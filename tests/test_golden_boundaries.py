"""Golden boundary cases (ARC-03): unit, currency, timezone, return, duplicate-event, late-arrival and missing-value.

Each case pins one edge of a rule to an exact expected value. They are deliberately small and independent, so a failure
names the boundary that moved. The planner, term-resolution, ingestion-classification, forecasting and retrieval code
under test is the production code; nothing here is mocked except the clock inputs the cases choose.
"""
from datetime import UTC, date, datetime, timedelta, timezone

import pandas as pd
import pytest

from supplylens.knowledge.ingest import ingest_document
from supplylens.knowledge.retrieve import search
from supplylens_ml import uci
from supplylens_ml.baselines import seasonal_naive
from supplylens_opt.leadtime_demand import ar1_acf
from supplylens_opt.planner import Need, Offer, PlanRequest, plan
from supplylens_opt.replenishment import Position, assess
from supplylens_opt.terms import Term, resolve

DEC = date(2026, 1, 1)
NEED_BY = date(2026, 1, 31)


# ----------------------------------------------------------------------------------------------- helpers
def offer(term="T1", sup="S1", sku="SKU", cost=100, cur="USD", moq=1, mult=1, lead=0):
    return Offer(term_id=term, supplier_id=sup, sku_id=sku, unit_cost_minor=cost, currency=cur, moq=moq, order_multiple=mult,
                 lead_time_days=lead)


def run(offers, need=10, budget=10**9, shortfall=False, penalty=0, capacity=None, cur="USD", need_by=NEED_BY):
    return plan(PlanRequest(decision_date=DEC, need_by=need_by, currency=cur, budget_minor=budget,
                            needs=[Need(sku_id="SKU", required_units=need, capacity_units=capacity)], offers=offers,
                            allow_shortfall=shortfall, shortage_penalty_minor=penalty))


def qty(result):
    return sum(line.quantity for line in result.lines)


def term(tid="A1", known="2026-01-01T00:00:00+00:00", frm=date(2026, 1, 1), to=None, supersedes=None, sup="S1"):
    return Term(term_id=tid, supplier_id=sup, sku_id="SKU", unit_cost_minor=100, currency="USD", moq=1, order_multiple=1,
                lead_time_days=0, valid_from=frm, valid_to=to, known_at=datetime.fromisoformat(known), supersedes=supersedes)


def sheet(*rows):
    """Raw bronze rows: (invoice, stock code, description, quantity, invoice date, price, customer id, country)."""
    return pd.DataFrame(list(rows), columns=uci.COLUMNS).assign(source_row=range(2, 2 + len(rows)))[["source_row", *uci.COLUMNS]]


def line(inv="500001", code="21232", desc="MUG", qty_="6", ts="2010-03-01 09:00:00", price="1.25", cust="12346", country="France"):
    return (inv, code, desc, qty_, ts, price, cust, country)


def classify_one(*rows):
    return uci.classify(uci.SHEETS[0], sheet(*rows))


# ======================================================================================= UNITS (order quantities)
def test_unit_need_below_moq_orders_the_moq():
    assert qty(run([offer(moq=10)], need=3)) == 10


def test_unit_need_equal_to_moq_orders_exactly_the_moq():
    assert qty(run([offer(moq=10)], need=10)) == 10


def test_unit_need_between_multiples_rounds_up_to_the_next_multiple():
    assert qty(run([offer(mult=6)], need=7)) == 12


def test_unit_need_on_a_multiple_is_not_rounded_up():
    assert qty(run([offer(mult=6)], need=12)) == 12


def test_unit_moq_that_is_not_a_multiple_rounds_up_to_the_next_multiple_above_it():
    assert qty(run([offer(moq=12, mult=5)], need=1)) == 15


def test_unit_zero_need_orders_nothing_and_is_optimal():
    r = run([offer(moq=10)], need=0)
    assert r.status == "OPTIMAL" and r.lines == [] and r.total_minor == 0


def test_unit_capacity_below_moq_is_infeasible_and_names_capacity():
    r = run([offer(moq=10)], need=3, capacity=5)
    assert r.status == "INFEASIBLE" and any("capacity" in e for e in r.explanation)


