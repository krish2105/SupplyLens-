"""Reference policy-change scenario (EXE-003/004/005) and planner invariants (ARC-05)."""
import json
from datetime import date, datetime, timezone
from pathlib import Path

from supplylens_opt.planner import Need, PlanLine, PlanRequest, PlanResult, plan
from supplylens_opt.terms import Term, resolve
from supplylens_opt.validator import validate

ROOT = Path(__file__).resolve().parents[1]


def dt(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def solve(terms, cutoff, eff, need_by, budget, units=30, sku="SKU-1"):
    res = resolve(terms, cutoff, eff)
    assert not res.conflicts
    req = PlanRequest(decision_date=eff, need_by=need_by, currency="USD", budget_minor=budget,
                      needs=[Need(sku_id=sku, required_units=units)], offers=res.applicable)
    return plan(req)


def json_fixture_terms():
    fx = json.loads((ROOT / "fixtures" / "policy_change_case.json").read_text())
    a, b = fx["suppliers"]
    eff = date.fromisoformat(a["policy_effective_date"])
    common = dict(sku_id="SKU-1", currency=fx["currency"], order_multiple=1, lead_time_days=0)
    return fx, [
        Term(term_id="A-v1", supplier_id=a["supplier_id"], unit_cost_minor=a["unit_price"] * 100,
             moq=a["minimum_order_before"], valid_from=date(2026, 1, 1), known_at=dt("2026-01-01"), **common),
        Term(term_id="A-v2", supplier_id=a["supplier_id"], unit_cost_minor=a["unit_price"] * 100,
             moq=a["minimum_order_after"], valid_from=eff, known_at=dt("2026-09-15"), supersedes="A-v1",
             **common),
        Term(term_id="B-v1", supplier_id=b["supplier_id"], unit_cost_minor=b["unit_price"] * 100,
             moq=b["minimum_order_before"], valid_from=date(2026, 1, 1), known_at=dt("2026-01-01"), **common),
    ]


def test_json_fixture_expected_outcomes():
    fx, terms = json_fixture_terms()
    budget = fx["budget"] * 100
    before = solve(terms, dt("2026-09-30T12:00"), date(2026, 9, 30), date(2026, 9, 30), budget)
    after = solve(terms, dt("2026-10-02T12:00"), date(2026, 10, 2), date(2026, 10, 2), budget)
    exp_b, exp_a = fx["expected"]["as_of_2026-09-30"], fx["expected"]["as_of_2026-10-02"]
    assert [(l.supplier_id, l.quantity) for l in before.lines] == [(exp_b["supplier"], exp_b["units"])]
    assert before.total_minor == exp_b["total_cost"] * 100
    assert [(l.supplier_id, l.quantity) for l in after.lines] == [(exp_a["supplier"], exp_a["units"])]
    assert after.total_minor == exp_a["total_cost"] * 100
    assert before.status == after.status == "OPTIMAL"


def spec_terms(amendment_known_at="2026-10-15"):
    common = dict(sku_id="SKU-1", currency="USD", lead_time_days=2)
    return [
        Term(term_id="A-v1", supplier_id="supplier-A", unit_cost_minor=500, moq=20, order_multiple=10,
             valid_from=date(2026, 1, 1), known_at=dt("2026-01-01"), **common),
        Term(term_id="A-v2", supplier_id="supplier-A", unit_cost_minor=500, moq=40, order_multiple=10,
             valid_from=date(2026, 10, 20), known_at=dt(amendment_known_at), supersedes="A-v1", **common),
        Term(term_id="B-v1", supplier_id="supplier-B", unit_cost_minor=600, moq=10, order_multiple=5,
             valid_from=date(2026, 1, 1), known_at=dt("2026-01-01"), **common),
    ]


def test_spec_text_variant():
    terms = spec_terms()
    before = solve(terms, dt("2026-10-19T09:00"), date(2026, 10, 19), date(2026, 10, 22), 18000)
    after = solve(terms, dt("2026-10-20T09:00"), date(2026, 10, 20), date(2026, 10, 22), 18000)
    assert [(l.supplier_id, l.quantity, l.line_minor) for l in before.lines] == [("supplier-A", 30, 15000)]
    assert [(l.supplier_id, l.quantity, l.line_minor) for l in after.lines] == [("supplier-B", 30, 18000)]


def test_amendment_known_before_effective_date_is_not_applied_early():
    res = resolve(spec_terms(), dt("2026-10-19T09:00"), date(2026, 10, 19))
    assert {t.term_id for t in res.applicable} == {"A-v1", "B-v1"}
    assert any(i.term_id == "A-v2" and "not yet effective" in i.reason for i in res.ignored)


def test_delayed_knowledge_variant_backtest_cannot_use_unknown_amendment():
    terms = spec_terms(amendment_known_at="2026-10-21T08:00")
    backtest = solve(terms, dt("2026-10-20T09:00"), date(2026, 10, 20), date(2026, 10, 22), 18000)
    assert [(l.supplier_id, l.quantity) for l in backtest.lines] == [("supplier-A", 30)]
    res = resolve(terms, dt("2026-10-20T09:00"), date(2026, 10, 20))
    assert any(i.term_id == "A-v2" and i.reason == "not known at knowledge cutoff" for i in res.ignored)
    hindsight = solve(terms, dt("2026-10-21T09:00"), date(2026, 10, 20), date(2026, 10, 22), 18000)
    assert [(l.supplier_id, l.quantity) for l in hindsight.lines] == [("supplier-B", 30)]


def test_unresolved_conflict_is_reported_not_resolved():
    terms = spec_terms()
    terms.append(Term(term_id="A-side-letter", supplier_id="supplier-A", sku_id="SKU-1", currency="USD",
                      unit_cost_minor=450, moq=50, order_multiple=10, lead_time_days=2,
                      valid_from=date(2026, 6, 1), known_at=dt("2026-06-01")))
    res = resolve(terms, dt("2026-10-19T09:00"), date(2026, 10, 19))
    assert res.conflicts == [["A-side-letter", "A-v1"]]


def test_infeasible_budget_is_explained_not_invented():
    r = solve(spec_terms(), dt("2026-10-20T09:00"), date(2026, 10, 20), date(2026, 10, 22), 14000)
    assert r.status == "INFEASIBLE" and r.lines == []
    assert any("budget" in e for e in r.explanation)


def test_lead_time_excludes_late_offers_with_reason():
    r = solve(spec_terms(), dt("2026-10-21T09:00"), date(2026, 10, 21), date(2026, 10, 22), 18000)
    assert r.status == "INFEASIBLE"
    assert len(r.excluded_offers) == 2 and all("after need-by" in e.reason for e in r.excluded_offers)
    assert any("lead_time" in e for e in r.explanation)


def test_validator_rejects_hand_built_invalid_line():
    terms = spec_terms()
    req = PlanRequest(decision_date=date(2026, 10, 20), need_by=date(2026, 10, 22), currency="USD",
                      budget_minor=18000, needs=[Need(sku_id="SKU-1", required_units=30)],
                      offers=resolve(terms, dt("2026-10-20"), date(2026, 10, 20)).applicable)
    bad = PlanResult(status="OPTIMAL", currency="USD", input_hash="x", solver={}, total_minor=15000, lines=[
        PlanLine(sku_id="SKU-1", supplier_id="supplier-A", term_id="A-v2", quantity=30, unit_cost_minor=500,
                 line_minor=15000, currency="USD", arrival_date=date(2026, 10, 22),
                 document_version_id=None, section=None)])
    errors = validate(req, bad)
    assert any("below MOQ 40" in e for e in errors)


def test_same_inputs_same_hash_and_plan():
    a = solve(spec_terms(), dt("2026-10-20T09:00"), date(2026, 10, 20), date(2026, 10, 22), 18000)
    b = solve(spec_terms(), dt("2026-10-20T09:00"), date(2026, 10, 20), date(2026, 10, 22), 18000)
    assert a.input_hash == b.input_hash and a.lines == b.lines


def test_currency_mismatch_excluded_without_conversion():
    terms = spec_terms()
    terms[2] = terms[2].model_copy(update={"currency": "EUR"})
    r = solve(terms, dt("2026-10-20T09:00"), date(2026, 10, 20), date(2026, 10, 22), 18000)
    assert r.status == "INFEASIBLE"
    assert any("no conversion rate" in e.reason for e in r.excluded_offers)
