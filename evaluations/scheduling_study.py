"""JS1: scheduling the receiving floor (job shop). Exact CP-SAT schedules against hand dispatch rules.

An approved purchase plan becomes work for the warehouse. Each inbound order (a job) passes four stations (machines) —
dock unloading, quality check, labelling, put-away — on a route that depends on its freight lane (ASSUMED: sea
containers are inspected before labelling because customs paperwork arrives first; road deliveries are labelled at the
dock). Processing minutes scale with the order's units, drawn around the real weekly sales of UCI products; due times come
from the order's promised slot. Questions: how much shorter is an optimal schedule than the dispatch rules a floor lead
would use (FIFO, shortest processing time, earliest due date, most work remaining), and how long does it take to find it?

Check: the classic Fisher-Thompson 6x6 instance (ft06), whose optimal makespan is known to be 55.
Simulated routes, processing times and due times; real product volumes. Nothing here is a measured floor.

uv run python evaluations/scheduling_study.py
"""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import numpy as np
from ortools.sat.python import cp_model
from sqlalchemy import text

from supplylens.config import REPO_ROOT
from supplylens.db import tenant_session
from supplylens.seed import tenant_id

SEED = 5
STATIONS = ["dock", "quality", "label", "put-away"]
ROUTES = {"road": [0, 2, 1, 3], "sea": [0, 1, 2, 3], "express": [0, 2, 3, 1]}   # ASSUMED routes by lane
MIN_PER_UNIT = {0: 0.06, 1: 0.10, 2: 0.04, 3: 0.08}                               # ASSUMED handling minutes per unit
SETUP_MIN = {0: 6, 1: 4, 2: 2, 3: 5}
SIZES = (10, 20, 40)
REPEATS = 3
TIME_LIMIT_S = 20.0

# Fisher & Thompson (1963) 6x6 instance: per job, (machine, minutes) in route order. Optimal makespan 55.
FT06 = [[(2, 1), (0, 3), (1, 6), (3, 7), (5, 3), (4, 6)],
        [(1, 8), (2, 5), (4, 10), (5, 10), (0, 10), (3, 4)],
        [(2, 5), (3, 4), (5, 8), (0, 9), (1, 1), (4, 7)],
        [(1, 5), (0, 5), (2, 5), (3, 3), (4, 8), (5, 9)],
        [(2, 9), (1, 3), (4, 5), (5, 4), (0, 3), (3, 1)],
        [(1, 3), (3, 3), (5, 9), (0, 10), (4, 4), (2, 1)]]


def weekly_volumes() -> list[float]:
    with tenant_session(tenant_id("uci-research")) as s:
        return [float(r[0]) for r in s.execute(text(
            "SELECT sum(units)::float / 104 FROM sales_daily GROUP BY sku_id HAVING sum(units) > 2000 ORDER BY 1 DESC LIMIT 400")).all()]


def instance(rng, n: int, volumes: list[float]):
    jobs = []
    for _ in range(n):
        units = max(20, int(rng.poisson(rng.choice(volumes))))
        lane = rng.choice(["road", "sea", "express"], p=[0.55, 0.3, 0.15])
        ops = [(m, int(round(SETUP_MIN[m] + MIN_PER_UNIT[m] * units))) for m in ROUTES[lane]]
        jobs.append({"ops": ops, "lane": str(lane), "units": units})
    total = sum(p for j in jobs for _, p in j["ops"])
    for j in jobs:                                  # promised slot: own work plus a share of the shift's load
        own = sum(p for _, p in j["ops"])
        j["due"] = int(own + rng.uniform(0.15, 0.6) * total / len(STATIONS))
    return jobs