def test_unit_capacity_equal_to_the_rounded_order_is_feasible():
    assert qty(run([offer(mult=6)], need=11, capacity=12)) == 12


def test_unit_cheaper_supplier_wins_even_when_it_has_a_large_moq_if_total_cost_is_lower():
    a, b = offer("A", "SA", cost=100, moq=50), offer("B", "SB", cost=120, moq=1)
    assert run([a, b], need=10).lines[0].supplier_id == "SB"          # 10 x 120 = 1200 < 50 x 100 = 5000
    assert run([a, b], need=50).lines[0].supplier_id == "SA"          # 50 x 100 = 5000 < 50 x 120 = 6000


def test_unit_exact_cost_tie_is_broken_by_supplier_id_not_by_input_order():
    a, b = offer("A", "S1"), offer("B", "S2")
    assert run([b, a]).lines[0].supplier_id == "S1"
    assert run([a, b]).lines[0].supplier_id == "S1"


# ======================================================================================= CURRENCY and money
def test_currency_budget_exactly_equal_to_the_total_is_feasible():
    r = run([offer(cost=100)], need=10, budget=1000)
    assert r.status == "OPTIMAL" and r.total_minor == 1000


def test_currency_budget_one_minor_unit_short_is_infeasible_without_shortfall():
    r = run([offer(cost=100)], need=10, budget=999)
    assert r.status == "INFEASIBLE" and any("Budget" in e for e in r.explanation)


def test_currency_budget_one_minor_unit_short_with_shortfall_buys_nine_and_reports_one_short():
    r = run([offer(cost=100)], need=10, budget=999, shortfall=True, penalty=500)
    assert qty(r) == 9 and r.shortfall == {"SKU": 1}


def test_currency_zero_budget_with_shortfall_orders_nothing():
    r = run([offer(cost=100)], need=10, budget=0, shortfall=True, penalty=500)
    assert r.lines == [] and r.shortfall == {"SKU": 10}


def test_currency_offer_in_another_currency_is_excluded_with_a_reason_and_never_converted():
    r = run([offer("A", "SA", cost=100, cur="USD"), offer("B", "SB", cost=1, cur="EUR")], need=10)
    assert [line.supplier_id for line in r.lines] == ["SA"]
    assert any(x.term_id == "B" and "EUR differs from plan currency USD" in x.reason for x in r.excluded_offers)


def test_currency_code_comparison_is_exact_so_lowercase_is_a_different_currency():
    r = run([offer(cur="usd")], need=10)
    assert r.status == "INFEASIBLE" and any("No eligible offer" in e for e in r.explanation)


def test_currency_money_stays_exact_integer_at_large_values():
    r = run([offer(cost=1_000_000_000)], need=1000, budget=10**12)
    assert r.lines[0].line_minor == 1_000_000_000_000 and isinstance(r.total_minor, int) and r.total_minor == 10**12


def test_currency_values_beyond_exact_integer_range_are_refused_with_a_clear_reason_not_silently_misplanned():
    r = run([offer(cost=50_000_000_000)], need=1000, budget=10**18)
    assert r.status == "MODEL_INVALID" and r.lines == []
    assert any("too large for exact integer arithmetic" in e for e in r.explanation)


def test_unit_the_order_never_exceeds_the_larger_of_moq_and_need_rounded_to_the_multiple():
    assert qty(run([offer(moq=40, mult=8)], need=5)) == 40
    assert qty(run([offer(moq=40, mult=8)], need=41)) == 48


def test_currency_every_line_equals_quantity_times_unit_price_with_no_rounding():
    r = run([offer(cost=333, mult=7)], need=100)
    for ln in r.lines:
        assert ln.line_minor == ln.quantity * ln.unit_cost_minor


def test_unit_offer_arriving_exactly_on_the_need_by_date_is_eligible_one_day_later_is_not():
    on_day = (NEED_BY - DEC).days
    assert run([offer(lead=on_day)]).status == "OPTIMAL"
    late = run([offer(lead=on_day + 1)])
    assert late.status == "INFEASIBLE" and any("after need-by" in x.reason for x in late.excluded_offers)


