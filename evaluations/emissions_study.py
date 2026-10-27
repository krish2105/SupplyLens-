"""E1: cost, service and CO2 trade-off on the real UCI scope (F2), exact versus evolutionary.

The scenario studio's default plan request (40 SKUs with an order need, two supplier offers each, the workspace budget)
is solved two ways for the two objectives "required units left uncovered" and "kg CO2e", under the budget:
- epsilon-constraint with the product's CP-SAT planner: the uncapped plan, then caps at 21 falling shares of its CO2;
  each solve is lexicographic (coverage, then cost), so every point is optimal for its cap;
- NSGA-II (pymoo): per SKU one gene picks the offer (or none) and one the share of the requirement bought; quantities are
  rounded up to MOQ and pack multiples and clipped to storage headroom; the budget is a constraint.
Reported: both fronts, hypervolume (normalised), how many NSGA-II points the exact front dominates, and run times.

CO2 factors are assumed (supplylens_opt.emissions); stock, terms and budget are the workspace's simulated recipe; demand is
the champion forecast at the workspace as-of. Nothing here is a measured outcome.

uv run --with pymoo==0.6.2 python evaluations/emissions_study.py
"""
from __future__ import annotations

import json
import math
import time
from datetime import UTC, datetime

import numpy as np

from supplylens.authz import resolve_actor
from supplylens.config import REPO_ROOT
from supplylens.planning.scenario import ScenarioInput, _prepare
from supplylens.seed import dev_email, tenant_id, user_id
from supplylens_opt.emissions import ASSUMPTIONS
from supplylens_opt.planner import plan

SHARES = [None] + [round(1 - i * 0.05, 2) for i in range(1, 20)] + [0.02]
SEEDS, POP, GENS = (1, 2, 3), 120, 250