def cp_sat(jobs, objective: str = "makespan", limit: float = TIME_LIMIT_S):
    m = cp_model.CpModel()
    horizon = sum(p for j in jobs for _, p in j["ops"])
    machines = {}
    ends, starts = [], {}
    for ji, j in enumerate(jobs):
        prev = None
        for oi, (mach, p) in enumerate(j["ops"]):
            s = m.NewIntVar(0, horizon, f"s{ji}_{oi}")
            e = m.NewIntVar(0, horizon, f"e{ji}_{oi}")
            iv = m.NewIntervalVar(s, p, e, f"i{ji}_{oi}")
            machines.setdefault(mach, []).append(iv)
            starts[(ji, oi)] = s
            if prev is not None:
                m.Add(s >= prev)
            prev = e
        ends.append(prev)
    for ivs in machines.values():
        m.AddNoOverlap(ivs)
    mk = m.NewIntVar(0, horizon, "makespan")
    m.AddMaxEquality(mk, ends)
    if objective == "makespan":
        m.Minimize(mk)
    else:
        tard = []
        for ji, j in enumerate(jobs):
            t = m.NewIntVar(0, horizon, f"t{ji}")
            m.Add(t >= ends[ji] - j.get("due", horizon))
            tard.append(t)
        m.Minimize(sum(tard))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = limit
    solver.parameters.num_workers = 8
    solver.parameters.random_seed = 0
    t0 = time.time()
    status = solver.Solve(m)
    dt = time.time() - t0
    sched = [[(int(solver.Value(starts[(ji, oi)])), mach, p) for oi, (mach, p) in enumerate(j["ops"])] for ji, j in enumerate(jobs)]
    return {"status": solver.StatusName(status), "seconds": round(dt, 3), "objective": int(solver.ObjectiveValue()),
            "bound": int(solver.BestObjectiveBound()), "schedule": sched}


def dispatch(jobs, rule: str):
    """Non-delay list scheduling: whenever a station is free and operations are waiting, start the one the rule picks."""
    n = len(jobs)
    nxt = [0] * n
    ready = [0] * n                       # when the job's next operation may start
    mfree: dict[int, int] = {}
    remaining = [sum(p for _, p in j["ops"]) for j in jobs]
    sched = [[None] * len(j["ops"]) for j in jobs]
    done = 0
    total_ops = sum(len(j["ops"]) for j in jobs)
    while done < total_ops:
        cands = [ji for ji in range(n) if nxt[ji] < len(jobs[ji]["ops"])]
        # earliest possible start over candidates; schedule among those that can start then (non-delay)
        est = {ji: max(ready[ji], mfree.get(jobs[ji]["ops"][nxt[ji]][0], 0)) for ji in cands}
        t = min(est.values())
        now = [ji for ji in cands if est[ji] == t]
        key = {"FIFO": lambda ji: (ready[ji], ji),
               "SPT": lambda ji: (jobs[ji]["ops"][nxt[ji]][1], ji),
               "EDD": lambda ji: (jobs[ji]["due"], ji),
               "MWKR": lambda ji: (-remaining[ji], ji)}[rule]
        ji = min(now, key=key)
        mach, p = jobs[ji]["ops"][nxt[ji]]
        sched[ji][nxt[ji]] = (t, mach, p)
        mfree[mach] = t + p
        ready[ji] = t + p
        remaining[ji] -= p
        nxt[ji] += 1
        done += 1
    return sched


def evaluate(jobs, sched):
    ends = [max(s + p for s, _, p in ops) for ops in sched]
    tard = [max(0, e - j["due"]) for e, j in zip(ends, jobs, strict=True)]
    return {"makespan": int(max(ends)), "total_tardiness": int(sum(tard)), "late_jobs": int(sum(1 for t in tard if t > 0)),
            "mean_flow": round(float(np.mean(ends)), 1)}


def feasible(jobs, sched) -> bool:
    for ji, ops in enumerate(sched):
        for oi in range(1, len(ops)):
            if ops[oi][0] < ops[oi - 1][0] + ops[oi - 1][2]:
                return False
        if [(m, p) for _, m, p in ops] != jobs[ji]["ops"]:
            return False
    by_m: dict[int, list] = {}
    for ops in sched:
        for s, m, p in ops:
            by_m.setdefault(m, []).append((s, s + p))
    return all(b[0] >= a[1] for iv in by_m.values() for a, b in zip(sorted(iv), sorted(iv)[1:], strict=False))


