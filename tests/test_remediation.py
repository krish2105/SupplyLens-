"""Regression tests for the CTO-audit findings corrected in session 4 (docs/remediation/register.json).

Each test states correct behaviour, not the old defect: they run against the real PostgreSQL schema, the CP-SAT solver
and the sandbox adapter. Finding IDs are in the test names.
"""
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from supplylens.actions import service as act
from supplylens.agent.graph import create_run
from supplylens.api import routes_decisions
from supplylens.api.app import app
from supplylens.authz import resolve_actor
from supplylens.db import admin_engine, tenant_session
from supplylens.integrations import sandbox_erp
from supplylens.planning.positions import MAX_SKUS_PER_RUN, load_positions
from supplylens.planning.scenario import ScenarioInput, run_scenario
from supplylens.planning.terms_service import applicable_terms
from supplylens.seed import dev_email, user_id
from supplylens.simulation import demo
from supplylens_opt.leadtime_demand import ar1_acf
from supplylens_opt.planner import Need, Offer, PlanRequest, plan
from supplylens_opt.replenishment import Position, assess
from supplylens_worker.main import tick

H = {"X-Requested-With": "supplylens"}
DEMO = {**H, "X-SupplyLens-Tenant": "demo"}
UCI = {**H, "X-SupplyLens-Tenant": "uci-research"}
CUTOFF = datetime(2026, 10, 20, 9, tzinfo=UTC)
DEC = date(2026, 1, 1)
AR = ar1_acf(0.3)


def who(tenant, role):
    return resolve_actor(user_id(dev_email(role)), tenant)


def path(days=28, start=DEC + timedelta(days=1), q=(2.0, 4.0, 7.0)):
    return [{"day": start + timedelta(days=i), "q10": q[0], "q50": q[1], "q90": q[2]} for i in range(days)]


# =========================================================================================== F02 clocks and windows
def test_F02_only_days_after_the_decision_date_count_seven_days_mean_seven():
    rows = path(35, start=DEC - timedelta(days=6))           # forecast starts BEFORE the decision date
    a = assess(Position(sku_id="S", on_hand=0, allocated=0, on_order=0), rows, DEC, 7, 0, "q50_plus_safety")
    assert a.demand_q50 == 7 * 4.0                             # exactly the 7 days decision+1 .. decision+7


def test_F02_equal_and_shifted_clocks_give_the_same_window():
    equal = assess(Position(sku_id="S", on_hand=5, allocated=0, on_order=0), path(28), DEC, 14, 0, acf=AR,
                   lead_time_days=3)
    shifted = assess(Position(sku_id="S", on_hand=5, allocated=0, on_order=0),
                     path(40, start=DEC - timedelta(days=11)), DEC, 14, 0, acf=AR, lead_time_days=3)
    assert equal.required_units == shifted.required_units and equal.protection_days == 17


def test_F02_a_forecast_with_a_gap_after_the_decision_date_is_rejected():
    with pytest.raises(ValueError, match="not on"):
        assess(Position(sku_id="S", on_hand=0, allocated=0, on_order=0), path(28, start=DEC + timedelta(days=3)),
               DEC, 7, 0, acf=AR)


def test_F02_summed_bases_reject_a_forecast_shorter_than_the_coverage_window():
    with pytest.raises(ValueError, match="cannot extrapolate"):
        assess(Position(sku_id="S", on_hand=0, allocated=0, on_order=0), path(10), DEC, 21, 0, "q90_sum")
    # the lead-time model extrapolates and says how many days it filled in
    a = assess(Position(sku_id="S", on_hand=0, allocated=0, on_order=0), path(10), DEC, 21, 0, acf=AR)
    assert a.extrapolated_days == 11


def test_F02_stockout_projection_stays_inside_the_window():
    a = assess(Position(sku_id="S", on_hand=1000, allocated=0, on_order=0), path(200), DEC, 14, 0, acf=AR)
    assert a.projected_stockout is None                        # 1000 units outlast 14 days of 4/day; no day 250 stockout


# =========================================================================================== F03 controls
def test_F03_safety_days_change_only_the_q50_basis_and_say_so():
    p0 = Position(sku_id="S", on_hand=0, allocated=0, on_order=0)
    lt0, lt9 = (assess(p0, path(), DEC, 14, d, acf=AR) for d in (0, 9))
    assert lt0.required_units == lt9.required_units and not lt0.safety_days_applied
    q0, q9 = (assess(p0, path(), DEC, 14, d, "q50_plus_safety") for d in (0, 9))
    assert q9.required_units - q0.required_units == 36 and q0.safety_days_applied


