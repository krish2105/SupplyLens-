"""RT1: last-mile route planning with van capacity and delivery windows, on SIMULATED instances.

The course (Week 7) asks for "route-planning with last-mile constraints". The real courier-day data the brief names
(LaDe, Amazon Last Mile) needs the owner's approval, which has not been given, so the brief's fallback is used: labelled
synthetic instances. Nothing below is a measured route.

Instances: a depot and 20, 40 or 80 delivery stops (five seeds each) on synthetic coordinates around an arbitrary
reference point: 60 % of stops in three neighbourhood clusters, 40 % scattered within 8 km. Each stop has 1-6 parcels;
half have a two-hour delivery window between 09:00 and 17:00, the rest may be served any time in the 08:00-18:00 shift.
Vans carry 60 parcels and start at the depot at 08:00; the fleet is the number of vans the parcels need plus two.
Distances are haversine (straight-line) km; driving time = haversine km / 25 km/h (ASSUMED straight-line-equivalent
speed); doorstep time 3 min + 0.5 min per parcel. Arriving early means waiting for the window to open; late means
starting service after the window (or the shift) has closed.

Ways to plan the same instance, all scored by one evaluator:
- OR-Tools routing (pywrapcp): capacity as a hard constraint, windows as soft upper bounds (cost per second late),
  a fixed cost per van used, path-cheapest-arc start, guided local search, fixed time limit;
- nearest neighbour: each van goes to the closest stop it can still reach before its window closes and has room for,
  returns when none is left, and the next van starts (the last van in the fleet takes whatever remains); also reported
  in its plain form, which ignores windows (closest stop with room);
- fixed order: stops sorted by compass angle around the depot, cut into van loads, windows ignored. It stands in for a
  habitual street or postcode sequence; it is NOT a real driver's sequence.
Reported: total distance, late stops, vans used, solve time, and fuel and CO2 from distance with assumed factors: an
ASSUMED average van payload x the rounded UK DESNZ road freight factor E1 uses (0.1 kg CO2e per tonne-km), and an
ASSUMED fuel use per 100 km. Fuel and CO2 are proportional to distance, so their savings equal the distance savings.

uv run python evaluations/routing_study.py
"""
from __future__ import annotations

import json
import math
import time
from datetime import UTC, datetime

import numpy as np
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from supplylens.config import REPO_ROOT
from supplylens_opt.emissions import ROAD_KG_PER_TKM

SIZES = (20, 40, 80)
SEEDS = (1, 2, 3, 4, 5)
TIME_LIMIT_S = 10
EARTH_RADIUS_KM = 6371.0088
REF_LATLON = (0.0, 0.0)            # arbitrary reference point for the synthetic coordinates; not a real service area
KM_PER_DEG = math.pi * EARTH_RADIUS_KM / 180
SHIFT_MIN, HORIZON_MIN = 600, 720  # minutes after 08:00: shift ends 18:00; no van may run past 20:00
SPEED_KMH = 25.0                   # ASSUMED straight-line-equivalent driving speed
SERVICE_MIN, SERVICE_PER_PARCEL_MIN = 3.0, 0.5
CAPACITY = 60                      # parcels per van (ASSUMED)
SPARE_VANS = 2
WINDOW_SHARE = 0.5
WINDOWS = ((60, 180), (180, 300), (300, 420), (420, 540))   # 09-11, 11-13, 13-15, 15-17
CLUSTERS, CLUSTER_SHARE, CLUSTER_SD_KM, SCATTER_KM = 3, 0.6, 1.0, 8.0
VAN_FIXED_KM = 20                  # solver objective only: using one more van costs as much as 20 km (ASSUMED)
LATE_M_PER_S = 20                  # solver objective only: each second late costs 20 m (1.2 km per minute; ASSUMED)
PAYLOAD_T = 0.5                    # ASSUMED average payload carried per van, tonnes
FUEL_L_PER_100KM = 9.0             # ASSUMED diesel van fuel use; not measured, not a DESNZ figure
LATE_TOLERANCE_MIN = 1e-6


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle (straight-line) distance in km; inputs in degrees, scalars or arrays."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def build(xy_km, demand, windows, vehicles: int | None = None, capacity: int = CAPACITY) -> dict:
    """An instance from planar km offsets (row 0 = depot), parcels per stop and (open, close) windows in minutes."""
    xy = np.asarray(xy_km, float)
    lat = REF_LATLON[0] + xy[:, 1] / KM_PER_DEG
    lon = REF_LATLON[1] + xy[:, 0] / (KM_PER_DEG * math.cos(math.radians(REF_LATLON[0])))
    dist = haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
    demand = [int(d) for d in demand]
    service = [0.0] + [SERVICE_MIN + SERVICE_PER_PARCEL_MIN * d for d in demand[1:]]
    if vehicles is None:
        vehicles = math.ceil(sum(demand) / capacity) + SPARE_VANS
    return {"latlon": np.c_[lat, lon], "dist_km": dist, "drive_min": dist / SPEED_KMH * 60, "demand": demand,
            "service_min": service, "window": [tuple(w) for w in windows], "vehicles": vehicles, "capacity": capacity,
            "angle": np.arctan2(xy[:, 1] - xy[0, 1], xy[:, 0] - xy[0, 0]) % (2 * math.pi)}


