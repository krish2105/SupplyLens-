"""Deterministic replenishment planning with OR-Tools CP-SAT.

The planner receives offers that are already *applicable* at the decision time (the
terms service resolves effective dates and amendments). It chooses at most one supplier
per SKU, respects MOQ, order multiples, lead time, budget and capacity. Money is integer minor units.

Objective, lexicographic: (1) cover as many required units as the hard constraints allow, (2) lowest purchase cost,
(3) fewer units, (4) stable supplier order. A shortfall (allow_shortfall) is therefore only ever the result of a binding
budget, capacity, MOQ or lead-time constraint, never of a cost trade-off against an assumed penalty: the penalty used
to make "order nothing" optimal whenever a unit cost at least as much as the penalty (audit P0-PLAN-01). The assumed
shortage penalty is still reported as the cost of the remaining gap.

The planner never invents a plan: an infeasible problem returns INFEASIBLE with the
constraint families whose relaxation would make it feasible.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from typing import Literal

import ortools
from ortools.sat.python import cp_model
from pydantic import BaseModel, Field

SOLVER_SETTINGS = {"num_workers": 1, "random_seed": 0, "max_time_s": 10.0}
INT_LIMIT = 2 ** 62          # CP-SAT works in 64-bit integers; stay well inside so sums cannot overflow


class ScaleError(ValueError):
    """Prices and quantities are too large to model exactly in 64-bit integers."""


class Offer(BaseModel):
    term_id: str
    supplier_id: str
    sku_id: str
    unit_cost_minor: int = Field(gt=0)
    currency: str
    moq: int = Field(ge=1)
    order_multiple: int = Field(ge=1)
    lead_time_days: int = Field(ge=0)
    document_version_id: str | None = None
    section: str | None = None
    value_kind: str = "observed"


class Need(BaseModel):
    sku_id: str
    required_units: int = Field(ge=0)
    capacity_units: int | None = Field(default=None, ge=0)
    # Units an offer must cover when its lead time is the key (P1-PLAN-02): a slower supplier protects a longer interval,
    # so it must deliver more. Lead times not listed (or an empty map) fall back to required_units.
    required_units_by_lead_time: dict[int, int] = {}

    def required_for(self, lead_time_days: int) -> int:
        return self.required_units_by_lead_time.get(lead_time_days, self.required_units)

    @property
    def max_required_units(self) -> int:
        return max([self.required_units, *self.required_units_by_lead_time.values()])


class PlanRequest(BaseModel):
    decision_date: date
    need_by: date
    currency: str
    budget_minor: int = Field(ge=0)
    needs: list[Need]
    offers: list[Offer]
    allow_shortfall: bool = False
    shortage_penalty_minor: int = Field(default=0, ge=0)
    max_units_per_line: int = Field(default=100_000, ge=1)


class PlanLine(BaseModel):
    sku_id: str
    supplier_id: str
    term_id: str
    quantity: int
    unit_cost_minor: int
    line_minor: int
    currency: str
    arrival_date: date
    document_version_id: str | None
    section: str | None


class ExcludedOffer(BaseModel):
    term_id: str
    supplier_id: str
    sku_id: str
    reason: str


class PlanResult(BaseModel):
    status: Literal["OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN", "MODEL_INVALID"]
    lines: list[PlanLine] = []
    total_minor: int = 0
    currency: str
    objective: dict = {}
    shortfall: dict[str, int] = {}
    excluded_offers: list[ExcludedOffer] = []
    explanation: list[str] = []
    violations: list[str] = []
    input_hash: str
    solver: dict


def input_hash(req: PlanRequest) -> str:
    canonical = json.dumps(req.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _eligible(req: PlanRequest, ignore: set[str] = frozenset()) -> tuple[list[Offer], list[ExcludedOffer]]:
    keep, excluded = [], []
    skus = {n.sku_id for n in req.needs}
    for o in req.offers:
        reason = None
        if o.sku_id not in skus:
            continue
        if o.currency != req.currency:
            reason = f"currency {o.currency} differs from plan currency {req.currency}; no conversion rate supplied"
        elif "lead_time" not in ignore and req.decision_date + timedelta(days=o.lead_time_days) > req.need_by:
            reason = (f"lead time {o.lead_time_days}d arrives "
                      f"{req.decision_date + timedelta(days=o.lead_time_days)} after need-by {req.need_by}")
        if reason:
            excluded.append(ExcludedOffer(term_id=o.term_id, supplier_id=o.supplier_id, sku_id=o.sku_id,
                                          reason=reason))
        else:
            keep.append(o)
    return keep, excluded


def _upper_bounds(req: PlanRequest, offers: list[Offer]) -> list[int]:
    """Most units one offer can usefully carry: ordering more than max(MOQ, need), rounded up to the order multiple, only
    costs more (unit costs are positive), so no optimal plan exceeds it. Tight bounds keep the arithmetic exact."""
    need = {n.sku_id: n for n in req.needs}
    out = []
    for o in offers:
        n = need.get(o.sku_id)
        useful = max(o.moq, n.required_for(o.lead_time_days) if n else 0)
        out.append(min(req.max_units_per_line, -(-useful // o.order_multiple) * o.order_multiple))
    return out


def _scale(req: PlanRequest, offers: list[Offer], ub: list[int]) -> int:
    """Weight W of the cost objective so that cost differences always outrank the secondary terms (fewer units, then
    supplier order). Raises ScaleError when the largest possible objective does not fit in 64-bit integers."""
    secondary = 100 * sum(ub) + len({o.supplier_id for o in offers}) ** 2 + 1
    w = 10 ** len(str(secondary))
    purchase_max = sum(o.unit_cost_minor * u for o, u in zip(offers, ub, strict=True))
    if purchase_max * w + secondary > INT_LIMIT or max(purchase_max, req.budget_minor) > INT_LIMIT:
        raise ScaleError(f"largest possible spend {purchase_max} (minor units) is too large for exact integer "
                         "arithmetic; quote prices in larger units or plan fewer SKUs per run")
    return w


def _solve(req: PlanRequest, offers: list[Offer], relax: set[str]):
    m = cp_model.CpModel()
    ub = _upper_bounds(req, offers)
    qty, use = {}, {}
    for i, o in enumerate(offers):
        k = m.NewIntVar(0, ub[i] // o.order_multiple, f"k{i}")
        q = m.NewIntVar(0, ub[i], f"q{i}")
        u = m.NewBoolVar(f"u{i}")
        m.Add(q == o.order_multiple * k)
        m.Add(q >= (1 if "moq" in relax else o.moq)).OnlyEnforceIf(u)
        m.Add(q == 0).OnlyEnforceIf(u.Not())
        qty[i], use[i] = q, u
    cost_terms, shortage = [], {}
    for n in req.needs:
        idx = [i for i, o in enumerate(offers) if o.sku_id == n.sku_id]
        m.Add(sum(use[i] for i in idx) <= 1)
        total = sum(qty[i] for i in idx) if idx else 0
        if n.capacity_units is not None and "capacity" not in relax:
            m.Add(total <= n.capacity_units)
        # The chosen offer must cover the requirement for ITS lead time (at most one offer per SKU is used).
        if req.allow_shortfall or "coverage" in relax:
            short = m.NewIntVar(0, n.max_required_units, f"short_{n.sku_id}")
            m.Add(total + short >= n.required_units)
            for i in idx:
                m.Add(qty[i] + short >= n.required_for(offers[i].lead_time_days)).OnlyEnforceIf(use[i])
            shortage[n.sku_id] = short
        else:
            m.Add(total >= n.required_units)
            for i in idx:
                m.Add(qty[i] >= n.required_for(offers[i].lead_time_days)).OnlyEnforceIf(use[i])
    for i, o in enumerate(offers):
        cost_terms.append(o.unit_cost_minor * qty[i])
    purchase = sum(cost_terms) if cost_terms else 0
    if "budget" not in relax:
        m.Add(purchase <= req.budget_minor)
    # Lexicographic, solved in two passes so no weight has to dominate another inside one 64-bit objective:
    # (1) fewest uncovered units, fixed; (2) lowest cost, then fewer units, then supplier order (stable).
    rank = {sid: r for r, sid in enumerate(sorted({o.supplier_id for o in offers}))}
    tiebreak = sum(rank[o.supplier_id] * use[i] for i, o in enumerate(offers)) if offers else 0
    units = sum(qty.values()) if qty else 0
    w = _scale(req, offers, ub)
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = SOLVER_SETTINGS["num_workers"]
    solver.parameters.random_seed = SOLVER_SETTINGS["random_seed"]
    solver.parameters.max_time_in_seconds = SOLVER_SETTINGS["max_time_s"]
    coverage_proven = True
    if shortage:
        uncovered = sum(shortage.values())
        m.Minimize(uncovered)
        status = solver.Solve(m)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return solver, status, qty, use, shortage
        coverage_proven = status == cp_model.OPTIMAL
        m.Add(uncovered <= round(solver.ObjectiveValue()))
        m.ClearObjective()
    m.Minimize(purchase * w + units * 100 + tiebreak)
    status = solver.Solve(m)
    if status == cp_model.OPTIMAL and not coverage_proven:
        status = cp_model.FEASIBLE          # optimal cost for a coverage level that was not proven best
    return solver, status, qty, use, shortage


STATUS = {cp_model.OPTIMAL: "OPTIMAL", cp_model.FEASIBLE: "FEASIBLE", cp_model.INFEASIBLE: "INFEASIBLE",
          cp_model.UNKNOWN: "UNKNOWN", cp_model.MODEL_INVALID: "MODEL_INVALID"}


def plan(req: PlanRequest) -> PlanResult:
    offers, excluded = _eligible(req)
    solver_info = {"name": "OR-Tools CP-SAT", "version": ortools.__version__, **SOLVER_SETTINGS}
    base = dict(currency=req.currency, excluded_offers=excluded, input_hash=input_hash(req),
                solver=solver_info)
    try:
        solver, status, qty, use, shortage = _solve(req, offers, set())
    except ScaleError as e:
        return PlanResult(status="MODEL_INVALID", explanation=[str(e)], **base)
    name = STATUS[status]
    if name == "UNKNOWN":
        # time limit reached without a feasible plan: do not spend up to five more time-limited solves explaining it
        return PlanResult(status=name, explanation=[f"no feasible plan found within the {SOLVER_SETTINGS['max_time_s']:.0f} s "
                                                    "solver time limit; reduce the scope or retry"], **base)
    if name not in ("OPTIMAL", "FEASIBLE"):
        return PlanResult(status=name, explanation=explain_infeasible(req), **base)
    lines = []
    for i, o in enumerate(offers):
        q = solver.Value(qty[i])
        if q:
            lines.append(PlanLine(
                sku_id=o.sku_id, supplier_id=o.supplier_id, term_id=o.term_id, quantity=q,
                unit_cost_minor=o.unit_cost_minor, line_minor=q * o.unit_cost_minor, currency=o.currency,
                arrival_date=req.decision_date + timedelta(days=o.lead_time_days),
                document_version_id=o.document_version_id, section=o.section))
    short = {k: solver.Value(v) for k, v in shortage.items() if solver.Value(v)}
    total = sum(line.line_minor for line in lines)
    result = PlanResult(
        status=name, lines=lines, total_minor=total, shortfall=short,
        objective={"purchase_minor": total,
                   "shortage_units": sum(short.values()),
                   "shortage_penalty_minor": sum(short.values()) * req.shortage_penalty_minor,
                   "proven_optimal": name == "OPTIMAL"},
        **base)
    if short:
        # Say which hard constraint forced the gap (coverage-first objective: nothing else can cause one).
        why = [r for r in explain_infeasible(req.model_copy(update={"allow_shortfall": False}))
               if "'coverage'" not in r]
        result.explanation = [f"{sum(short.values())} required unit(s) cannot be covered within the constraints"] + why
    from .validator import validate
    result.violations = validate(req, result)
    if result.violations:
        # A plan that fails independent validation is never returned as acceptable.
        result.status = "MODEL_INVALID"
    return result


def explain_infeasible(req: PlanRequest) -> list[str]:
    """Name each constraint family whose relaxation alone yields a feasible plan."""
    reasons = []
    offers, _ = _eligible(req)
    skus_without = [n.sku_id for n in req.needs if n.required_units > 0
                    and not any(o.sku_id == n.sku_id for o in offers)]
    if skus_without:
        reasons.append(f"No eligible offer for: {', '.join(skus_without)}")
    checks = [
        ("budget", "Budget is too small for the cheapest feasible order", set()),
        ("moq", "Minimum order quantities force spend above the budget or capacity", set()),
        ("capacity", "Storage capacity is below the minimum orderable quantity", set()),
        ("lead_time", "Only offers that arrive after the need-by date could satisfy the need", {"lead_time"}),
        ("coverage", "Required units cannot be fully covered; a partial order would fit", set()),
    ]
    for family, message, ignore in checks:
        cand, _ = _eligible(req, ignore) if ignore else (offers, None)
        try:
            _, status, *_ = _solve(req, cand, {family})
        except ScaleError:          # e.g. an offer excluded for its lead time is too large to model exactly (P3-PLAN-06)
            reasons.append(f"relaxing '{family}' could not be tested: prices too large for exact integer arithmetic")
            continue
        if STATUS[status] in ("OPTIMAL", "FEASIBLE"):
            reasons.append(f"{message} (relaxing '{family}' makes the problem feasible)")
    return reasons or ["No single constraint relaxation restores feasibility"]
