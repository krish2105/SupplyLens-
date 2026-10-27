"""FA1: does budget-constrained replenishment serve customers in every country equally? (F3)

When the weekly budget binds, the coverage-first planner leaves some required units uncovered. It counts every unit the
same, so products bought mostly by the large UK customer base can crowd out products that customers elsewhere depend
on. This study measures that allocation harm and applies reweighing as the mitigation:

1. Baseline: the scenario studio's default plan on the real UCI scope (budget binding).
2. Each product's demand is split across customer country groups by its sales in the 365 days before the as-of date;
   a product's uncovered units fall on its customers in the same proportion (a stock-out hits everyone who buys it).
   Group coverage = covered / required units attributed to the group.
3. Reweighing (Kamiran & Calders style, applied to the optimiser's objective): each product's uncovered units are
   weighted by sum over groups of (its demand share in the group x 1 / the group's share of all demand), so a unit short
   for an under-represented group counts more. Same budget, same offers, same forecast.
4. Reported: coverage per group and per large country, the gap between the best- and worst-served group, the ratio of
   worst to best (the "four-fifths" screen), and what fairness costs in total coverage.
5. Strength sweep: weights (1 / group share) ** alpha for alpha in 0 ... 1. alpha = 0 is the baseline, alpha = 1 full
   reweighing; the sweep traces the fairness / efficiency trade-off and the smallest alpha that passes the 0.8 screen.

Simulated: stock, terms and budget are the workspace's assumed recipe; demand is the champion forecast; country shares
are recorded sales. A deterministic allocation, so no sampling interval applies; it is one scope on one date.

uv run python evaluations/fairness_study.py
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from supplylens.authz import resolve_actor
from supplylens.config import REPO_ROOT
from supplylens.db import tenant_session
from supplylens.planning.grain import split_key
from supplylens.planning.scenario import ScenarioInput, _prepare
from supplylens.seed import dev_email, tenant_id, user_id
from supplylens_opt.planner import plan

EUROPE = {"Austria", "Belgium", "Channel Islands", "Cyprus", "Czech Republic", "Denmark", "EIRE", "Finland", "France", "Germany",
          "Greece", "Iceland", "Italy", "Lithuania", "Malta", "Netherlands", "Norway", "Poland", "Portugal", "Spain", "Sweden",
          "Switzerland", "European Community"}
UNSPECIFIED = {"Unspecified", "", None}
WEIGHT_SCALE = 100                 # integer weights for CP-SAT: 1.00 -> 100
ALPHAS = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.75, 1.0)
FOUR_FIFTHS = 0.8
MIN_COUNTRY_UNITS = 50             # report a country on its own only when enough required units are attributed to it


def group_of(country: str | None) -> str:
    if country in UNSPECIFIED:
        return "Unspecified"
    if country == "United Kingdom":
        return "United Kingdom"
    return "Europe (non-UK)" if country in EUROPE else "Rest of world"


def coverage(req, result, share):
    """Required and covered units per group and per country, attributing each product's gap by its demand shares."""
    short = result.shortfall
    by_group, by_country = defaultdict(lambda: [0.0, 0.0]), defaultdict(lambda: [0.0, 0.0])
    for n in req.needs:
        sku = split_key(n.sku_id)[0]
        need, gap = n.required_units, min(short.get(n.sku_id, 0), n.required_units)
        for country, s in share.get(sku, {}).items():
            for table, key in ((by_group, group_of(country)), (by_country, country or "Unspecified")):
                table[key][0] += need * s
                table[key][1] += (need - gap) * s
    rate = lambda t: {k: {"required": round(r, 1), "covered": round(c, 1), "coverage": round(c / r, 4) if r else None}  # noqa: E731
                      for k, (r, c) in sorted(t.items(), key=lambda kv: -kv[1][0])}
    return rate(by_group), rate(by_country)


def summary(groups):
    rates = [g["coverage"] for g in groups.values() if g["coverage"] is not None and g["required"] >= MIN_COUNTRY_UNITS]
    return {"best": max(rates), "worst": min(rates), "gap_points": round((max(rates) - min(rates)) * 100, 2),
            "worst_to_best_ratio": round(min(rates) / max(rates), 4)}