def instance(rng, n: int, window_share: float = WINDOW_SHARE, capacity: int = CAPACITY) -> dict:
    """A SIMULATED instance: depot at the reference point, n stops (clustered and scattered)."""
    centres = [(r * math.cos(a), r * math.sin(a)) for r, a in zip(rng.uniform(2, 7, CLUSTERS), rng.uniform(0, 2 * math.pi, CLUSTERS), strict=True)]
    pts = []
    for _ in range(n):
        if rng.random() < CLUSTER_SHARE:
            c = centres[int(rng.integers(CLUSTERS))]
            pts.append((c[0] + rng.normal(0, CLUSTER_SD_KM), c[1] + rng.normal(0, CLUSTER_SD_KM)))
        else:
            r, a = SCATTER_KM * math.sqrt(rng.random()), rng.uniform(0, 2 * math.pi)
            pts.append((r * math.cos(a), r * math.sin(a)))
    demand = [0] + [int(min(6, 1 + rng.poisson(1.5))) for _ in range(n)]
    windows = [(0, SHIFT_MIN)] + [WINDOWS[int(rng.integers(len(WINDOWS)))] if rng.random() < window_share else (0, SHIFT_MIN)
                                  for _ in range(n)]
    return build([(0.0, 0.0), *pts], demand, windows, capacity=capacity)


def evaluate(inst: dict, routes: list[list[int]]) -> dict:
    """Score routes (lists of stop numbers, depot 0 implied at both ends) with one set of rules for every method."""
    D, T, W = inst["dist_km"], inst["drive_min"], inst["window"]
    n = len(inst["demand"]) - 1
    routes = [r for r in routes if r]
    seen = sorted(s for r in routes for s in r)
    dist = late_min = over_min = 0.0
    late = overtime_routes = 0
    loads, returns = [], []
    for r in routes:
        t, prev = 0.0, 0
        for s in r:
            dist += D[prev, s]
            start = max(t + T[prev, s], W[s][0])
            if start > W[s][1] + LATE_TOLERANCE_MIN:
                late += 1
                late_min += start - W[s][1]
            t, prev = start + inst["service_min"][s], s
        dist += D[prev, 0]
        t += T[prev, 0]
        returns.append(t)
        overtime_routes += int(t > SHIFT_MIN + LATE_TOLERANCE_MIN)
        over_min += max(0.0, t - SHIFT_MIN)
        loads.append(sum(inst["demand"][s] for s in r))
    return {"distance_km": round(float(dist), 3), "late_stops": late, "late_minutes": round(float(late_min), 1),
            "vans": len(routes), "vans_over_fleet": max(0, len(routes) - inst["vehicles"]),
            "overtime_routes": overtime_routes, "overtime_minutes": round(float(over_min), 1),
            "last_return_min": round(float(max(returns, default=0.0)), 1),
            "capacity_ok": all(x <= inst["capacity"] for x in loads), "all_stops_once": seen == list(range(1, n + 1)),
            "fuel_l": round(float(dist) * FUEL_L_PER_100KM / 100, 2),
            "co2_kg": round(float(dist) * PAYLOAD_T * ROAD_KG_PER_TKM, 3)}


def objective(score: dict) -> float:
    """The solver's own objective re-computed from an evaluation (km): distance + van cost + lateness cost."""
    late = score["late_minutes"] + score["overtime_minutes"]
    return score["distance_km"] + VAN_FIXED_KM * score["vans"] + LATE_M_PER_S * 60 * late / 1000


