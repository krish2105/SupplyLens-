"""Scenario planning: the same snapshot, terms and optimiser with explicit, bounded what-if inputs.

Inputs that change results (demand multiplier, supplier delay, budget, safety days) are
recorded with the result; every scenario is persisted as an immutable plan run.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import text

from supplylens_opt.planner import Need, PlanRequest, plan
from supplylens_opt.replenishment import Position, assess

from ..authz import Actor
from ..db import tenant_session
from ..forecasting.service import run_forecast
from .terms_service import applicable_terms


class ScenarioInput(BaseModel):
    name: str = "Scenario"
    sku_ids: list[str] | None = None
    knowledge_cutoff: datetime | None = None
    effective_date: date | None = None
    budget_minor: int | None = Field(default=None, ge=0, le=10_000_000_000)
    demand_multiplier: float = Field(default=1.0, ge=0.25, le=3.0)
    supplier_delay_days: int = Field(default=0, ge=0, le=60)
    safety_days: int | None = Field(default=None, ge=0, le=60)
    coverage_days: int | None = Field(default=None, ge=7, le=60)
    allow_shortfall: bool = True
    shortage_penalty_minor: int = Field(default=500, ge=0, le=1_000_000)
    currency: str | None = None


def run_scenario(actor: Actor, inp: ScenarioInput) -> dict:
    actor.require("plan.run")
    with tenant_session(actor.tenant_id) as s:
        st = s.execute(text("SELECT operational_as_of, currency, dataset_id, planning FROM tenant_settings")).first()
        if st is None:
            raise ValueError("workspace has no operational settings")
        cutoff = inp.knowledge_cutoff or st.operational_as_of
        eff = inp.effective_date or cutoff.date()
        skus = inp.sku_ids or [r.sku_id for r in s.execute(text(
            "SELECT DISTINCT sku_id FROM inventory_positions ORDER BY sku_id"))]
        rows = s.execute(text("""SELECT DISTINCT ON (sku_id) sku_id, on_hand, allocated, on_order, capacity
            FROM inventory_positions WHERE sku_id = ANY(:k) AND as_of <= :e ORDER BY sku_id, as_of DESC"""),
            {"k": skus, "e": eff}).mappings().all()
    planning = st.planning or {}
    currency = inp.currency or st.currency.strip()
    budget = inp.budget_minor if inp.budget_minor is not None else int(planning.get("weekly_budget_minor", 0))
    safety = inp.safety_days if inp.safety_days is not None else planning.get("safety_days", 5)
    coverage = inp.coverage_days or planning.get("coverage_days", 21)
    if not st.dataset_id:
        raise ValueError("scenario studio needs a sales history to forecast; this workspace has none")
    fr = run_forecast(actor.tenant_id, st.dataset_id, skus, cutoff.date(), horizon=max(28, coverage),
                      created_by=actor.user_id)
    needs = {}
    for r in rows:
        pts = fr.points[fr.points["sku_id"] == r["sku_id"]]
        if pts.empty:
            continue
        path = [{"day": p.day.date(), "q50": p.q50 * inp.demand_multiplier, "q90": p.q90 * inp.demand_multiplier}
                for p in pts.itertuples()]
        needs[r["sku_id"]] = assess(Position(sku_id=r["sku_id"], **{k: r[k] for k in
                                    ("on_hand", "allocated", "on_order", "capacity")}), path, eff, coverage, safety)
    res = applicable_terms(actor.tenant_id, skus, cutoff, eff)
    offers = [t.model_copy(update={"lead_time_days": t.lead_time_days + inp.supplier_delay_days})
              for t in res.applicable if t.currency == currency]
    to_buy = {k: v for k, v in needs.items() if v.required_units > 0}
    req = PlanRequest(decision_date=eff, need_by=eff + timedelta(days=coverage), currency=currency,
                      budget_minor=budget, needs=[Need(sku_id=k, required_units=v.required_units)
                                                  for k, v in to_buy.items()],
                      offers=[o for o in offers if o.sku_id in to_buy], allow_shortfall=inp.allow_shortfall,
                      shortage_penalty_minor=inp.shortage_penalty_minor)
    result = plan(req) if to_buy else None
    lines = result.lines if result else []
    ordered = {}
    for l in lines:
        ordered[l.sku_id] = ordered.get(l.sku_id, 0) + l.quantity
    # Simple projected coverage: share of q50 window demand covered by available + on-order + ordered units
    # (arrival timing inside the window is ignored; this is a simulated indicator, not a fill rate).
    covered = sum(min(v.demand_q50, max(v.available, 0) + (v.inventory_position - v.available) + ordered.get(k, 0))
                  for k, v in needs.items())
    demand = sum(v.demand_q50 for v in needs.values())
    out = {
        "scenario_id": str(uuid.uuid4()), "name": inp.name,
        "inputs": {**inp.model_dump(mode="json"), "budget_minor": budget, "safety_days": safety,
                   "coverage_days": coverage, "currency": currency,
                   "knowledge_cutoff": cutoff.isoformat(), "effective_date": eff.isoformat()},
        "value_kinds": {"forecast": "forecast", "stock": "simulated", "terms": "simulated", "budget": "assumed",
                        "demand_multiplier": "assumed", "supplier_delay_days": "assumed"},
        "forecast_run_id": str(fr.run_id),
        "needs": {k: v.model_dump(mode="json") for k, v in needs.items()},
        "plan": result.model_dump(mode="json") if result else {"status": "NO_ACTION", "lines": []},
        "terms": {"applicable": len(res.applicable), "ignored": [i.model_dump() for i in res.ignored],
                  "conflicts": res.conflicts},
        "metrics": {
            "skus_assessed": len(needs), "skus_needing_order": len(to_buy),
            "units_ordered": sum(ordered.values()), "spend_minor": result.total_minor if result else 0,
            "shortfall_units": sum(result.shortfall.values()) if result else 0,
            "projected_q50_coverage": round(covered / demand, 4) if demand else None,
            "metric_note": "Simulated: q50 demand path vs stock + ordered units in the window; not a measured fill rate.",
        },
    }
    with tenant_session(actor.tenant_id) as s:
        s.execute(text("""INSERT INTO plan_runs (id, tenant_id, as_of, request, input_hash, status, result, created_by)
            VALUES (:i,:t,:a,CAST(:r AS jsonb),:h,:s,CAST(:res AS jsonb),:u)"""),
            {"i": out["scenario_id"], "t": actor.tenant_id, "a": cutoff, "r": json.dumps(out["inputs"]),
             "h": result.input_hash if result else "no-action", "s": out["plan"]["status"],
             "res": json.dumps(out, default=str), "u": actor.user_id})
    return out