def test_missing_no_offers_at_all_is_infeasible_and_names_the_sku():
    r = run([], need=5)
    assert r.status == "INFEASIBLE" and any("SKU" in e and "No eligible offer" in e for e in r.explanation)


# ======================================================================================= TIMEZONE and clocks
CUT = datetime(2026, 9, 15, 0, 0, 0, tzinfo=UTC)


def test_timezone_term_known_exactly_at_the_cutoff_is_known():
    r = resolve([term(known="2026-09-15T00:00:00+00:00")], CUT, date(2026, 9, 15))
    assert [t.term_id for t in r.applicable] == ["A1"]


def test_timezone_term_known_one_microsecond_after_the_cutoff_is_not_known():
    t = term()
    t = t.model_copy(update={"known_at": CUT + timedelta(microseconds=1)})
    r = resolve([t], CUT, date(2026, 9, 15))
    assert r.applicable == [] and r.ignored[0].reason == "not known at knowledge cutoff"


def test_timezone_a_cutoff_in_another_offset_is_the_same_instant():
    ist = timezone(timedelta(hours=5, minutes=30))
    cutoff_ist = datetime(2026, 9, 15, 5, 30, 0, tzinfo=ist)             # == 2026-09-15T00:00:00Z
    assert cutoff_ist == CUT
    exactly = resolve([term(known="2026-09-15T00:00:00+00:00")], cutoff_ist, date(2026, 9, 15))
    one_second_later = resolve([term(known="2026-09-15T00:00:01+00:00")], cutoff_ist, date(2026, 9, 15))
    assert len(exactly.applicable) == 1 and one_second_later.applicable == []


def test_timezone_known_at_written_in_another_offset_compares_by_instant():
    # 2026-09-15T05:30+05:30 is midnight UTC: known at the cutoff. 05:31+05:30 is a minute after: not known.
    assert len(resolve([term(known="2026-09-15T05:30:00+05:30")], CUT, date(2026, 9, 15)).applicable) == 1
    assert resolve([term(known="2026-09-15T05:31:00+05:30")], CUT, date(2026, 9, 15)).applicable == []


def test_timezone_valid_from_equal_to_the_effective_date_applies_the_day_before_does_not():
    eff = date(2026, 9, 15)
    assert len(resolve([term(frm=eff)], CUT, eff).applicable) == 1
    r = resolve([term(frm=eff + timedelta(days=1))], CUT, eff)
    assert r.applicable == [] and r.ignored[0].reason.startswith("not yet effective")


def test_timezone_valid_to_equal_to_the_effective_date_still_applies_the_day_after_it_is_expired():
    eff = date(2026, 9, 15)
    assert len(resolve([term(to=eff)], CUT, eff).applicable) == 1
    r = resolve([term(to=eff - timedelta(days=1))], CUT, eff)
    assert r.applicable == [] and r.ignored[0].reason.startswith("expired")


def test_timezone_naive_and_aware_datetimes_cannot_be_compared_so_naive_input_is_an_error_not_a_guess():
    naive = term().model_copy(update={"known_at": datetime(2026, 9, 1)})
    with pytest.raises(TypeError):
        resolve([naive], CUT, date(2026, 9, 15))


# ======================================================================================= LATE ARRIVAL
def test_late_amendment_known_one_second_after_the_cutoff_does_not_replace_the_old_term():
    v1 = term("V1", known="2026-01-01T00:00:00+00:00")
    v2 = term("V2", known="2026-09-15T00:00:01+00:00", supersedes="V1")
    r = resolve([v1, v2], CUT, date(2026, 9, 15))
    assert [t.term_id for t in r.applicable] == ["V1"]
    assert any(i.term_id == "V2" and i.reason == "not known at knowledge cutoff" for i in r.ignored)


def test_late_amendment_known_at_the_cutoff_does_replace_the_old_term():
    v1 = term("V1", known="2026-01-01T00:00:00+00:00")
    v2 = term("V2", known="2026-09-15T00:00:00+00:00", supersedes="V1")
    assert [t.term_id for t in resolve([v1, v2], CUT, date(2026, 9, 15)).applicable] == ["V2"]


