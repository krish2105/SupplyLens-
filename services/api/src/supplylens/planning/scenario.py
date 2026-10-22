"""Scenario planning: the same snapshot, terms and optimiser with explicit, bounded what-if inputs.

Inputs that change results (demand multiplier, supplier delay, budget, replenishment basis and its own controls) are
recorded with the result; every scenario is persisted as an immutable plan run. A control that does not apply to the
selected basis is rejected rather than silently ignored (audit F03): `safety_days` belongs to `q50_plus_safety`,
`service_level` to `leadtime_demand`. `controls` in the result lists which inputs applied.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text

from supplylens_opt.planner import Need, PlanRequest, plan
from supplylens_opt.replenishment import Position, assess

from ..authz import Actor
from ..db import tenant_session
from ..forecasting.service import run_forecast
from .demand_history import dependence_by_sku
from .grain import demand_shares, expand_offers
from .positions import bounded_scope, load_positions
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
    coverage_days: int | None = Field(default=None, ge=7, le=28)
    service_level: float | None = Field(default=None, ge=0.5, lt=1.0)
    allow_shortfall: bool = True
    shortage_penalty_minor: int = Field(default=500, ge=0, le=1_000_000)
    currency: str | None = None
    replenishment_basis: Literal["leadtime_demand", "q90_sum", "q50_plus_safety"] | None = None

    @model_validator(mode="after")
    def _controls_match_basis(self):
        basis = self.replenishment_basis or "leadtime_demand"
        if self.safety_days is not None and basis != "q50_plus_safety":
            raise ValueError(f"safety_days applies only to the q50_plus_safety basis, not {basis}")
        if self.service_level is not None and basis != "leadtime_demand":
            raise ValueError(f"service_level applies only to the leadtime_demand basis, not {basis}")
        return self


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
        skus, scope = bounded_scope(skus, explicit=bool(inp.sku_ids))
        # Operational data (stock snapshots, open orders, sales shares) is read as known at the cutoff: a replay whose
        # effective date is later than its cutoff must not see snapshots or orders recorded after it (P2-PLAN-03).
        known = min(cutoff.date(), eff)
        positions, excluded = load_positions(s, skus, known)
        shares = demand_shares(s, st.dataset_id, positions, known)
    real_skus = sorted({p["sku_id"] for p in positions.values()})
    planning = st.planning or {}
    currency = inp.currency or st.currency.strip()
    budget = inp.budget_minor if inp.budget_minor is not None else int(planning.get("weekly_budget_minor", 0))
    basis = inp.replenishment_basis or "leadtime_demand"
    safety = inp.safety_days if inp.safety_days is not None else planning.get("safety_days", 5)
    coverage = inp.coverage_days or planning.get("coverage_days", 21)
    if not st.dataset_id:
        raise ValueError("scenario studio needs a sales history to forecast; this workspace has none")
    # The forecast origin is the earlier of the knowledge cutoff and the decision date: nothing after the cutoff is known,
    # and demand on or before the decision date is not part of the coverage window (audit F02).
    origin = min(cutoff.date(), eff)
    fr = run_forecast(actor.tenant_id, st.dataset_id, real_skus, origin, horizon=28,
                      created_by=actor.user_id, allow_baseline_fallback=True)
    res = applicable_terms(actor.tenant_id, real_skus, cutoff, eff)
    # Two applicable terms for one supplier and SKU without a supersession link are a conflict: review required, never
    # pick one (terms.py). The scenario plans without the conflicting terms and reports them (P2-PLAN-05).
    conflicted = sorted({tid for group in res.conflicts for tid in group})
    offers = [t.model_copy(update={"lead_time_days": t.lead_time_days + inp.supplier_delay_days})
              for t in res.applicable if t.currency == currency and t.term_id not in conflicted]
    leads_by_sku: dict[str, set[int]] = {}
    for o in offers:                       # each supplier's lead time sets its own protection interval (P1-PLAN-02)
        leads_by_sku.setdefault(o.sku_id, set()).add(o.lead_time_days)
    service_level = inp.service_level or planning.get("service_level", 0.9)
    dependence = dependence_by_sku(actor.tenant_id, st.dataset_id, real_skus, known)
    needs, required_by_lead = {}, {}
    for key, r in positions.items():
        sku = r["sku_id"]
        pts = fr.points[fr.points["sku_id"] == sku]
        if pts.empty:
            excluded[key] = "no forecast for this SKU"
            continue
        share, _ = shares[key]
        m = inp.demand_multiplier * share       # a location plans for its own share of the SKU's demand (grain.py)
        path = [{"day": p.day.date(), "q10": p.q10 * m, "q50": p.q50 * m, "q90": p.q90 * m} for p in pts.itertuples()]
        acf, dep_basis = dependence.get(sku, (None, "assumed default"))
        position = Position(sku_id=key, **{k: r[k] for k in ("on_hand", "allocated", "on_order", "capacity")})
        leads = sorted(leads_by_sku.get(sku, {0}))
        try:
            by_lead = {lead: assess(position, path, eff, coverage, safety, basis, lead_time_days=lead,
                                    service_level=service_level, acf=acf, dependence_basis=dep_basis) for lead in leads}
        except ValueError as e:
            excluded[key] = str(e)
            continue
        needs[key] = by_lead[leads[0]]       # shown at the fastest lead time; each offer must cover its own
        required_by_lead[key] = {lead: a.required_units for lead, a in by_lead.items()}
    to_buy = {k: v for k, v in needs.items() if v.required_units > 0}
    req = PlanRequest(decision_date=eff, need_by=eff + timedelta(days=coverage), currency=currency,
                      budget_minor=budget, needs=[Need(sku_id=k, required_units=v.required_units,
                                                       capacity_units=v.capacity_headroom_units,
                                                       required_units_by_lead_time=required_by_lead[k])
                                                  for k, v in to_buy.items()],
                      offers=expand_offers(offers, list(to_buy)), allow_shortfall=inp.allow_shortfall,
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
        "inputs": {**inp.model_dump(mode="json"), "budget_minor": budget, "replenishment_basis": basis,
                   "safety_days": safety if basis == "q50_plus_safety" else None,
                   "coverage_days": coverage, "service_level": service_level if basis == "leadtime_demand" else None,
                   "currency": currency, "knowledge_cutoff": cutoff.isoformat(), "effective_date": eff.isoformat(),
                   "forecast_origin": origin.isoformat()},
        "controls": {"replenishment_basis": basis,
                     "safety_days": "applied" if basis == "q50_plus_safety" else f"not applicable under {basis}",
                     "service_level": "applied" if basis == "leadtime_demand" else f"not applicable under {basis}",
                     "budget_minor": "explicit" if inp.budget_minor is not None else "workspace default"},
        "scope": {**scope, "not_assessed": excluded},
        "value_kinds": {"forecast": "forecast", "stock": "simulated", "terms": "simulated", "budget": "assumed",
                        "demand_multiplier": "assumed", "supplier_delay_days": "assumed"},
        "forecast_run_id": str(fr.run_id),
        "needs": {k: {**v.model_dump(mode="json"), "location_id": positions[k]["location_id"],
                      "required_units_by_lead_time": {str(d): u for d, u in required_by_lead[k].items()},
                      "demand_share": round(shares[k][0], 4), "demand_share_basis": shares[k][1]} for k, v in needs.items()},
        "plan": result.model_dump(mode="json") if result else {"status": "NO_ACTION", "lines": []},
        "terms": {"applicable": len(res.applicable), "ignored": [i.model_dump() for i in res.ignored],
                  "conflicts": res.conflicts, "excluded_for_conflict": conflicted},
        "metrics": {
            "skus_assessed": len(needs), "skus_not_assessed": len(excluded), "skus_needing_order": len(to_buy),
            "uncapped_units": sum(v.uncapped_required_units for v in needs.values()),
            "capacity_capped_units": sum(v.uncapped_required_units - v.required_units for v in needs.values()),
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