def test_F03_scenario_input_rejects_a_control_that_does_not_apply():
    with pytest.raises(ValueError, match="safety_days applies only"):
        ScenarioInput(safety_days=7)
    with pytest.raises(ValueError, match="service_level applies only"):
        ScenarioInput(replenishment_basis="q90_sum", service_level=0.95)
    assert ScenarioInput(replenishment_basis="q50_plus_safety", safety_days=7).safety_days == 7


# =========================================================================================== F04 capacity
def test_F04_capacity_below_the_orderable_minimum_is_infeasible_not_accepted():
    req = PlanRequest(decision_date=DEC, need_by=DEC + timedelta(days=14), currency="GBP", budget_minor=10**6,
                      needs=[Need(sku_id="S", required_units=10, capacity_units=10)],
                      offers=[Offer(term_id="T", supplier_id="SUP", sku_id="S", unit_cost_minor=100, currency="GBP",
                                    moq=12, order_multiple=6, lead_time_days=2)])
    r = plan(req)
    assert r.status == "INFEASIBLE" and any("capacity" in e for e in r.explanation)
    short = plan(req.model_copy(update={"allow_shortfall": True}))
    assert short.status == "OPTIMAL" and short.lines == [] and short.shortfall == {"S": 10}


def test_F04_assess_keeps_uncapped_demand_visible_and_reports_headroom():
    a = assess(Position(sku_id="S", on_hand=0, allocated=0, on_order=0, capacity=10), path(), DEC, 14, 0, acf=AR,
               lead_time_days=3)
    assert a.required_units == 10 and a.capacity_headroom_units == 10 and a.uncapped_required_units > 10


@pytest.fixture()
def uci_world(clean_db, tenant_a):
    """UCI workspace with a 140-day history: S1 at one site (capacity 10; MOQ 12 in packs of 6), S2 at two sites."""
    did = uuid.uuid4()
    with tenant_session(tenant_a) as s:
        s.execute(text("INSERT INTO datasets (id, tenant_id, name, source_kind, license, file_name, sha256, bytes, "
                       "schema_version, status) VALUES (:i,:t,'synthetic','generated','n/a','f','h',1,'v','READY')"),
                  {"i": did, "t": tenant_a})
        for sku in ("S1", "S2"):
            s.execute(text("INSERT INTO products (tenant_id, sku_id, source_kind) VALUES (:t,:k,'generated')"),
                      {"t": tenant_a, "k": sku})
        for loc in ("WH", "WH2"):
            s.execute(text("INSERT INTO locations VALUES (:t,:l,:l,'warehouse',true,'synthetic')"), {"t": tenant_a, "l": loc})
        s.execute(text("INSERT INTO inventory_positions VALUES (:t,'WH','Z','S1','2011-05-20',0,0,0,10,'simulated',NULL)"),
                  {"t": tenant_a})
        for loc in ("WH", "WH2"):
            s.execute(text("INSERT INTO inventory_positions VALUES (:t,:l,'Z','S2','2011-05-20',3,0,0,NULL,'simulated',NULL)"),
                      {"t": tenant_a, "l": loc})
        s.execute(text("INSERT INTO suppliers VALUES (:t,'SUP','Supplier','generated','synthetic')"), {"t": tenant_a})
        for sku in ("S1", "S2"):
            s.execute(text("""INSERT INTO supplier_terms (term_id, tenant_id, supplier_id, sku_id, unit_cost_minor, currency,
                moq, order_multiple, lead_time_days, valid_from, known_at, value_kind, source_kind) VALUES (:id,:t,'SUP',:k,
                100,'GBP',12,6,3,'2011-01-01','2011-01-01T00:00:00Z','simulated','generated')"""),
                      {"id": f"T-{sku}", "t": tenant_a, "k": sku})
        s.execute(text("INSERT INTO tenant_settings VALUES (:t,'2011-05-20T12:00:00Z','GBP',:d,NULL,CAST(:p AS jsonb))"),
                  {"t": tenant_a, "d": did, "p": '{"weekly_budget_minor": 100000, "coverage_days": 14}'})
        for i in range(140):
            for sku in ("S1", "S2"):
                s.execute(text("INSERT INTO sales_daily VALUES (:t,:d,:k,'WH',:day,:u)"),
                          {"t": tenant_a, "d": did, "k": sku, "day": date(2011, 1, 1) + timedelta(days=i), "u": (i % 7) + 2})
    return tenant_a


def test_F04_scenario_never_orders_beyond_storage_capacity(uci_world):
    out = run_scenario(who(uci_world, "planner"), ScenarioInput(sku_ids=["S1"]))
    need = out["needs"]["S1"]
    assert need["capacity_headroom_units"] == 10 and need["uncapped_required_units"] > 10
    assert sum(l["quantity"] for l in out["plan"]["lines"] if l["sku_id"] == "S1") <= 10
    assert out["plan"]["shortfall"].get("S1") == 10            # MOQ 12 cannot fit: shortfall is explicit
    assert out["metrics"]["capacity_capped_units"] == need["uncapped_required_units"] - 10