def test_late_known_amendment_not_yet_effective_leaves_the_old_term_in_force():
    v1 = term("V1")
    v2 = term("V2", known="2026-09-01T00:00:00+00:00", frm=date(2026, 10, 1), supersedes="V1")
    r = resolve([v1, v2], CUT, date(2026, 9, 15))
    assert [t.term_id for t in r.applicable] == ["V1"]


def test_late_supersession_chain_leaves_only_the_newest_live_term():
    v1, v2 = term("V1"), term("V2", supersedes="V1")
    v3 = term("V3", supersedes="V2")
    r = resolve([v1, v2, v3], CUT, date(2026, 9, 15))
    assert [t.term_id for t in r.applicable] == ["V3"] and r.conflicts == []


def test_late_two_live_terms_without_a_supersession_link_are_a_conflict_not_a_choice():
    r = resolve([term("X1"), term("X2")], CUT, date(2026, 9, 15))
    assert r.conflicts == [["X1", "X2"]]


def test_late_seasonal_forecast_cannot_see_rows_after_its_origin():
    idx = pd.date_range("2011-01-03", periods=70, freq="D")
    s = pd.Series([5.0, 3, 0, 4, 6, 0, 2] * 10, index=idx)
    origin = idx[-8]
    late = s.copy()
    late.loc[origin + timedelta(days=1):] = 9999.0               # sales that arrive (or are booked) after the origin
    pd.testing.assert_frame_equal(seasonal_naive(s[:origin], 7), seasonal_naive(late[:origin], 7))


# ======================================================================================= RETURNS (UCI classification)
def test_return_cancellation_invoice_with_negative_quantity_is_a_return_not_a_sale():
    c = classify_one(line(inv="C500002", qty_="-3"))
    assert (len(c.accepted), len(c.returned), len(c.quarantined)) == (0, 1, 0)
    assert c.returned["return_kind"].iloc[0] == "cancellation_invoice"


def test_return_negative_quantity_on_an_ordinary_invoice_is_a_return():
    c = classify_one(line(inv="500003", qty_="-2"))
    assert len(c.returned) == 1 and c.returned["return_kind"].iloc[0] == "negative_quantity"


def test_return_with_zero_price_is_still_a_return_the_zero_price_rule_applies_to_sales_only():
    c = classify_one(line(inv="500004", qty_="-5", price="0"))
    assert len(c.returned) == 1 and c.quarantined.empty


def test_return_never_reaches_the_accepted_sales_used_for_demand():
    c = classify_one(line(inv="C500005", qty_="-9"), line(inv="500006", qty_="4"))
    assert list(c.accepted["qty"]) == [4] and list(c.returned["qty"]) == [-9]


def test_return_cancellation_invoice_with_a_positive_quantity_is_held_with_returns_not_sold():
    c = classify_one(line(inv="C500007", qty_="3"))
    assert len(c.accepted) == 0 and len(c.returned) == 1


# ======================================================================================= DUPLICATE EVENTS
def test_duplicate_identical_sale_lines_keep_the_first_and_quarantine_the_rest():
    c = classify_one(line(), line(), line())
    assert len(c.accepted) == 1 and c.counts["quarantine_reasons"] == {"exact_duplicate_line": 2}


def test_duplicate_lines_that_differ_in_quantity_are_two_sales():
    assert len(classify_one(line(qty_="6"), line(qty_="7")).accepted) == 2


def test_duplicate_lines_that_differ_in_timestamp_by_one_second_are_two_sales():
    assert len(classify_one(line(ts="2010-03-01 09:00:00"), line(ts="2010-03-01 09:00:01")).accepted) == 2


def test_duplicate_invoice_in_two_sheets_is_counted_once():
    a = uci.classify(uci.SHEETS[0], sheet(line(inv="500010")))
    b = uci.classify(uci.SHEETS[1], sheet(line(inv="500010"), line(inv="500011")))
    out = uci.resolve_sheet_overlap({uci.SHEETS[0]: a, uci.SHEETS[1]: b})
    assert len(out[uci.SHEETS[0]].accepted) == 1 and len(out[uci.SHEETS[1]].accepted) == 1
    assert out[uci.SHEETS[1]].counts["quarantine_reasons"]["cross_sheet_overlap"] == 1