def solve(inst: dict, time_limit_s: float = TIME_LIMIT_S) -> dict:
    """OR-Tools routing: capacity hard, windows and shift end soft, fixed cost per van, guided local search."""
    n_nodes, V = len(inst["demand"]), inst["vehicles"]
    dist_m = np.rint(inst["dist_km"] * 1000).astype(int).tolist()
    # transit seconds = doorstep time at the origin + driving time, rounded up so the solver is never optimistic
    tr_s = [[int(round(inst["service_min"][i] * 60)) + math.ceil(inst["drive_min"][i][j] * 60 - 1e-9) for j in range(n_nodes)]
            for i in range(n_nodes)]
    manager = pywrapcp.RoutingIndexManager(n_nodes, V, 0)
    routing = pywrapcp.RoutingModel(manager)
    dist_cb = routing.RegisterTransitCallback(lambda i, j: dist_m[manager.IndexToNode(i)][manager.IndexToNode(j)])
    routing.SetArcCostEvaluatorOfAllVehicles(dist_cb)
    routing.SetFixedCostOfAllVehicles(VAN_FIXED_KM * 1000)
    load_cb = routing.RegisterUnaryTransitCallback(lambda i: inst["demand"][manager.IndexToNode(i)])
    routing.AddDimensionWithVehicleCapacity(load_cb, 0, [inst["capacity"]] * V, True, "load")
    time_cb = routing.RegisterTransitCallback(lambda i, j: tr_s[manager.IndexToNode(i)][manager.IndexToNode(j)])
    routing.AddDimension(time_cb, HORIZON_MIN * 60, HORIZON_MIN * 60, True, "time")
    td = routing.GetDimensionOrDie("time")
    for node in range(1, n_nodes):
        idx = manager.NodeToIndex(node)
        open_, close = inst["window"][node]
        td.CumulVar(idx).SetRange(int(open_ * 60), HORIZON_MIN * 60)
        td.SetCumulVarSoftUpperBound(idx, int(close * 60), LATE_M_PER_S)
    for v in range(V):
        td.SetCumulVarSoftUpperBound(routing.End(v), SHIFT_MIN * 60, LATE_M_PER_S)
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromMilliseconds(int(time_limit_s * 1000))
    found: list[tuple[float, int]] = []
    t0 = time.perf_counter()
    routing.AddAtSolutionCallback(lambda: found.append((time.perf_counter() - t0, int(routing.CostVar().Value()))))
    sol = routing.SolveWithParameters(params)
    seconds = time.perf_counter() - t0
    if sol is None:
        return {"routes": None, "status": int(routing.status()), "seconds": round(seconds, 3)}
    routes = []
    for v in range(V):
        idx, r = routing.Start(v), []
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            if node:
                r.append(node)
            idx = sol.Value(routing.NextVar(idx))
        routes.append(r)
    best = int(sol.ObjectiveValue())
    first_best = next((t for t, c in found if c <= best), seconds)
    return {"routes": [r for r in routes if r], "status": int(routing.status()), "seconds": round(seconds, 3),
            "time_to_best_s": round(first_best, 3), "solutions_seen": len(found), "objective_m": best,
            "first_solution_m": found[0][1] if found else None}


def nearest_neighbour(inst: dict, respect_windows: bool = True) -> list[list[int]]:
    """Each van: go to the closest stop that fits and can still be reached before its window closes; the last van in the
    fleet also takes stops it will be late for. A new van starts when nothing fits. With respect_windows=False it is the
    plain capacity-only version (closest stop that fits, whatever its window)."""
    D, T, W = inst["dist_km"], inst["drive_min"], inst["window"]
    left = set(range(1, len(inst["demand"])))
    routes = []
    while left:
        last_van = len(routes) >= inst["vehicles"] - 1
        route, load, t, cur = [], 0, 0.0, 0
        while True:
            fits = [s for s in left if load + inst["demand"][s] <= inst["capacity"]]
            on_time = [s for s in fits if not respect_windows or t + T[cur, s] <= W[s][1] + LATE_TOLERANCE_MIN]
            pool = on_time or (fits if (last_van or not route) else [])
            if not pool:
                break
            s = min(pool, key=lambda k: (D[cur, k], k))
            t = max(t + T[cur, s], W[s][0]) + inst["service_min"][s]
            load += inst["demand"][s]
            route.append(s)
            left.discard(s)
            cur = s
        routes.append(route)
    return routes