def main() -> None:
    rng = np.random.default_rng(SEED)
    ft = [{"ops": ops, "due": 10**6} for ops in FT06]
    ft_res = cp_sat(ft)
    assert feasible(ft, ft_res["schedule"])
    ft_rules = {r: evaluate(ft, dispatch(ft, r))["makespan"] for r in ("FIFO", "SPT", "EDD", "MWKR")}
    print("ft06", ft_res["status"], ft_res["objective"], ft_rules)

    vols = weekly_volumes()
    rows, gantt = [], None
    for n in SIZES:
        for rep in range(REPEATS):
            jobs = instance(rng, n, vols)
            exact = cp_sat(jobs, "makespan")
            exact_t = cp_sat(jobs, "tardiness")
            assert feasible(jobs, exact["schedule"]) and feasible(jobs, exact_t["schedule"])
            row = {"jobs": n, "repeat": rep, "operations": n * len(STATIONS),
                   "cp_sat_makespan": {**evaluate(jobs, exact["schedule"]), "status": exact["status"], "seconds": exact["seconds"],
                                       "lower_bound": exact["bound"]},
                   "cp_sat_tardiness": {**evaluate(jobs, exact_t["schedule"]), "status": exact_t["status"], "seconds": exact_t["seconds"]},
                   "rules": {}}
            for r in ("FIFO", "SPT", "EDD", "MWKR"):
                sch = dispatch(jobs, r)
                assert feasible(jobs, sch)
                row["rules"][r] = evaluate(jobs, sch)
            rows.append(row)
            if n == 10 and rep == 0:
                gantt = {"jobs": [{"lane": j["lane"], "units": j["units"], "due": j["due"]} for j in jobs],
                         "cp_sat": exact["schedule"], "FIFO": dispatch(jobs, "FIFO")}
            print(n, rep, row["cp_sat_makespan"]["makespan"], row["cp_sat_makespan"]["status"],
                  {r: v["makespan"] for r, v in row["rules"].items()})

    def gap(rule, metric):
        vals = [(r["rules"][rule][metric] - r["cp_sat_makespan" if metric == "makespan" else "cp_sat_tardiness"][metric])
                / max(1, r["cp_sat_makespan" if metric == "makespan" else "cp_sat_tardiness"][metric]) for r in rows]
        return round(float(np.mean(vals)), 4)
    summary = {"makespan_gap_vs_cp_sat": {r: gap(r, "makespan") for r in ("FIFO", "SPT", "EDD", "MWKR")},
               "tardiness_gap_vs_cp_sat": {r: gap(r, "total_tardiness") for r in ("FIFO", "SPT", "EDD", "MWKR")},
               "cp_sat_proven_optimal_makespan": sum(r["cp_sat_makespan"]["status"] == "OPTIMAL" for r in rows),
               "instances": len(rows),
               "best_rule_by_size": {n: min(("FIFO", "SPT", "EDD", "MWKR"), key=lambda r, n=n: np.mean([x["rules"][r]["makespan"] for x in rows if x["jobs"] == n]))
                                     for n in SIZES}}
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = REPO_ROOT / "artifacts" / "experiments" / f"JS1-{stamp}"
    out.mkdir(parents=True)
    metrics = {"experiment_id": out.name, "study": "JS1", "kind": "simulated",
               "question": "How much shorter is an optimal receiving-floor schedule than the dispatch rules a floor lead would use?",
               "check_ft06": {"known_optimum": 55, "cp_sat": ft_res["objective"], "status": ft_res["status"], "seconds": ft_res["seconds"],
                              "rules": ft_rules},
               "setup": {"stations": STATIONS, "routes": {k: [STATIONS[i] for i in v] for k, v in ROUTES.items()},
                         "minutes_per_unit": {STATIONS[k]: v for k, v in MIN_PER_UNIT.items()}, "setup_minutes": {STATIONS[k]: v for k, v in SETUP_MIN.items()},
                         "sizes": SIZES, "repeats": REPEATS, "time_limit_s": TIME_LIMIT_S, "seed": SEED},
               "instances": rows, "summary": summary, "gantt_example": gantt,
               "limits": ["routes, handling times and due slots are assumed; product volumes are real UCI weekly sales",
                          "one shift, no breakdowns or arrivals during the shift (static job shop)",
                          "dispatch rules are non-delay list schedules, the usual hand method"]}
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1, default=str))
    print(json.dumps({"experiment_id": out.name, "check_ft06": metrics["check_ft06"], "summary": summary}, indent=1, default=str))


if __name__ == "__main__":
    main()