def test_every_input_row_gets_exactly_one_disposition():
    c = classify_one(line(), line(inv="C500020", qty_="-1"), line(code="POST"), line(qty_="0"), line(price="abc"),
                     line(ts="2010-02-30 10:00:00"), line(inv=""), line(code=" "))
    n = c.counts
    assert n["accepted"] + n["returned"] + n["quarantined"] == n["input_rows"] == 8


# ======================================================================================= MISSING / MALFORMED VALUES
@pytest.mark.parametrize("price,minor", [("6.955", 696), ("0.005", 1), ("0.004", 0), ("1.25", 125), ("1e2", 10000)])
def test_missing_values_price_to_integer_minor_units_rounds_half_up(price, minor):
    assert uci._to_minor(price) == minor


def test_missing_values_unparseable_price_and_quantity_are_quarantined_with_their_own_reason():
    c = classify_one(line(price="abc"), line(inv="500031", qty_="x"), line(inv="500032", qty_="1.5"))
    assert c.counts["quarantine_reasons"] == {"invalid_price": 1, "invalid_quantity": 2}


def test_missing_values_negative_price_adjustments_are_not_sales_or_returns():
    c = classify_one(line(price="-0.5"))
    assert c.counts["quarantine_reasons"] == {"negative_price_adjustment": 1}


def test_missing_values_stock_code_case_and_whitespace_are_normalised():
    c = classify_one(line(code=" 85048a "), line(inv=" 500041 ", code="22087"))
    assert sorted(c.accepted["sku_id"]) == ["22087", "85048A"]
    assert "500041" in set(c.accepted["invoice"])


def test_missing_values_missing_customer_is_accepted_with_a_null_customer_not_dropped():
    c = classify_one(line(cust=""))
    assert len(c.accepted) == 1 and pd.isna(c.accepted["customer_id"].iloc[0])


def test_missing_values_non_merchandise_codes_are_quarantined_not_sold():
    c = classify_one(line(code="POST"), line(inv="500051", code="M"), line(inv="500052", code="DOT"))
    assert c.counts["quarantine_reasons"] == {"non_merchandise_code": 3}


def test_missing_values_midnight_boundary_timestamps_are_kept_as_recorded_without_zone_shift():
    c = classify_one(line(ts="2010-12-31 23:59:59"), line(inv="500061", ts="2011-01-01 00:00:00"))
    assert [str(t) for t in c.accepted["ts"]] == ["2010-12-31 23:59:59", "2011-01-01 00:00:00"]


def test_missing_values_history_shorter_than_one_season_is_refused_not_extrapolated():
    with pytest.raises(ValueError):
        seasonal_naive(pd.Series([1.0] * 6, index=pd.date_range("2011-01-03", periods=6)), 7)


def test_missing_values_exactly_one_season_of_history_gives_a_degenerate_but_ordered_interval():
    f = seasonal_naive(pd.Series([5.0, 3, 0, 4, 6, 0, 2], index=pd.date_range("2011-01-03", periods=7)), 7)
    assert list(f["q50"]) == [5, 3, 0, 4, 6, 0, 2]
    assert (f["q10"] <= f["q50"]).all() and (f["q50"] <= f["q90"]).all()


def test_missing_values_all_zero_history_forecasts_zero_not_nan():
    f = seasonal_naive(pd.Series([0.0] * 28, index=pd.date_range("2011-01-03", periods=28)), 14)
    assert (f[["q10", "q50", "q90"]] == 0).all().all()


# ---- replenishment need boundaries ------------------------------------------------------------------
def path(q10=2.0, q50=5.0, q90=9.0, n=28):
    return [{"day": date(2026, 1, 2) + timedelta(days=i), "q10": q10, "q50": q50, "q90": q90} for i in range(n)]


AR = ar1_acf(0.3)


def pos(on_hand=40, allocated=0, on_order=0, capacity=None):
    return Position(sku_id="S", on_hand=on_hand, allocated=allocated, on_order=on_order, capacity=capacity)