def fixed_order(inst: dict) -> list[list[int]]:
    """Stops in compass-angle order around the depot (a stand-in for a habitual street/postcode order, NOT a real driver
    sequence), cut into van loads; windows are ignored."""
    order = sorted(range(1, len(inst["demand"])), key=lambda s: (inst["angle"][s], s))
    routes, cur, load = [], [], 0
    for s in order:
        if load + inst["demand"][s] > inst["capacity"]:
            routes.append(cur)
            cur, load = [], 0
        cur.append(s)
        load += inst["demand"][s]
    return [*routes, cur] if cur else routes


def run_instance(n: int, seed: int, time_limit_s: float = TIME_LIMIT_S) -> dict:
    inst = instance(np.random.default_rng(seed), n)
    out = {"stops": n, "seed": seed, "parcels": sum(inst["demand"]), "fleet": inst["vehicles"],
           "windowed_stops": sum(1 for w in inst["window"][1:] if w != (0, SHIFT_MIN)), "methods": {}}
    sol = solve(inst, time_limit_s)
    if sol["routes"] is None:
        out["methods"]["or_tools"] = {"error": "no solution", **sol}
    else:
        out["methods"]["or_tools"] = {**evaluate(inst, sol["routes"]), "seconds": sol["seconds"],
                                      "time_to_best_s": sol["time_to_best_s"], "solutions_seen": sol["solutions_seen"]}
    for name, fn in (("nearest_neighbour", nearest_neighbour), ("nearest_neighbour_ignoring_windows", None),
                     ("fixed_order", fixed_order)):
        t0 = time.perf_counter()
        routes = fn(inst) if fn else nearest_neighbour(inst, respect_windows=False)
        out["methods"][name] = {**evaluate(inst, routes), "seconds": round(time.perf_counter() - t0, 4)}
    for m in out["methods"].values():
        if "distance_km" in m:
            assert m["all_stops_once"] and m["capacity_ok"], m
            m["objective_km"] = round(objective(m), 3)
    return out


def summarise(rows: list[dict]) -> dict:
    methods = ("or_tools", "nearest_neighbour", "nearest_neighbour_ignoring_windows", "fixed_order")
    fields = ("distance_km", "late_stops", "late_minutes", "vans", "overtime_routes", "overtime_minutes", "seconds", "fuel_l",
              "co2_kg", "objective_km")
    by_size = {}
    for n in SIZES:
        rs = [r for r in rows if r["stops"] == n and "distance_km" in r["methods"]["or_tools"]]
        if not rs:
            continue
        s = {m: {f: round(float(np.mean([r["methods"][m][f] for r in rs])), 3) for f in fields} for m in methods}
        for other in methods[1:]:
            saving = [1 - r["methods"]["or_tools"]["distance_km"] / r["methods"][other]["distance_km"] for r in rs]
            s[f"distance_saving_vs_{other}"] = {"mean": round(float(np.mean(saving)), 4), "min": round(float(np.min(saving)), 4),
                                                "max": round(float(np.max(saving)), 4)}
        s["or_tools_time_to_best_s_mean"] = round(float(np.mean([r["methods"]["or_tools"]["time_to_best_s"] for r in rs])), 3)
        s["instances"] = len(rs)
        by_size[str(n)] = s
    ok = [r for r in rows if "distance_km" in r["methods"]["or_tools"]]
    return {"by_size": by_size, "instances": len(rows), "or_tools_solved": len(ok),
            "or_tools_distance_not_longer_than_nn": sum(r["methods"]["or_tools"]["distance_km"] <= r["methods"]["nearest_neighbour"]["distance_km"] + 1e-9 for r in ok),
            "or_tools_objective_not_worse_than_nn": sum(r["methods"]["or_tools"]["objective_km"] <= r["methods"]["nearest_neighbour"]["objective_km"] + 1e-9 for r in ok),
            "or_tools_distance_not_longer_than_fixed_order": sum(r["methods"]["or_tools"]["distance_km"] <= r["methods"]["fixed_order"]["distance_km"] + 1e-9 for r in ok),
            "or_tools_late_stops_total": sum(r["methods"]["or_tools"]["late_stops"] for r in ok),
            **{f"{m}_late_stops_total": sum(r["methods"][m]["late_stops"] for r in ok) for m in methods[1:]},
            "windowed_stops_total": sum(r["windowed_stops"] for r in ok), "stops_total": sum(r["stops"] for r in ok)}