def test_F04_agent_run_reports_capacity_infeasibility_and_prepares_nothing(uci_world):
    run = create_run(who(uci_world, "planner"), mode="draft", inp={"sku_ids": ["S1"], "allow_shortfall": False})
    tick()
    with tenant_session(uci_world) as s:
        r = s.execute(text("SELECT status, state FROM agent_runs WHERE id=:i"), {"i": run}).mappings().first()
        n = s.execute(text("SELECT count(*) FROM actions")).scalar()
    assert r["state"]["plan"]["status"] == "INFEASIBLE" and n == 0
    assert r["state"]["plan"]["request"]["needs"][0]["capacity_units"] == 10


def test_S21_multi_location_sku_is_planned_per_location_with_its_own_demand_share(uci_world):
    with tenant_session(uci_world) as s:       # S2 also sells at WH2, at half the WH rate
        did = s.execute(text("SELECT dataset_id FROM tenant_settings")).scalar()
        for i in range(140):
            s.execute(text("INSERT INTO sales_daily VALUES (:t,:d,'S2','WH2',:day,:u)"),
                      {"t": uci_world, "d": did, "day": date(2011, 1, 1) + timedelta(days=i), "u": ((i % 7) + 2) / 2})
        positions, excluded = load_positions(s, ["S1", "S2"], date(2011, 5, 20))
    assert set(positions) == {"S1", "S2@WH", "S2@WH2"} and not excluded
    assert positions["S2@WH2"]["location_id"] == "WH2" and positions["S2@WH2"]["on_hand"] == 3   # not pooled to 6
    out = run_scenario(who(uci_world, "planner"), ScenarioInput(sku_ids=["S2"], budget_minor=10**8))
    wh, wh2 = out["needs"]["S2@WH"], out["needs"]["S2@WH2"]
    assert wh["demand_share"] > wh2["demand_share"] > 0 and abs(wh["demand_share"] + wh2["demand_share"] - 1) < 1e-9
    assert wh["demand_q50"] > wh2["demand_q50"]
    keys = {l["sku_id"] for l in out["plan"]["lines"]}
    assert keys <= {"S2@WH", "S2@WH2"} and len(out["plan"]["lines"]) == 2     # one line per site, never one pooled line


def test_S21_agent_drafts_carry_locations_and_receipts_need_one(uci_world):
    with tenant_session(uci_world) as s:       # both sites sell S2
        did = s.execute(text("SELECT dataset_id FROM tenant_settings")).scalar()
        for i in range(140):
            s.execute(text("INSERT INTO sales_daily VALUES (:t,:d,'S2','WH2',:day,:u)"),
                      {"t": uci_world, "d": did, "day": date(2011, 1, 1) + timedelta(days=i), "u": (i % 7) + 2})
    run = create_run(who(uci_world, "planner"), mode="draft", inp={"sku_ids": ["S2"], "budget_minor": 10**8})
    tick()
    with tenant_session(uci_world) as s:
        a = s.execute(text("SELECT id, payload, payload_hash, row_version FROM actions WHERE agent_run_id=:r"),
                      {"r": run}).mappings().one()
    locs = sorted(l["location_id"] for l in a["payload"]["lines"])
    assert locs == ["WH", "WH2"] and {l["sku_id"] for l in a["payload"]["lines"]} == {"S2"}
    assert {l["term_id"] for l in a["payload"]["lines"]} == {"T-S2"}         # real term id, not the planning copy
    act.approve(who(uci_world, "approver"), a["id"], payload_hash=a["payload_hash"], expected_row_version=a["row_version"])
    assert act.dispatch_once(uci_world)["result"] == "RECONCILED"
    lines = [x for x in act.open_orders(who(uci_world, "viewer")) if x["action_id"] == a["id"]]
    assert sorted(x["location_id"] for x in lines) == ["WH", "WH2"]
    with pytest.raises(act.ActionError) as e:
        act.record_receipt(who(uci_world, "planner"), a["id"], sku_id="S2", quantity=1, received_on=date(2011, 5, 21), key="r1")
    assert e.value.code == "location_required"
    r = act.record_receipt(who(uci_world, "planner"), a["id"], sku_id="S2", quantity=1, received_on=date(2011, 5, 21),
                           key="r1", location_id="WH2")
    assert r["received_units"] == 1


def test_S21_explicit_scope_over_the_limit_is_rejected():
    with pytest.raises(ValueError, match="at most"):
        create_run(_fake_planner(), mode="draft",
                   inp={"sku_ids": [f"S{i}" for i in range(MAX_SKUS_PER_RUN + 1)]})