def test_missing_values_zero_forecast_demand_needs_nothing_and_has_no_cover_figure():
    a = assess(pos(), path(0, 0, 0), DEC, 21, 5, acf=AR)
    assert a.required_units == 0 and a.days_of_cover is None and a.status in ("healthy", "excess")


def test_unit_allocated_stock_above_on_hand_is_a_shortage_that_triggers_an_order():
    a = assess(pos(on_hand=10, allocated=30), path(), DEC, 21, 5, acf=AR)
    assert a.available == -20 and a.required_units > 0 and a.status == "shortage_risk"


def test_unit_on_order_stock_counts_toward_the_position_and_reduces_the_order():
    base = assess(pos(on_order=0), path(), DEC, 21, 5, acf=AR).required_units
    covered = assess(pos(on_order=10), path(), DEC, 21, 5, acf=AR).required_units
    assert base - covered == 10


def test_unit_capacity_zero_caps_the_order_at_zero():
    assert assess(pos(capacity=0), path(), DEC, 21, 5, acf=AR).required_units == 0


def test_unit_capacity_below_current_position_never_produces_a_negative_order():
    assert assess(pos(on_hand=100, capacity=60), path(), DEC, 21, 5, acf=AR).required_units == 0


# ======================================================================================= retrieval clocks (database)
SUPPLIER = "GOLDEN-SUP"
BODY = "Late delivery penalty: zebraquartz surcharge of two percent applies per week."


def ingested(tenant, **kw):
    base = dict(title="Golden agreement", doc_type="contract", supplier_id=SUPPLIER, source_kind="generated", file_name="g.txt",
                body=BODY, version_label="v1", known_at=datetime(2026, 6, 2, tzinfo=UTC), valid_from=date(2026, 6, 1))
    base.update(kw)
    return ingest_document(tenant, **base)


def found(tenant, as_of, **kw):
    r = search(tenant, "zebraquartz surcharge", as_of=as_of, role=kw.pop("role", "viewer"), use_vectors=False, **kw)
    return len(r["results"])


def test_late_document_known_one_second_after_the_cutoff_is_not_retrievable(clean_db, tenant_b):
    ingested(tenant_b)
    assert found(tenant_b, datetime(2026, 6, 1, 23, 59, 59, tzinfo=UTC)) == 0


def test_late_document_known_exactly_at_the_cutoff_is_retrievable(clean_db, tenant_b):
    ingested(tenant_b)
    assert found(tenant_b, datetime(2026, 6, 2, 0, 0, 0, tzinfo=UTC), effective_date=date(2026, 6, 2)) >= 1


def test_timezone_retrieval_cutoff_in_another_offset_is_the_same_instant(clean_db, tenant_b):
    ingested(tenant_b)
    ist = timezone(timedelta(hours=5, minutes=30))
    assert found(tenant_b, datetime(2026, 6, 2, 5, 30, 0, tzinfo=ist), effective_date=date(2026, 6, 2)) >= 1
    assert found(tenant_b, datetime(2026, 6, 2, 5, 29, 59, tzinfo=ist)) == 0


def test_timezone_retrieval_effective_date_boundaries_are_inclusive_at_both_ends(clean_db, tenant_b):
    ingested(tenant_b, valid_to=date(2026, 6, 30))
    cut = datetime(2026, 7, 15, tzinfo=UTC)
    assert found(tenant_b, cut, effective_date=date(2026, 5, 31)) == 0          # day before valid_from
    assert found(tenant_b, cut, effective_date=date(2026, 6, 1)) >= 1           # valid_from itself
    assert found(tenant_b, cut, effective_date=date(2026, 6, 30)) >= 1          # valid_to itself
    assert found(tenant_b, cut, effective_date=date(2026, 7, 1)) == 0           # day after valid_to
    assert found(tenant_b, cut, effective_date=date(2026, 7, 1), mode="known") >= 1   # "known" mode ignores validity


def test_missing_role_not_on_the_document_acl_gets_nothing_not_a_redacted_hit(clean_db, tenant_b):
    ingested(tenant_b, allowed_roles=["approver", "tenant_admin"])
    cut = datetime(2026, 6, 15, tzinfo=UTC)
    assert found(tenant_b, cut, role="viewer") == 0
    assert found(tenant_b, cut, role="approver") >= 1
