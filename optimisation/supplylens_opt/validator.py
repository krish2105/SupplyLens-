"""Independent plan validator. Recomputes every hard constraint from the request alone."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from .planner import PlanRequest, PlanResult


def validate(req: PlanRequest, result: PlanResult) -> list[str]:
    errors: list[str] = []
    offers = {o.term_id: o for o in req.offers}
    per_sku = defaultdict(int)
    suppliers_per_sku = defaultdict(set)
    lead_per_sku = {}
    total = 0
    for line in result.lines:
        o = offers.get(line.term_id)
        if o is None or o.supplier_id != line.supplier_id or o.sku_id != line.sku_id:
            errors.append(f"{line.sku_id}: line does not match an offered term ({line.term_id})")
            continue
        if line.quantity < o.moq:
            errors.append(f"{line.sku_id}/{line.supplier_id}: quantity {line.quantity} below MOQ {o.moq}")
        if line.quantity % o.order_multiple:
            errors.append(f"{line.sku_id}/{line.supplier_id}: quantity {line.quantity} "
                          f"not a multiple of {o.order_multiple}")
        if line.unit_cost_minor != o.unit_cost_minor or line.line_minor != line.quantity * o.unit_cost_minor:
            errors.append(f"{line.sku_id}: line cost does not equal quantity x unit cost")
        if line.currency != req.currency or o.currency != req.currency:
            errors.append(f"{line.sku_id}: currency mismatch")
        if req.decision_date + timedelta(days=o.lead_time_days) > req.need_by:
            errors.append(f"{line.sku_id}/{line.supplier_id}: arrives after need-by date")
        per_sku[line.sku_id] += line.quantity
        suppliers_per_sku[line.sku_id].add(line.supplier_id)
        lead_per_sku[line.sku_id] = o.lead_time_days
        total += line.line_minor
    if total != result.total_minor:
        errors.append("plan total does not equal the sum of lines")
    if total > req.budget_minor:
        errors.append(f"total {total} exceeds budget {req.budget_minor}")
    for n in req.needs:
        if len(suppliers_per_sku[n.sku_id]) > 1:
            errors.append(f"{n.sku_id}: more than one supplier")
        if n.capacity_units is not None and per_sku[n.sku_id] > n.capacity_units:
            errors.append(f"{n.sku_id}: exceeds capacity {n.capacity_units}")
        covered = per_sku[n.sku_id] + result.shortfall.get(n.sku_id, 0)
        lead = lead_per_sku.get(n.sku_id)
        required = n.required_units if lead is None else n.required_for(lead)
        if covered < required:
            errors.append(f"{n.sku_id}: need {required} not covered"
                          + (f" (requirement for the chosen {lead}-day lead time)" if lead is not None else ""))
        if result.shortfall.get(n.sku_id) and not req.allow_shortfall:
            errors.append(f"{n.sku_id}: shortfall reported but not allowed")
    return errors