def _fake_planner():
    from supplylens.authz import Actor
    return Actor(uuid.uuid4(), uuid.uuid4(), "planner", "p@x")


# =========================================================================================== F08 zero budget
@pytest.fixture()
def demo_tenant(clean_db, tenant_b):
    demo.load(tenant_b)
    return tenant_b


def test_F08_explicit_zero_budget_stays_zero_and_spends_nothing(demo_tenant):
    run = create_run(who(demo_tenant, "planner"), mode="draft", inp={
        "sku_ids": ["DEMO-REF-SKU"], "knowledge_cutoff": CUTOFF.isoformat(), "effective_date": "2026-10-20",
        "currency": "USD", "budget_minor": 0, "allow_shortfall": True})
    tick()
    with tenant_session(demo_tenant) as s:
        st = s.execute(text("SELECT state FROM agent_runs WHERE id=:i"), {"i": run}).scalar()
        spend = s.execute(text("SELECT COALESCE(sum(total_minor), 0) FROM actions")).scalar()
    assert st["settings"]["budget_minor"] == 0 and st["settings"]["budget_source"] == "explicit"
    assert st["plan"]["total_minor"] == 0 and spend == 0


def test_F08_missing_budget_inherits_and_negative_is_rejected(demo_tenant):
    run = create_run(who(demo_tenant, "planner"), mode="observe", inp={"sku_ids": ["DEMO-REF-SKU"]})
    tick()
    with tenant_session(demo_tenant) as s:
        st = s.execute(text("SELECT state FROM agent_runs WHERE id=:i"), {"i": run}).scalar()
    assert st["settings"]["budget_minor"] == 500000 and st["settings"]["budget_source"] == "workspace default"
    with pytest.raises(ValueError, match="negative"):
        create_run(who(demo_tenant, "planner"), mode="draft", inp={"budget_minor": -1})


# =========================================================================================== actions: F05 F06 F07 S11 S12
def prepared(tenant, effective=date(2026, 10, 20)):
    res = applicable_terms(tenant, ["DEMO-REF-SKU"], CUTOFF, effective)
    req = PlanRequest(decision_date=effective, need_by=date(2026, 10, 22), currency="USD", budget_minor=18000,
                      needs=[Need(sku_id="DEMO-REF-SKU", required_units=30)], offers=res.applicable)
    result = plan(req)
    decision = {"knowledge_cutoff": CUTOFF.isoformat(), "effective_date": effective.isoformat(),
                "plan_input_hash": result.input_hash, "budget_minor": 18000}
    return act.prepare(who(tenant, "planner"), supplier_id=result.lines[0].supplier_id, lines=result.lines,
                       currency="USD", need_by=req.need_by, decision=decision, evidence={}, versions={})


def approved(tenant):
    a = prepared(tenant)
    act.approve(who(tenant, "approver"), a["id"], payload_hash=a["payload_hash"], expected_row_version=a["row_version"])
    return a


@pytest.mark.parametrize("fault", ["alter_line_price", "duplicate_line", "change_unit", "change_need_by",
                                   "cancel_after_commit"])
def test_F06_any_difference_in_the_returned_order_blocks_reconciliation(demo_tenant, fault):
    a = approved(demo_tenant)
    sandbox_erp.inject_fault(f"po-{a['id']}", fault)
    r = act.dispatch_once(demo_tenant)
    assert r["result"] == "MISMATCH" and r["mismatches"]
    final = act.get(who(demo_tenant, "viewer"), a["id"])
    assert final["status"] == "CONFIRMED" and "read-back mismatch" in final["status_reason"]
    assert act.open_orders(who(demo_tenant, "viewer")) == []   # a mismatched order is not open supply


def test_F06_same_total_with_a_duplicated_line_is_still_a_mismatch(demo_tenant):
    a = approved(demo_tenant)
    sandbox_erp.inject_fault(f"po-{a['id']}", "duplicate_line")
    r = act.dispatch_once(demo_tenant)
    order = sandbox_erp.lookup(f"po-{a['id']}")
    assert order["total_minor"] == a["total_minor"] and len(order["lines"]) == 2
    assert any("not approved" in m for m in r["mismatches"])


def test_F07_committed_order_is_found_after_the_approval_expired_and_not_sent_again(demo_tenant, monkeypatch):
    a = approved(demo_tenant)
    key = f"po-{a['id']}"
    item = act._claim(demo_tenant, "worker-that-dies")
    sandbox_erp.execute(key, "x", item["payload"])            # external commit, then the worker dies
    with tenant_session(demo_tenant) as s:
        s.execute(text("UPDATE outbox SET lease_expires_at = now() - interval '1 second'"))
        s.execute(text("UPDATE approvals SET expires_at = now() - interval '1 minute'"))

    def no_second_send(*a, **k):
        raise AssertionError("execute called again for a committed order")
    monkeypatch.setattr(sandbox_erp, "execute", no_second_send)
    r = act.dispatch_once(demo_tenant, worker="recovery")
    assert r["result"] == "RECONCILED" and sandbox_erp.count_for_key(key) == 1