def main() -> None:
    t0 = time.time()
    rows = []
    for n in SIZES:
        for seed in SEEDS:
            r = run_instance(n, seed)
            rows.append(r)
            print(n, seed, {m: (v.get("distance_km"), v.get("late_stops"), v.get("vans")) for m, v in r["methods"].items()}, flush=True)
    summary = summarise(rows)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = REPO_ROOT / "artifacts" / "experiments" / f"RT1-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    config = {"sizes": list(SIZES), "seeds": list(SEEDS), "time_limit_s": TIME_LIMIT_S, "reference_latlon": REF_LATLON,
              "shift_min_after_0800": SHIFT_MIN, "horizon_min_after_0800": HORIZON_MIN, "speed_kmh": SPEED_KMH,
              "service_min": SERVICE_MIN, "service_per_parcel_min": SERVICE_PER_PARCEL_MIN, "capacity_parcels": CAPACITY,
              "spare_vans": SPARE_VANS, "window_share": WINDOW_SHARE, "windows_min_after_0800": WINDOWS,
              "clusters": CLUSTERS, "cluster_share": CLUSTER_SHARE, "cluster_sd_km": CLUSTER_SD_KM, "scatter_km": SCATTER_KM,
              "solver": {"first_solution": "PATH_CHEAPEST_ARC", "metaheuristic": "GUIDED_LOCAL_SEARCH",
                         "van_fixed_cost_km": VAN_FIXED_KM, "late_cost_m_per_s": LATE_M_PER_S,
                         "capacity": "hard", "windows_and_shift_end": "soft upper bounds", "window_open": "hard (wait)"},
              "payload_t": PAYLOAD_T, "road_kg_co2e_per_tkm": ROAD_KG_PER_TKM, "fuel_l_per_100km": FUEL_L_PER_100KM}
    metrics = {
        "experiment_id": out.name, "study": "RT1", "kind": "simulated routing instances (synthetic stops; no real routes)",
        "question": "How much distance and lateness does a VRP solver with capacity and delivery windows save over a "
                    "nearest-neighbour plan and a fixed habitual-style order? (SIMULATED instances)",
        "data": {"label": "SIMULATED", "generator": "evaluations/routing_study.py instance(); parameters in config.json",
                 "sizes": list(SIZES), "seeds": list(SEEDS),
                 "distance": "haversine (straight-line) km between synthetic coordinates; real road distances are longer",
                 "fixed_order_note": "compass-angle order around the depot stands in for a habitual sequence; it is not a real driver's sequence"},
        "results": {"summary": summary, "instances": rows},
        "assumptions": [
            f"driving time = haversine km / {SPEED_KMH:g} km/h (assumed straight-line-equivalent speed); doorstep "
            f"{SERVICE_MIN:g} min + {SERVICE_PER_PARCEL_MIN:g} min per parcel",
            f"vans carry {CAPACITY} parcels; fleet = vans the parcels need + {SPARE_VANS}; shift 08:00-18:00",
            f"CO2 = km x assumed average payload {PAYLOAD_T} t x {ROAD_KG_PER_TKM} kg CO2e per tonne-km (rounded UK DESNZ "
            "road freight factor, as E1). That factor is an HGV average; DESNZ per-vehicle-km van factors were not used, and "
            "the absolute CO2 here is likely well below a real van's. Read CO2 as relative between methods",
            f"fuel = km x {FUEL_L_PER_100KM:g} L/100 km (assumed diesel van figure, not measured)",
            f"solver objective: metres + {VAN_FIXED_KM} km per van used + {LATE_M_PER_S} m per second late (windows and "
            "shift end); the evaluator, not the solver, produces every reported number",
        ],
        "limits": [
            "synthetic instances: results show what the method does on the stated generator, not on real courier days",
            "distances are haversine (straight-line); no road network, one-way streets or traffic",
            "no real driver sequences: the fixed order is a stand-in for a habitual route",
            "the real datasets (LaDe, Amazon Last Mile) need the owner's approval before they can replace the generator",
            "the solver stops at a wall-clock limit, so a rerun on a busier machine can return slightly different routes",
        ],
        "seeds": {"instances": list(SEEDS), "solver": "OR-Tools routing is single-threaded; stops at the time limit"},
        "seconds": round(time.time() - t0, 1),
    }
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1, default=str))
    (out / "config.json").write_text(json.dumps(config, indent=1, default=str))
    print(json.dumps({"experiment_id": out.name, "seconds": metrics["seconds"], "summary": summary}, indent=1))


if __name__ == "__main__":
    main()
