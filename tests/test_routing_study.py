"""RT1 last-mile routing (week-7 study, SIMULATED instances): the evaluator, the heuristics and the OR-Tools model."""
import importlib.util
import itertools

import numpy as np

from supplylens.config import REPO_ROOT

spec = importlib.util.spec_from_file_location("routing_study", REPO_ROOT / "evaluations" / "routing_study.py")
rt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rt)


def small_instance(window_share: float = 0.5):
    """The fixed small instance the brief asks for: 12 stops, vans of 12 parcels, half the stops with a window."""
    return rt.instance(np.random.default_rng(42), 12, window_share=window_share, capacity=12)


def test_haversine_is_the_great_circle_distance():
    assert abs(rt.haversine_km(0.0, 0.0, 1.0, 0.0) - 111.195) < 0.01
    inst = rt.build([(0, 0), (3, 4)], [0, 1], [(0, rt.SHIFT_MIN)] * 2)
    assert abs(inst["dist_km"][0, 1] - 5.0) < 0.01 and inst["dist_km"][1, 0] == inst["dist_km"][0, 1]


def test_solver_is_never_worse_than_nearest_neighbour_on_a_fixed_small_instance():
    inst = small_instance()
    sol = rt.solve(inst, time_limit_s=2)
    ortools = rt.evaluate(inst, sol["routes"])
    assert ortools["all_stops_once"] and ortools["capacity_ok"]
    for routes in (rt.nearest_neighbour(inst), rt.nearest_neighbour(inst, respect_windows=False), rt.fixed_order(inst)):
        other = rt.evaluate(inst, routes)
        assert other["all_stops_once"] and other["capacity_ok"]
        assert rt.objective(ortools) <= rt.objective(other) + 1e-6
    assert ortools["late_stops"] <= rt.evaluate(inst, rt.nearest_neighbour(inst))["late_stops"]
    assert abs(rt.objective(ortools) - sol["objective_m"] / 1000) < 0.05        # evaluator agrees with the solver
    no_windows = small_instance(window_share=0.0)                               # pure capacitated routing: distance only
    d_solver = rt.evaluate(no_windows, rt.solve(no_windows, time_limit_s=2)["routes"])["distance_km"]
    assert d_solver <= rt.evaluate(no_windows, rt.nearest_neighbour(no_windows))["distance_km"] + 1e-6


def test_single_van_solution_matches_brute_force_optimum():
    rng = np.random.default_rng(5)
    pts = [(0.0, 0.0)] + [tuple(rng.uniform(-5, 5, 2)) for _ in range(7)]
    inst = rt.build(pts, [0] + [1] * 7, [(0, rt.SHIFT_MIN)] * 8, vehicles=1)
    D = inst["dist_km"]
    best = min(D[0, p[0]] + sum(D[a, b] for a, b in itertools.pairwise(p)) + D[p[-1], 0]
               for p in itertools.permutations(range(1, 8)))
    got = rt.evaluate(inst, rt.solve(inst, time_limit_s=1)["routes"])["distance_km"]
    assert got <= best + 0.01                                                    # metre rounding only


def test_evaluator_counts_lateness_capacity_and_missing_stops():
    # stop 1 is 5 km east, stop 2 is 5 km west with a window closing 15 minutes after 08:00 (12 min away)
    inst = rt.build([(0, 0), (5, 0), (-5, 0)], [0, 2, 2], [(0, rt.SHIFT_MIN), (0, rt.SHIFT_MIN), (0, 15)], capacity=3)
    east_first = rt.evaluate(inst, [[1, 2]])
    assert east_first["late_stops"] == 1 and not east_first["capacity_ok"] and east_first["all_stops_once"]
    two_vans = rt.evaluate(inst, [[2], [1]])
    assert two_vans["late_stops"] == 0 and two_vans["capacity_ok"] and two_vans["vans"] == 2
    assert abs(two_vans["distance_km"] - 20.0) < 0.05
    assert not rt.evaluate(inst, [[1]])["all_stops_once"]
    assert two_vans["co2_kg"] == round(two_vans["distance_km"] * rt.PAYLOAD_T * rt.ROAD_KG_PER_TKM, 3)
    assert two_vans["fuel_l"] == round(two_vans["distance_km"] * rt.FUEL_L_PER_100KM / 100, 2)


def test_heuristics_visit_every_stop_once_within_capacity():
    inst = rt.instance(np.random.default_rng(9), 40, capacity=20)
    for routes in (rt.nearest_neighbour(inst), rt.nearest_neighbour(inst, respect_windows=False), rt.fixed_order(inst)):
        e = rt.evaluate(inst, routes)
        assert e["all_stops_once"] and e["capacity_ok"]
    plain = rt.evaluate(inst, rt.fixed_order(inst))
    assert plain["vans"] == len(rt.fixed_order(inst)) and plain["vans"] >= -(-sum(inst["demand"]) // 20)