def test_S11_revoked_approver_blocks_a_fresh_send(demo_tenant):
    a = approved(demo_tenant)
    with admin_engine().begin() as c:
        c.execute(text("UPDATE memberships SET role='viewer' WHERE tenant_id=:t AND user_id=:u"),
                  {"t": demo_tenant, "u": user_id(dev_email("approver"))})
    try:
        r = act.dispatch_once(demo_tenant)
    finally:
        with admin_engine().begin() as c:
            c.execute(text("UPDATE memberships SET role='approver' WHERE tenant_id=:t AND user_id=:u"),
                      {"t": demo_tenant, "u": user_id(dev_email("approver"))})
    assert r["result"] == "STALE" and "approval rights" in r["reason"]
    assert sandbox_erp.lookup(f"po-{a['id']}") is None


def test_S11_terms_amended_after_approval_route_back_to_review(demo_tenant):
    a = approved(demo_tenant)
    with tenant_session(demo_tenant) as s:
        s.execute(text("""INSERT INTO supplier_terms (term_id, tenant_id, supplier_id, sku_id, unit_cost_minor,
            currency, moq, order_multiple, lead_time_days, valid_from, known_at, value_kind, source_kind,
            supersedes_term_id) VALUES ('REF-B-v2', :t, 'DEMO-REF-B', 'DEMO-REF-SKU', 650, 'USD', 10, 5, 2,
            '2026-10-01', now(), 'synthetic', 'generated', 'REF-B-v1')"""), {"t": demo_tenant})
    r = act.dispatch_once(demo_tenant)
    assert r["result"] == "STALE" and "term changed" in r["reason"]
    assert act.get(who(demo_tenant, "viewer"), a["id"])["status"] == "STALE"
    assert sandbox_erp.lookup(f"po-{a['id']}") is None


def test_S12_reconciled_order_feeds_the_next_plan_and_receipts_move_it_once(demo_tenant):
    eff = date(2026, 10, 20)
    with tenant_session(demo_tenant) as s:
        before, _ = load_positions(s, ["DEMO-REF-SKU"], eff)
    a = approved(demo_tenant)
    assert act.dispatch_once(demo_tenant)["result"] == "RECONCILED"
    with tenant_session(demo_tenant) as s:
        after, _ = load_positions(s, ["DEMO-REF-SKU"], eff)
    assert after["DEMO-REF-SKU"]["on_order"] - before["DEMO-REF-SKU"]["on_order"] == 30
    # replan: the 30 units on order cover the reference need, so nothing new is prepared
    run = create_run(who(demo_tenant, "planner"), mode="draft", inp={
        "sku_ids": ["DEMO-REF-SKU"], "knowledge_cutoff": CUTOFF.isoformat(), "effective_date": eff.isoformat(),
        "currency": "USD", "budget_minor": 18000})
    tick()
    with tenant_session(demo_tenant) as s:
        n = s.execute(text("SELECT count(*) FROM actions WHERE agent_run_id=:r"), {"r": run}).scalar()
    assert n == 0
    planner = who(demo_tenant, "planner")
    r = act.record_receipt(planner, a["id"], sku_id="DEMO-REF-SKU", quantity=10, received_on=eff, key="rcpt-1")
    assert r["status"] == "PARTIAL" and r["open_units"] == 20
    again = act.record_receipt(planner, a["id"], sku_id="DEMO-REF-SKU", quantity=10, received_on=eff, key="rcpt-1")
    assert again["status"] == "DUPLICATE"
    with tenant_session(demo_tenant) as s:
        moved, _ = load_positions(s, ["DEMO-REF-SKU"], eff)
    p0, p1 = after["DEMO-REF-SKU"], moved["DEMO-REF-SKU"]
    assert p1["on_hand"] - p0["on_hand"] == 10 and p0["on_order"] - p1["on_order"] == 10
    with pytest.raises(act.ActionError) as e:
        act.record_receipt(planner, a["id"], sku_id="DEMO-REF-SKU", quantity=21, received_on=eff, key="rcpt-2")
    assert e.value.code == "over_receipt"
    assert act.cancel_open_units(planner, a["id"], sku_id="DEMO-REF-SKU", reason="short-shipped")["released_units"] == 20
    with tenant_session(demo_tenant) as s:
        final, _ = load_positions(s, ["DEMO-REF-SKU"], eff)
    assert final["DEMO-REF-SKU"]["on_order"] == before["DEMO-REF-SKU"]["on_order"]


