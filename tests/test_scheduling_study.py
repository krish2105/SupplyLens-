"""JS1 receiving-floor scheduling: the exact model and the dispatch rules produce valid schedules (week-5 study)."""
import importlib.util

import numpy as np

from supplylens.config import REPO_ROOT

spec = importlib.util.spec_from_file_location("scheduling_study", REPO_ROOT / "evaluations" / "scheduling_study.py")
js = importlib.util.module_from_spec(spec)
spec.loader.exec_module(js)


def test_cp_sat_solves_ft06_to_its_known_optimum():
    jobs = [{"ops": ops, "due": 10**6} for ops in js.FT06]
    r = js.cp_sat(jobs, limit=10)
    assert r["status"] == "OPTIMAL" and r["objective"] == 55
    assert js.feasible(jobs, r["schedule"])


def test_every_dispatch_rule_gives_a_feasible_schedule_no_shorter_than_the_optimum():
    jobs = [{"ops": ops, "due": 30 + 5 * i} for i, ops in enumerate(js.FT06)]
    for rule in ("FIFO", "SPT", "EDD", "MWKR"):
        sched = js.dispatch(jobs, rule)
        assert js.feasible(jobs, sched)
        assert js.evaluate(jobs, sched)["makespan"] >= 55


def test_feasibility_check_catches_overlap_and_broken_routes():
    jobs = [{"ops": [(0, 3), (1, 2)], "due": 10}, {"ops": [(0, 2), (1, 4)], "due": 10}]
    assert js.feasible(jobs, [[(0, 0, 3), (3, 1, 2)], [(3, 0, 2), (5, 1, 4)]])
    assert not js.feasible(jobs, [[(0, 0, 3), (3, 1, 2)], [(1, 0, 2), (5, 1, 4)]])     # two orders on the dock at once
    assert not js.feasible(jobs, [[(0, 0, 3), (2, 1, 2)], [(3, 0, 2), (5, 1, 4)]])     # quality before unloading ended


def test_generated_orders_follow_their_lane_route():
    jobs = js.instance(np.random.default_rng(0), 12, [50.0, 120.0, 400.0])
    for j in jobs:
        assert [m for m, _ in j["ops"]] == js.ROUTES[j["lane"]] and all(p > 0 for _, p in j["ops"]) and j["due"] > 0