def main() -> None:
    tid = tenant_id("uci-research")
    actor = resolve_actor(user_id(dev_email("planner")), tid)
    c = _prepare(actor, ScenarioInput())
    base = c.req.model_copy(update={"allow_shortfall": True})
    skus = sorted({split_key(n.sku_id)[0] for n in base.needs})
    with tenant_session(tid) as s:
        rows = s.execute(text("""SELECT sku_id, country, sum(quantity)::float AS u FROM sales_lines
            WHERE sku_id = ANY(:k) AND quantity > 0 AND invoiced_at::date > CAST(:e AS date) - 365 AND invoiced_at::date <= :e
            GROUP BY 1, 2"""), {"k": skus, "e": c.eff}).all()
    units = defaultdict(dict)
    for sku, country, u in rows:
        units[sku][country] = u
    share = {sku: {k: v / sum(d.values()) for k, v in d.items()} for sku, d in units.items()}
    total = defaultdict(float)
    for d in units.values():
        for country, u in d.items():
            total[group_of(country)] += u
    all_units = sum(total.values())
    group_share = {g: v / all_units for g, v in total.items()}

    def weights_for(alpha: float) -> dict[str, int]:
        out = {}
        for n in base.needs:
            sh = share.get(split_key(n.sku_id)[0], {})
            w = sum(s * (1 / group_share[group_of(country)]) ** alpha for country, s in sh.items()) if sh else 1.0
            out[n.sku_id] = max(1, round(w * WEIGHT_SCALE))
        return out

    required = sum(n.required_units for n in base.needs)

    def run(alpha: float) -> dict:
        w = weights_for(alpha)
        req = base if alpha == 0 else base.model_copy(update={"needs": [n.model_copy(update={"shortage_weight": w[n.sku_id]})
                                                                         for n in base.needs]})
        r = plan(req, deterministic_first=False, explain=False)
        if r.status not in ("OPTIMAL", "FEASIBLE"):
            raise SystemExit(f"alpha {alpha}: {r.status}")
        groups, countries = coverage(base, r, share)
        return {"alpha": alpha, "status": r.status, "spend_minor": r.total_minor, "shortfall_units": sum(r.shortfall.values()),
                "overall_coverage": round(1 - sum(r.shortfall.values()) / required, 4),
                "weights": {"min": min(w.values()) / WEIGHT_SCALE, "max": max(w.values()) / WEIGHT_SCALE},
                "groups": groups, "summary": summary(groups),
                "countries": {k: v for k, v in countries.items() if v["required"] >= MIN_COUNTRY_UNITS}}

    sweep = [run(a) for a in ALPHAS]
    passing = [x for x in sweep if x["summary"]["worst_to_best_ratio"] >= FOUR_FIFTHS]
    chosen = max(passing, key=lambda x: (x["overall_coverage"], -x["alpha"])) if passing else None
    out_runs = {"baseline": sweep[0], "reweighed": sweep[-1]}
    weights = weights_for(1.0)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = REPO_ROOT / "artifacts" / "experiments" / f"FA1-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    b, f = out_runs["baseline"], out_runs["reweighed"]
    metrics = {
        "experiment_id": out.name, "study": "FA1", "kind": "simulated",
        "question": "When the budget binds, are customers in every country group served equally, and what does reweighing change?",
        "scope": {"skus": len(base.needs), "required_units": sum(n.required_units for n in base.needs), "budget_minor": base.budget_minor,
                  "currency": base.currency, "effective_date": c.eff.isoformat(),
                  "share_window": f"{(c.eff - timedelta(days=365)).isoformat()} to {c.eff.isoformat()}"},
        "group_demand_share": {g: round(v, 4) for g, v in sorted(group_share.items(), key=lambda kv: -kv[1])},
        "weights": {"method": "sum over the product's country shares of (1 / that group's share of all demand) ** alpha",
                    "alpha_1_min": min(weights.values()) / WEIGHT_SCALE, "alpha_1_max": max(weights.values()) / WEIGHT_SCALE},
        "baseline": b, "reweighed": f,
        "sweep": [{k: x[k] for k in ("alpha", "overall_coverage", "spend_minor", "summary")} |
                  {"groups": {g: v["coverage"] for g, v in x["groups"].items()}} for x in sweep],
        "recommended": None if chosen is None else {
            "alpha": chosen["alpha"], "overall_coverage": chosen["overall_coverage"], "summary": chosen["summary"],
            "groups": {g: v["coverage"] for g, v in chosen["groups"].items()},
            "coverage_cost_points": round((sweep[0]["overall_coverage"] - chosen["overall_coverage"]) * 100, 2),
            "rule": f"highest overall coverage among weightings whose worst-to-best ratio is at least {FOUR_FIFTHS}"},
        "effect": {"gap_points_before": b["summary"]["gap_points"], "gap_points_after": f["summary"]["gap_points"],
                   "ratio_before": b["summary"]["worst_to_best_ratio"], "ratio_after": f["summary"]["worst_to_best_ratio"],
                   "overall_coverage_change_points": round((f["overall_coverage"] - b["overall_coverage"]) * 100, 2),
                   "spend_change_minor": f["spend_minor"] - b["spend_minor"]},
        "limits": ["one scope, one date; deterministic allocation, no sampling interval",
                   "a stock-out is assumed to hit a product's customers in proportion to their past purchases",
                   f"groups and countries with fewer than {MIN_COUNTRY_UNITS} attributed required units are not ranked",
                   "stock, terms and budget are the workspace's assumed recipe; demand is the champion forecast"],
    }
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1, default=str))
    (out / "config.json").write_text(json.dumps({"weight_scale": WEIGHT_SCALE, "min_country_units": MIN_COUNTRY_UNITS, "alphas": ALPHAS,
                                                 "europe": sorted(EUROPE)}, indent=1))
    print(json.dumps({"experiment_id": out.name, "group_share": metrics["group_demand_share"], "effect": metrics["effect"],
                      "before": {k: v["coverage"] for k, v in b["groups"].items()},
                      "after": {k: v["coverage"] for k, v in f["groups"].items()},
                      "sweep": [(x["alpha"], x["overall_coverage"], x["summary"]["worst_to_best_ratio"], x["summary"]["gap_points"]) for x in sweep],
                      "recommended": metrics["recommended"]}, indent=1))


if __name__ == "__main__":
    main()