def test_F05_crash_after_the_approval_commits_replays_instead_of_approving_twice(demo_tenant, monkeypatch):
    a = prepared(demo_tenant)
    real = act.approve

    def approve_then_die(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("process died after commit")
    c = TestClient(app, raise_server_exceptions=False)
    assert c.post("/api/v1/auth/dev-login", json={"email": dev_email("approver")}, headers=H).status_code == 200
    body = {"payload_hash": a["payload_hash"], "expected_row_version": a["row_version"]}
    hdr = {**DEMO, "Idempotency-Key": "approve-intent-1"}
    monkeypatch.setattr(routes_decisions.actions, "approve", approve_then_die)
    assert c.post(f"/api/v1/actions/{a['id']}/approve", json=body, headers=hdr).status_code == 500
    monkeypatch.setattr(routes_decisions.actions, "approve", real)
    r = c.post(f"/api/v1/actions/{a['id']}/approve", json=body, headers=hdr)
    assert r.status_code == 200 and r.json()["idempotent_replay"] is True and r.json()["status"] == "QUEUED"
    with tenant_session(demo_tenant) as s:
        assert s.execute(text("SELECT count(*) FROM approvals")).scalar() == 1
        assert s.execute(text("SELECT count(*) FROM outbox")).scalar() == 1


def test_F05_same_key_with_a_different_payload_is_refused(demo_tenant):
    a = prepared(demo_tenant)
    c = TestClient(app)
    c.post("/api/v1/auth/dev-login", json={"email": dev_email("approver")}, headers=H)
    hdr = {**DEMO, "Idempotency-Key": "approve-intent-2"}
    ok = c.post(f"/api/v1/actions/{a['id']}/approve", headers=hdr,
                json={"payload_hash": a["payload_hash"], "expected_row_version": a["row_version"]})
    assert ok.status_code == 200
    other = c.post(f"/api/v1/actions/{a['id']}/approve", headers=hdr,
                   json={"payload_hash": a["payload_hash"], "expected_row_version": a["row_version"] + 1})
    assert other.status_code == 409 and other.json()["code"] == "idempotency_key_reused"


# =========================================================================================== S10 document ACL
def test_S10_restricted_document_is_withheld_on_every_indirect_path(demo_tenant):
    run = create_run(who(demo_tenant, "planner"), mode="draft", inp={
        "sku_ids": ["DEMO-REF-SKU"], "knowledge_cutoff": CUTOFF.isoformat(), "effective_date": "2026-10-20",
        "currency": "USD", "budget_minor": 18000, "allow_shortfall": False})
    tick()
    with tenant_session(demo_tenant) as s:
        action_id, vid = s.execute(text("""SELECT a.id, a.evidence->'terms'->0->>'document_version_id' FROM actions a
            WHERE a.agent_run_id=:r"""), {"r": run}).one()
        s.execute(text("""UPDATE documents SET allowed_roles = ARRAY['planner','approver']
            WHERE id = (SELECT document_id FROM document_versions WHERE id = :v)"""), {"v": vid})
        s.execute(text("""INSERT INTO clause_labels (tenant_id, version_id, category, char_start, char_end, text, source)
            VALUES (:t, :v, 'Price', 0, 5, 'Price', 'test')"""), {"t": demo_tenant, "v": vid})
    c = TestClient(app)
    c.post("/api/v1/auth/dev-login", json={"email": dev_email("viewer")}, headers=H)
    assert c.get(f"/api/v1/documents/versions/{vid}", headers=DEMO).status_code == 404
    assert c.get(f"/api/v1/documents/versions/{vid}/labels", headers=DEMO).status_code == 404
    detail = c.get(f"/api/v1/actions/{action_id}", headers=DEMO).json()
    term = detail["evidence"]["terms"][0]
    assert term["withheld"] and term["section"] is None and term["unit_cost_minor"] == 600   # value stays visible
    assert term["citation"]["body"] is None and term["citation"]["withheld"]
    run_view = c.get(f"/api/v1/agent-runs/{run}", headers=DEMO).json()
    assert all(t.get("section") is None for t in run_view["terms"]["applicable"] if t.get("document_version_id") == vid)
    events = c.get(f"/api/v1/agent-runs/{run}/events", headers=DEMO).text
    assert "Schedule item DEMO-REF-SKU" not in events
    terms = c.get("/api/v1/terms", params={"sku_id": "DEMO-REF-SKU"}, headers=DEMO).json()
    assert all(h["title"] is None for h in terms["history"] if h["document_version_id"] == vid)
    # the planner (allowed) still sees everything
    c.post("/api/v1/auth/dev-login", json={"email": dev_email("planner")}, headers=H)
    assert c.get(f"/api/v1/documents/versions/{vid}/labels", headers=DEMO).status_code == 200
    assert c.get(f"/api/v1/actions/{action_id}", headers=DEMO).json()["evidence"]["terms"][0]["citation"]["body"]


# =========================================================================================== S14 model resolution
def test_S14_model_resolution_is_scoped_by_dataset_and_status(clean_db, tenant_a):
    from supplylens.forecasting.service import ForecastError, resolve_model
    d1, d2 = uuid.uuid4(), uuid.uuid4()
    with tenant_session(tenant_a) as s:
        for d in (d1, d2):
            s.execute(text("INSERT INTO datasets (id, tenant_id, name, source_kind, license, file_name, sha256, bytes, "
                           "schema_version, status) VALUES (:i,:t,'d','generated','n/a','f',:h,1,'v','READY')"),
                      {"i": d, "t": tenant_a, "h": str(d)})
        rows = [("1.0", "CHAMPION", d1, "2011-01-01"), ("2.0", "RETIRED", d1, "2011-02-01"),
                ("3.0", "CANDIDATE", d2, "2011-03-01")]
        for v, st, d, at in rows:
            s.execute(text("""INSERT INTO model_versions (id, tenant_id, family, version, status, dataset_id, created_at)
                VALUES (:i,:t,'lightgbm_quantile',:v,:s,:d,:at)"""),
                      {"i": uuid.uuid4(), "t": tenant_a, "v": v, "s": st, "d": d, "at": at})
    assert resolve_model(tenant_a, d1, "lightgbm_quantile")["version"] == "1.0"     # newest (2.0) is retired
    assert resolve_model(tenant_a, d1, "lightgbm_quantile", allow_retired=True)["version"] == "1.0"  # champion first
    assert resolve_model(tenant_a, d2, "lightgbm_quantile")["version"] == "3.0"     # other dataset's champion ignored
    assert resolve_model(tenant_a, d2)["family"] == "seasonal_naive"                 # no champion on d2
    assert resolve_model(tenant_a, d1)["version"] == "1.0"
    with pytest.raises(ForecastError):
        resolve_model(tenant_a, d2, "tcn_quantile")


def test_F04_capacity_counts_allocated_stock_and_scheduled_receipts_as_occupied():
    # 100 capacity, 60 on hand of which 50 allocated, 30 arriving: only 10 units of space remain
    a = assess(Position(sku_id="S", on_hand=60, allocated=50, on_order=30, capacity=100), path(), DEC, 14, 0, acf=AR,
               lead_time_days=3)
    assert a.capacity_headroom_units == 10 and a.required_units <= 10 < a.uncapped_required_units


def test_S12_erp_receipt_feed_books_each_receipt_once_and_never_above_open(demo_tenant):
    from supplylens.onboarding import service as onb
    a = approved(demo_tenant)
    assert act.dispatch_once(demo_tenant)["result"] == "RECONCILED"
    po = sandbox_erp.lookup(f"po-{a['id']}")["po_number"]
    admin = who(demo_tenant, "tenant_admin")
    csv_text = ("receipt_id,po_number,sku_id,quantity,received_on\n"
                f"GRN-1,{po},DEMO-REF-SKU,10,2026-10-22\n"
                f"GRN-1,{po},DEMO-REF-SKU,10,2026-10-22\n"          # duplicate id in the same file
                f"GRN-2,{po},DEMO-REF-SKU,25,2026-10-22\n"          # 10 + 25 > 30 ordered
                f"GRN-3,SBX-PO-NOPE,DEMO-REF-SKU,5,2026-10-22\n"    # unknown order
                f"GRN-4,{po},DEMO-REF-SKU,5,2026-10-01\n")          # before the order date
    b = onb.upload(admin, kind="receipts", file_name="grn.csv", data=csv_text.encode(), rights="ERP goods-receipt export")
    v = onb.validate_batch(admin, b["id"], b["mapping"])
    assert (v["rows_valid"], v["rows_quarantined"]) == (1, 4)
    reasons = " | ".join(" ".join(r["errors"]) for r in v["quarantined_sample"])
    assert "duplicate" in reasons and "exceeds" in reasons and "no reconciled" in reasons and "before the order date" in reasons
    onb.publish(admin, b["id"])
    line = [x for x in act.open_orders(who(demo_tenant, "viewer")) if x["action_id"] == a["id"]][0]
    assert (line["received_units"], line["open_units"], line["status"]) == (10, 20, "PARTIAL")
    again = onb.upload(admin, kind="receipts", file_name="grn2.csv", rights="ERP goods-receipt export",
                       data=f"receipt_id,po_number,sku_id,quantity,received_on\nGRN-1,{po},DEMO-REF-SKU,10,2026-10-22\n".encode())
    v2 = onb.validate_batch(admin, again["id"], again["mapping"])
    assert v2["rows_valid"] == 0 and "already booked" in v2["quarantined_sample"][0]["errors"][0]


# =========================================================================================== DEF-10 back-pressure
def test_DEF10_requests_past_capacity_are_refused_at_once_and_recovery_is_immediate(monkeypatch):
    from supplylens.api import admission
    c = TestClient(app)
    c.post("/api/v1/auth/dev-login", json={"email": dev_email("viewer")}, headers=H)
    monkeypatch.setattr(admission.settings, "admission_wait_ms", 50)       # a full class waits briefly, then refuses
    g = admission.gates()
    monkeypatch.setattr(g["retrieval"], "inflight", g["retrieval"].cap)
    r = c.get("/api/v1/evidence/search", params={"q": "minimum order"}, headers=DEMO)
    assert r.status_code == 503 and r.json()["code"] == "overloaded" and r.headers["Retry-After"] == "2"
    assert c.get("/api/v1/overview", headers=DEMO).status_code == 200      # cheap reads still served
    assert c.get("/health").status_code == 200
    monkeypatch.setattr(g["retrieval"], "inflight", 0)
    assert c.get("/api/v1/evidence/search", params={"q": "minimum order"}, headers=DEMO).status_code == 200
    monkeypatch.setattr(g["all"], "inflight", g["all"].cap)
    assert c.get("/api/v1/overview", headers=DEMO).status_code == 503
    assert c.get("/api/v1/me").status_code == 200                           # sign-in state is never shed


# =========================================================================================== S09 profiles (no IdP needed)
def test_S09_production_and_demo_profiles_fail_closed():
    from supplylens.config import Settings
    owner = "postgresql+psycopg://own:s3c@db/sl"
    safe = dict(session_secret="x" * 40, alert_webhook_secret="y" * 40, cookie_secure=True,
                database_url="postgresql+psycopg://supplylens_app:s3cret@db/sl", admin_database_url=None)
    with pytest.raises(ValueError, match="production profile refused"):
        Settings(environment="production", dev_auth=True, **safe)
    with pytest.raises(ValueError, match="OIDC provider"):
        Settings(environment="production", dev_auth=False, **safe)
    demo_ok = Settings(environment="demo", dev_auth=True, **safe)              # public demo keeps the role accounts
    assert demo_ok.dev_login_available
    for bad in ({"cookie_secure": False}, {"session_secret": "dev-only-change-me"},
                {"database_url": "postgresql+psycopg://supplylens_app:supplylens_app_dev@db/sl"},
                {"database_url": owner, "admin_database_url": owner},
                {"admin_database_url": owner}):            # P1-SEC-02: a serving process never holds the owner URL
        with pytest.raises(ValueError, match="demo profile refused"):
            Settings(environment="demo", dev_auth=True, **{**safe, **bad})
    # migrations and maintenance commands may hold the owner URL; the serving process may not
    assert Settings(environment="demo", dev_auth=True, maintenance=True, **{**safe, "admin_database_url": owner})
    with pytest.raises(RuntimeError, match="only for migrations and maintenance"):
        _ = demo_ok.owner_database_url


def test_inline_jobs_complete_a_run_and_a_dispatch_without_a_worker(demo_tenant, monkeypatch):
    """Serverless hosting: with inline_jobs the request that queues work also performs it (no worker process)."""
    from supplylens.config import settings
    monkeypatch.setattr(settings, "inline_jobs", True)
    c = TestClient(app)
    c.post("/api/v1/auth/dev-login", json={"email": dev_email("planner")}, headers=H)
    r = c.post("/api/v1/agent-runs", headers={**DEMO, "Idempotency-Key": uuid.uuid4().hex}, json={
        "mode": "draft", "sku_ids": ["DEMO-REF-SKU"], "knowledge_cutoff": CUTOFF.isoformat(), "effective_date": "2026-10-20",
        "budget_minor": 18000, "currency": "USD", "allow_shortfall": False})
    d = c.get(f"/api/v1/agent-runs/{r.json()['run_id']}", headers=DEMO).json()
    assert d["status"] == "WAITING_FOR_APPROVAL" and len(d["actions"]) == 1             # done before the reply
    action = c.get(f"/api/v1/actions/{d['actions'][0]['id']}", headers=DEMO).json()
    c.post("/api/v1/auth/dev-login", json={"email": dev_email("approver")}, headers=H)
    ok = c.post(f"/api/v1/actions/{action['id']}/approve", headers={**DEMO, "Idempotency-Key": uuid.uuid4().hex},
                json={"payload_hash": action["payload_hash"], "expected_row_version": action["row_version"]})
    assert ok.status_code == 200
    assert c.get(f"/api/v1/actions/{action['id']}", headers=DEMO).json()["status"] == "RECONCILED"