def shortage_and_co2(req, choice: list[int], frac: list[float]):
    """Evaluate one NSGA-II decision with the planner's own coverage rule (validator semantics)."""
    by_sku = {}
    for o in req.offers:
        by_sku.setdefault(o.sku_id, []).append(o)
    short = co2 = spend = 0
    for i, n in enumerate(req.needs):
        offers = by_sku.get(n.sku_id, [])
        k = choice[i]
        if k == 0 or k > len(offers) or frac[i] <= 0:
            short += n.required_units
            continue
        o = offers[k - 1]
        need = n.required_for(o.lead_time_days)
        q = max(o.moq, math.ceil(frac[i] * need))
        q = -(-q // o.order_multiple) * o.order_multiple
        if n.capacity_units is not None and q > n.capacity_units:
            q = (n.capacity_units // o.order_multiple) * o.order_multiple
            if q < o.moq:
                q = 0
        short += max(n.required_units - q, need - q, 0) if q else n.required_units
        co2 += q * (o.co2_grams_per_unit or 0)
        spend += q * o.unit_cost_minor
    return short, co2, spend


def nondominated(points):
    pts = sorted(set(points))
    front, best = [], math.inf
    for s, c in pts:                  # minimise both: sweep by shortage, keep strictly falling CO2
        if c < best:
            front.append((s, c))
            best = c
    return front


def hypervolume(front, ref):
    """2-D hypervolume (both minimised) below reference point `ref`."""
    hv, prev_c = 0.0, ref[1]
    for s, c in sorted(front):
        if s >= ref[0] or c >= prev_c:
            continue
        hv += (ref[0] - s) * (prev_c - c)
        prev_c = c
    return hv


def main() -> None:
    from pymoo.algorithms.moo.nsga2 import NSGA2
    from pymoo.core.problem import ElementwiseProblem
    from pymoo.optimize import minimize

    actor = resolve_actor(user_id(dev_email("planner")), tenant_id("uci-research"))
    c = _prepare(actor, ScenarioInput())
    base = c.req.model_copy(update={"allow_shortfall": True, "co2_cap_grams": None})
    required = sum(n.required_units for n in base.needs)

    t0 = time.time()
    exact, top = [], None
    for share in SHARES:
        cap = None if share is None else int(top * share)
        r = plan(base.model_copy(update={"co2_cap_grams": cap}), deterministic_first=False, explain=False)
        if r.status not in ("OPTIMAL", "FEASIBLE"):
            raise SystemExit(f"cap {share}: {r.status}")
        g = r.objective["co2_grams"]
        top = g if share is None else top
        exact.append({"cap_share": share, "shortfall_units": r.objective["shortage_units"], "co2_grams": g,
                      "spend_minor": r.total_minor, "status": r.status})
    t_exact = time.time() - t0

    n_sku = len(base.needs)
    k_max = max(sum(1 for o in base.offers if o.sku_id == n.sku_id) for n in base.needs)

    class Problem(ElementwiseProblem):
        def __init__(self):
            super().__init__(n_var=2 * n_sku, n_obj=2, n_ieq_constr=1, xl=np.zeros(2 * n_sku),
                             xu=np.concatenate([np.full(n_sku, k_max + 0.999), np.ones(n_sku)]))

        def _evaluate(self, x, out, *args, **kwargs):
            s, co2, spend = shortage_and_co2(base, [int(v) for v in x[:n_sku]], list(x[n_sku:]))
            out["F"] = [s, co2]
            out["G"] = [spend - base.budget_minor]

    nsga, t_nsga = [], 0.0
    for seed in SEEDS:
        t1 = time.time()
        res = minimize(Problem(), NSGA2(pop_size=POP), ("n_gen", GENS), seed=seed, verbose=False)
        t_nsga += time.time() - t1
        F = res.F if res.F is not None else np.empty((0, 2))
        nsga.append([(int(a), int(b)) for a, b in np.atleast_2d(F)])
    exact_front = nondominated([(p["shortfall_units"], p["co2_grams"]) for p in exact])
    ref = (required * 1.01, max(p["co2_grams"] for p in exact) * 1.5 + 1)
    hv_exact = hypervolume(exact_front, ref)
    per_seed = []
    for seed, pts in zip(SEEDS, nsga, strict=True):
        front = nondominated(pts)
        dominated = sum(1 for s, g in front if any(es <= s and ec <= g and (es, ec) != (s, g) for es, ec in exact_front))
        per_seed.append({"seed": seed, "front_points": len(front), "hypervolume_ratio": round(hypervolume(front, ref) / hv_exact, 4),
                         "dominated_by_exact": dominated, "front": front})
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = REPO_ROOT / "artifacts" / "experiments" / f"E1-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    metrics = {
        "experiment_id": out.name, "study": "E1", "kind": "simulated",
        "question": "What does cutting the plan's CO2 cost in service and spend, and does an evolutionary search find the same trade-off as the exact solver?",
        "scope": {"skus": n_sku, "offers": len(base.offers), "budget_minor": base.budget_minor, "required_units": required,
                  "currency": base.currency, "effective_date": c.eff.isoformat()},
        "exact": {"method": "epsilon-constraint, CP-SAT (lexicographic: coverage, then cost)", "seconds": round(t_exact, 1),
                  "points": exact},
        "nsga2": {"method": f"pymoo NSGA-II, population {POP}, {GENS} generations, seeds {list(SEEDS)}",
                  "seconds_total": round(t_nsga, 1), "per_seed": per_seed},
        "hypervolume_reference": {"shortfall_units": ref[0], "co2_grams": ref[1]},
        "assumptions": ASSUMPTIONS + ["service = share of required units covered (simulated)", "budget binds (workspace weekly budget)"],
    }
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1, default=str))
    (out / "config.json").write_text(json.dumps({"shares": SHARES, "seeds": SEEDS, "pop": POP, "gens": GENS}, indent=1))
    print(json.dumps({"experiment_id": out.name, "exact_seconds": metrics["exact"]["seconds"], "nsga_seconds": metrics["nsga2"]["seconds_total"],
                      "hv_ratio": [p["hypervolume_ratio"] for p in per_seed], "dominated": [p["dominated_by_exact"] for p in per_seed],
                      "front_points": [p["front_points"] for p in per_seed]}, indent=1))


if __name__ == "__main__":
    main()
