"""Reweighed coverage for fair allocation (F3): shortage weights in the planner's coverage objective."""
from datetime import date, timedelta

from supplylens_opt.planner import Need, Offer, PlanRequest, plan

D = date(2026, 1, 5)


def request(weight_b=None):
    """Budget 1,000p buys 10 of A (100p) or 5 of B (200p); each needs 10."""
    offer = lambda sku, cost: Offer(term_id=f"T-{sku}", supplier_id="SUP", sku_id=sku, unit_cost_minor=cost, currency="GBP",  # noqa: E731
                                    moq=1, order_multiple=1, lead_time_days=1)
    return PlanRequest(decision_date=D, need_by=D + timedelta(days=7), currency="GBP", budget_minor=1_000, allow_shortfall=True,
                       needs=[Need(sku_id="A", required_units=10), Need(sku_id="B", required_units=10, shortage_weight=weight_b)],
                       offers=[offer("A", 100), offer("B", 200)])


def test_unweighted_coverage_buys_the_most_units():
    r = plan(request())
    assert {line.sku_id: line.quantity for line in r.lines} == {"A": 10} and r.shortfall == {"B": 10}


def test_a_heavier_weight_moves_the_budget_to_the_under_served_product():
    r = plan(request(weight_b=3))                        # 3 x 5 units of B outweigh 1 x 10 units of A
    assert {line.sku_id: line.quantity for line in r.lines} == {"B": 5} and r.shortfall == {"A": 10, "B": 5}
    assert not r.violations
