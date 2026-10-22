"""ARC-07 / BUS-015 load driver.

    uv run python scripts/loadtest/run_load.py --base http://127.0.0.1:8100 --phase warm --seconds 240 --out artifacts/reports/loadtest-warm.json

Traffic model (declared, so the result can be reproduced and challenged):
  * 20 interactive users, each with their own account. A user opens a "screen" (the set of reads that screen makes,
    issued in parallel), then thinks for 4-8 s (uniform) before the next screen. Closed loop.
  * Retrieval (GET /evidence/search) is a separate OPEN-loop stream at a fixed 5 requests/second, spread over the
    users round-robin, so a slow response cannot slow the arrival rate (no coordinated omission).
  * Latencies are measured at the client, per request, from send to the last byte of the body.
Separate single-user benchmarks (--phase batch) time forecasting, the optimiser and the agent run, which ARC-07 says must
not be hidden inside the interactive numbers.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import random
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np

TENANT = "load-ref"
USERS = 20
SCREENS = {   # what each screen reads, in parallel
    "overview": ["/api/v1/overview", "/api/v1/alerts"],
    "inventory": ["/api/v1/inventory", "/api/v1/warehouse"],
    "exceptions": ["/api/v1/exceptions", "/api/v1/alerts"],
    "product": ["/api/v1/products/{sku}/sales", "/api/v1/terms?sku_id={sku}"],
    "documents": ["/api/v1/documents"],
    "runs": ["/api/v1/agent-runs", "/api/v1/actions"],
    "data": ["/api/v1/datasets", "/api/v1/models"],
}
SCREEN_WEIGHTS = {"overview": 25, "inventory": 15, "exceptions": 20, "product": 20, "documents": 5, "runs": 10, "data": 5}
DOMAIN = ("supplier lead time minimum order quantity price break payment terms penalty delivery warranty liability "
          "indemnity termination renewal audit confidential governing law force majeure exclusivity rebate discount "
          "shipment pallet carton inspection quality defect return credit invoice currency tariff incoterm packaging").split()


def pct(xs, p):
    return float(np.percentile(xs, p)) if xs else None


def summarise(samples: list[tuple[float, int]]) -> dict:
    ok = [s for s, c in samples if 200 <= c < 300]
    codes: dict[str, int] = {}
    for _, c in samples:
        codes[str(c)] = codes.get(str(c), 0) + 1
    return {"n": len(samples), "failed": len(samples) - len(ok), "status_codes": codes,
            "p50_ms": pct(ok, 50), "p95_ms": pct(ok, 95), "p99_ms": pct(ok, 99), "max_ms": max(ok) if ok else None,
            "mean_ms": statistics.fmean(ok) if ok else None}


def _ps_snapshot() -> dict[int, tuple[float, int, str]]:
    """pid -> (cumulative CPU seconds, RSS KB, command) for every process, from `ps` (macOS and other non-Linux hosts)."""
    out = subprocess.run(["ps", "-A", "-o", "pid=,time=,rss=,command="], capture_output=True, text=True).stdout
    snap = {}
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4 or not parts[0].isdigit():
            continue
        t = parts[1].replace("-", ":").split(":")          # [[dd-]hh:]mm:ss.cc
        secs = sum(float(x) * m for x, m in zip(reversed(t), (1, 60, 3600, 86400), strict=False))
        snap[int(parts[0])] = (secs, int(parts[2]), parts[3])
    return snap


def pids_matching(*needles: str) -> list[int]:
    out = []
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                cmd = open(f"/proc/{p}/cmdline", "rb").read().replace(b"\0", b" ").decode()
            except OSError:
                continue
            if all(n in cmd for n in needles):
                out.append(int(p))
    return out


def cpu_ticks(pid: int) -> int | None:
    try:
        f = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
        return int(f[11]) + int(f[12])
    except OSError:
        return None


def rss_kb(pid: int) -> int:
    try:
        return int(open(f"/proc/{pid}/statm").read().split()[1]) * (os.sysconf("SC_PAGE_SIZE") // 1024)
    except OSError:
        return 0


class Sampler:
    """1 Hz CPU/RSS sampling of the API, PostgreSQL and the load driver itself (all share this machine). Reads /proc on
    Linux and `ps` elsewhere (cumulative CPU time, 10 ms resolution)."""
    def __init__(self, api_marker: str):
        self.api_marker = api_marker
        self.groups = {"api": lambda: pids_matching("uvicorn", api_marker), "postgres": lambda: [int(p) for p in os.listdir("/proc") if p.isdigit() and _comm(p) == "postgres"],
                       "driver": lambda: [os.getpid()]}
        self.series: dict[str, list[tuple[float, float]]] = {k: [] for k in self.groups}
        self.last: dict[str, dict[int, float]] = {k: {} for k in self.groups}
        self.stop = False
        self.linux = os.path.isdir("/proc/self")
        self.tick = os.sysconf("SC_CLK_TCK")

    def _group_of(self, pid: int, cmd: str) -> str | None:
        if pid == os.getpid():
            return "driver"
        if "uvicorn" in " ".join(cmd.split()[:3]) and self.api_marker in cmd:      # the server, not a shell quoting it
            return "api"
        exe = cmd.split()[0] if cmd else ""
        if exe.endswith("/postgres") or exe == "postgres" or cmd.startswith("postgres:"):
            return "postgres"
        return None

    def _sample(self) -> dict[str, tuple[dict[int, float], int]]:
        """group -> ({pid: cumulative CPU seconds}, total RSS KB)."""
        if self.linux:
            res = {}
            for g, finder in self.groups.items():
                cur, rss = {}, 0
                for pid in finder():
                    t = cpu_ticks(pid)
                    if t is not None:
                        cur[pid] = t / self.tick
                        rss += rss_kb(pid)
                res[g] = (cur, rss)
            return res
        res = {g: ({}, 0) for g in self.groups}
        for pid, (secs, rss, cmd) in _ps_snapshot().items():
            g = self._group_of(pid, cmd)
            if g:
                cur, total = res[g]
                cur[pid] = secs
                res[g] = (cur, total + rss)
        return res

    async def run(self):
        prev = time.time()
        while not self.stop:
            await asyncio.sleep(1.0)
            now = time.time(); dt = now - prev; prev = now
            for g, (cur, rss) in (await asyncio.to_thread(self._sample)).items():
                used = sum(t - self.last[g].get(pid, t) for pid, t in cur.items())
                self.last[g] = cur
                self.series[g].append((used / dt, rss / 1024))

    def summary(self) -> dict:
        out = {}
        for g, s in self.series.items():
            if s:
                cpu = [a for a, _ in s]
                out[g] = {"cpu_cores_mean": round(statistics.fmean(cpu), 2), "cpu_cores_max": round(max(cpu), 2), "rss_mb_max": round(max(b for _, b in s))}
        return out


def _comm(pid: str) -> str:
    try:
        return open(f"/proc/{pid}/comm").read().strip()
    except OSError:
        return ""


async def login(base: str, i: int) -> httpx.AsyncClient:
    c = httpx.AsyncClient(base_url=base, timeout=120, headers={"X-SupplyLens-Tenant": TENANT, "X-Requested-With": "supplylens"},
                          limits=httpx.Limits(max_connections=50))
    r = await c.post("/api/v1/auth/dev-login", json={"email": f"load{i:02d}@dev.supplylens.local"})
    r.raise_for_status()
    return c


TRANSPORT_ERRORS: dict[str, int] = {}     # client-side failures (no HTTP response), recorded as status 599, by type


async def timed(c: httpx.AsyncClient, url: str, bucket: dict, name: str):
    t = time.perf_counter()
    try:
        r = await c.get(url)
        _ = r.content
        code = r.status_code
    except Exception as e:
        code = 599
        TRANSPORT_ERRORS[type(e).__name__] = TRANSPORT_ERRORS.get(type(e).__name__, 0) + 1
    bucket.setdefault(name, []).append(((time.perf_counter() - t) * 1000, code))


async def interactive(users: list[httpx.AsyncClient], u: int, deadline: float, bucket: dict, rng: random.Random):
    names, weights = zip(*SCREEN_WEIGHTS.items(), strict=True)
    c = users[u]
    await asyncio.sleep(rng.uniform(0, 6))                 # stagger arrivals
    while time.time() < deadline:
        screen = rng.choices(names, weights)[0]
        sku = f"L{rng.randint(1, 2000):05d}"
        await asyncio.gather(*[timed(c, p.format(sku=sku), bucket, p.split("?")[0].replace(sku, "{sku}")) for p in SCREENS[screen]])
        await asyncio.sleep(rng.uniform(4, 8))


async def retrieval(users: list[httpx.AsyncClient], rate: float, deadline: float, bucket: dict, words: list[str], rng: random.Random):
    tasks, i, t0 = [], 0, time.time()
    while time.time() < deadline:
        due = t0 + i / rate
        await asyncio.sleep(max(0.0, due - time.time()))
        q = " ".join(rng.sample(DOMAIN, 2) + rng.choices(words, k=rng.randint(0, 1)))
        tasks.append(asyncio.create_task(timed(users[i % len(users)], f"/api/v1/evidence/search?q={q.replace(' ', '+')}&k=8", bucket, "GET /evidence/search")))
        i += 1
    await asyncio.gather(*tasks)


async def compute(c: httpx.AsyncClient, u: int, deadline: float, bucket: dict):
    """A planner running 60-SKU scenarios (the per-run maximum, D-043) back to back (forecast + CP-SAT), to measure whether
    compute starves retrieval."""
    i = 0
    while time.time() < deadline:
        skus = [f"L{(u * 400 + i * 60 + k) % 2000 + 1:05d}" for k in range(60)]
        t = time.perf_counter()
        try:
            r = await c.post("/api/v1/scenarios", json={"name": f"load-{u}-{i}", "sku_ids": skus},
                             headers={"Idempotency-Key": f"compute-{u}-{i}-{time.time_ns()}"})
            code = r.status_code
        except Exception:
            code = 599
        bucket.setdefault("POST /scenarios", []).append(((time.perf_counter() - t) * 1000, code))
        if code in (429, 503):
            await asyncio.sleep(2)
        i += 1


def vocabulary_sample() -> list[str]:
    """Mid-frequency pseudo-words (ranks 150-600) from the same vocabulary the corpus was built from."""
    from seed_reference import vocabulary
    words = vocabulary(np.random.default_rng(20111208))
    return [w for w in words[150:600] if w not in DOMAIN]


async def interactive_phase(a) -> dict:
    users = [await login(a.base, i) for i in range(USERS)]
    rng = random.Random(7)
    bucket: dict[str, list] = {}
    sampler = Sampler(a.api_marker)
    st = asyncio.create_task(sampler.run())
    t0 = time.time(); deadline = t0 + a.seconds
    planners = [users[i] for i in range(0, USERS, 4)][:a.compute_users]      # load00, load04, ... are planners
    await asyncio.gather(retrieval(users, a.retrieval_rate, deadline, bucket, vocabulary_sample(), rng),
                         *[interactive(users, u, deadline, bucket, random.Random(100 + u)) for u in range(USERS)],
                         *[compute(c, u, deadline, bucket) for u, c in enumerate(planners)])
    elapsed = time.time() - t0
    sampler.stop = True; await st
    meta = [x for k, v in bucket.items() if k not in ("GET /evidence/search", "POST /scenarios") for x in v]
    for c in users:
        await c.aclose()
    return {"seconds": round(elapsed, 1), "metadata_reads": {**summarise(meta), "rps": round(len(meta) / elapsed, 2)},
            "retrieval": {**summarise(bucket.get("GET /evidence/search", [])), "rps": round(len(bucket.get("GET /evidence/search", [])) / elapsed, 2)},
            "compute": {**summarise(bucket.get("POST /scenarios", [])), "users": a.compute_users},
            "client_transport_errors": dict(TRANSPORT_ERRORS),
            "per_endpoint": {k: summarise(v) for k, v in sorted(bucket.items())}, "resources": sampler.summary()}


async def batch_phase(a) -> dict:
    c = await login(a.base, 0)                    # load00 is a planner
    skus = [f"L{i:05d}" for i in range(1, 2001)]
    out: dict = {}
    sampler = Sampler(a.api_marker); st = asyncio.create_task(sampler.run())

    async def post(path, body, name, store):
        t = time.perf_counter()
        r = await c.post(path, json=body, headers={"Idempotency-Key": f"bench-{name}-{time.time_ns()}"})
        store.append(((time.perf_counter() - t) * 1000, r.status_code))
        return r

    f200: list = []
    for i in range(5):
        await post("/api/v1/forecasts", {"sku_ids": skus[i * 200:(i + 1) * 200], "model_family": "seasonal_naive"}, "f200", f200)
    out["forecast_200_skus_seasonal_naive"] = summarise(f200)
    t = time.perf_counter(); codes = []
    for i in range(10):
        r = await post("/api/v1/forecasts", {"sku_ids": skus[i * 200:(i + 1) * 200], "model_family": "seasonal_naive"}, "fall", [])
        codes.append(r.status_code)
    out["batch_forecast_all_2000_skus"] = {"seconds": round(time.perf_counter() - t, 1), "requests": 10, "status_codes": codes}
    s200: list = []
    for i in range(3):
        await post("/api/v1/scenarios", {"name": f"bench{i}", "sku_ids": skus[i * 200:(i + 1) * 200]}, "s200", s200)
    out["scenario_200_skus_forecast_plus_cpsat"] = summarise(s200)
    # The API plans at most 200 SKUs per run, so the whole 2,000-SKU catalogue is ten runs.
    t = time.perf_counter(); full: list = []
    for i in range(10):
        await post("/api/v1/scenarios", {"name": f"bench-full-{i}", "sku_ids": skus[i * 200:(i + 1) * 200]}, "sfull", full)
    out["scenario_full_catalogue_10_runs_of_200"] = {"seconds": round(time.perf_counter() - t, 1), **summarise(full)}
    r = await c.post("/api/v1/scenarios", json={"name": "bench-all"})
    out["scenario_without_sku_list_on_2000_skus"] = {"status_code": r.status_code, "message": r.json().get("message")}
    # agent run end-to-end (needs a worker on the same database)
    runs = []
    for i in range(2):
        t = time.perf_counter()
        r = await post("/api/v1/agent-runs", {"mode": "draft", "sku_ids": skus[i * 50:(i + 1) * 50]}, "run", [])
        if r.status_code != 202:
            runs.append({"status": r.status_code}); continue
        rid = r.json()["run_id"] if "run_id" in r.json() else r.json().get("id")
        status = None
        while time.perf_counter() - t < 300:
            d = (await c.get(f"/api/v1/agent-runs/{rid}")).json()
            status = d.get("status")
            if status in ("SUCCEEDED", "FAILED", "CANCELLED", "REVIEW_REQUIRED", "WAITING_FOR_APPROVAL", "COMPLETE"):
                break
            await asyncio.sleep(0.5)
        runs.append({"status": status, "seconds": round(time.perf_counter() - t, 1)})
    out["agent_run_50_skus_end_to_end"] = runs
    sampler.stop = True; await st
    out["resources"] = sampler.summary()
    await c.aclose()
    return out


def host_info() -> dict:
    if os.path.exists("/proc/meminfo"):
        mem = {l.split(":")[0]: l.split(":")[1].strip() for l in open("/proc/meminfo")}.get("MemTotal")
        cpu = [l.split(":")[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name")]
        model = cpu[0] if cpu else "unknown"
    else:                                   # macOS
        def sysctl(k):
            return subprocess.run(["sysctl", "-n", k], capture_output=True, text=True).stdout.strip()
        model, mem = sysctl("machdep.cpu.brand_string") or "unknown", f"{int(sysctl('hw.memsize') or 0) // 1024} kB"
    return {"vcpus": os.cpu_count(), "cpu_model": model, "mem_total": mem, "os": platform.system(), "kernel": platform.release(),
            "python": platform.python_version(), "note": "API, worker, PostgreSQL and this driver all run on the same machine"}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8100")
    ap.add_argument("--phase", choices=["interactive", "batch"], default="interactive")
    ap.add_argument("--condition", default="warm")
    ap.add_argument("--seconds", type=int, default=240)
    ap.add_argument("--retrieval-rate", type=float, default=5.0)
    ap.add_argument("--compute-users", type=int, default=0, help="planners running 60-SKU scenarios back to back (0-5)")
    ap.add_argument("--api-marker", default="--port 8100")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    res = await (interactive_phase(a) if a.phase == "interactive" else batch_phase(a))
    doc = {"generated_at": datetime.now(UTC).isoformat(), "phase": a.phase, "condition": a.condition, "host": host_info(), "result": res}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(doc, indent=2))
    print(json.dumps(doc, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
