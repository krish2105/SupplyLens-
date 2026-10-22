"""DEF-10 probe: burst far past capacity, then check that accepted requests stay fast and recovery is immediate.

uv run python scripts/loadtest/overload_probe.py [--base http://localhost:8000] [--burst 120] [--concurrency 60]
Writes artifacts/reports/overload_probe_<stamp>.json. Local evidence only; the declared load profile is ARC-07.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import httpx

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://localhost:8000")
ap.add_argument("--burst", type=int, default=120)
ap.add_argument("--concurrency", type=int, default=60)
a = ap.parse_args()
H = {"X-Requested-With": "supplylens", "X-SupplyLens-Tenant": "uci-research"}
login = httpx.post(f"{a.base}/api/v1/auth/dev-login", json={"email": "viewer@dev.supplylens.local"}, headers=H)
cookies = login.cookies
QUERY = {"q": "minimum order quantity lead time", "k": 8}


def one(_):
    t0 = time.perf_counter()
    r = httpx.get(f"{a.base}/api/v1/evidence/search", params=QUERY, headers=H, cookies=cookies, timeout=120)
    return r.status_code, (time.perf_counter() - t0) * 1000


t0 = time.perf_counter()
with ThreadPoolExecutor(a.concurrency) as pool:
    results = list(pool.map(one, range(a.burst)))
burst_s = time.perf_counter() - t0
ok = sorted(ms for code, ms in results if code == 200)
shed = sorted(ms for code, ms in results if code == 503)
t1 = time.perf_counter()
after = one(0)
out = {
    "probe": "DEF-10 back-pressure", "at": datetime.now(UTC).isoformat(), "base": a.base,
    "burst_requests": a.burst, "client_concurrency": a.concurrency, "burst_seconds": round(burst_s, 2),
    "accepted": len(ok), "shed_503": len(shed), "other": len(results) - len(ok) - len(shed),
    "accepted_ms_p50": round(statistics.median(ok), 1) if ok else None,
    "accepted_ms_p95": round(ok[int(0.95 * (len(ok) - 1))], 1) if ok else None,
    "shed_ms_p95": round(shed[int(0.95 * (len(shed) - 1))], 1) if shed else None,
    "first_request_after_burst": {"status": after[0], "ms": round(after[1], 1),
                                  "seconds_after_burst": round(time.perf_counter() - t1, 2)},
}
stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
path = Path(__file__).resolve().parents[2] / "artifacts" / "reports" / f"overload_probe_{stamp}.json"
path.write_text(json.dumps(out, indent=2) + "\n")
print(json.dumps(out, indent=2))
