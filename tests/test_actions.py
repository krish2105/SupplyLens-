"""Approval binding, idempotent dispatch, unknown outcomes and reconciliation (BUS-005..007, EXE-007..009)."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from supplylens.actions import service as act
from supplylens.authz import Forbidden, resolve_actor
from supplylens.db import tenant_session
from supplylens.integrations import sandbox_erp
from supplylens.seed import dev_email, user_id
from supplylens.simulation import demo
from supplylens.planning.terms_service import applicable_terms
from supplylens_opt.planner import Need, PlanRequest, plan

CUTOFF = datetime(2026, 10, 20, 9, tzinfo=timezone.utc)


@pytest.fixture()
def demo_tenant(clean_db, tenant_b):
    demo.load(tenant_b)
    return tenant_b


def actor(tenant, role):
    return resolve_actor(user_id(dev_email(role)), tenant)


def approver2(tenant):
    return resolve_actor(user_id("approver2@dev.supplylens.local"), tenant)


def prepared(tenant, budget=18000, effective=date(2026, 10, 20)):
    res = applicable_terms(tenant, ["DEMO-REF-SKU"], CUTOFF, effective)
    req = PlanRequest(decision_date=effective, need_by=date(2026, 10, 22), currency="USD", budget_minor=budget,
                      needs=[Need(sku_id="DEMO-REF-SKU", required_units=30)], offers=res.applicable)
    result = plan(req)
    assert result.status == "OPTIMAL"
    decision = {"knowledge_cutoff": CUTOFF.isoformat(), "effective_date": effective.isoformat(),
                "plan_input_hash": result.input_hash}
    return act.prepare(actor(tenant, "planner"), supplier_id=result.lines[0].supplier_id, lines=result.lines,
                       currency="USD", need_by=req.need_by, decision=decision,
                       evidence={"terms": [l.term_id for l in result.lines]}, versions={"plan": result.input_hash})


def approve(tenant, a, who="approver"):
    return act.approve(actor(tenant, who), a["id"], payload_hash=a["payload_hash"],
                       expected_row_version=a["row_version"])


def test_reference_case_prepares_supplier_b_after_amendment(demo_tenant):
    a = prepared(demo_tenant)
    assert a["payload"]["supplier_id"] == "DEMO-REF-B"
    assert a["total_minor"] == 18000 and a["status"] == "PENDING_APPROVAL"


def test_role_matrix_and_separation_of_duties(demo_tenant):
    a = prepared(demo_tenant)
    with pytest.raises(Forbidden):
        approve(demo_tenant, a, who="viewer")
    with pytest.raises(Forbidden):
        approve(demo_tenant, a, who="tenant_admin")
    with pytest.raises(Forbidden):
        act.prepare(actor(demo_tenant, "approver"), supplier_id="x", lines=[], currency="USD",
                    need_by=date(2026, 10, 22), decision={}, evidence={}, versions={})


def test_preparer_cannot_self_approve(demo_tenant):
    # Give the planner's own user an approver-equivalent attempt by preparing as approver2? Instead:
    a = prepared(demo_tenant)
    planner = actor(demo_tenant, "planner")
    fake = type(planner)(planner.user_id, planner.tenant_id, "approver", planner.email)
    with pytest.raises(act.ActionError) as e:
        act.approve(fake, a["id"], payload_hash=a["payload_hash"], expected_row_version=a["row_version"])
    assert e.value.code == "separation_of_duties"


def test_stale_payload_hash_and_version_rejected(demo_tenant):
    a = prepared(demo_tenant)
    with pytest.raises(act.ActionError) as e:
        act.approve(actor(demo_tenant, "approver"), a["id"], payload_hash="0" * 64,
                    expected_row_version=a["row_version"])
    assert e.value.code == "payload_mismatch"
    with pytest.raises(act.ActionError) as e:
        act.approve(actor(demo_tenant, "approver"), a["id"], payload_hash=a["payload_hash"],
                    expected_row_version=a["row_version"] + 5)
    assert e.value.code == "version_conflict"


def test_edit_invalidates_old_approval_and_revalidates(demo_tenant):
    a = prepared(demo_tenant)
    with pytest.raises(act.ActionError) as e:   # 33 is not a multiple of 5
        act.edit_quantities(actor(demo_tenant, "planner"), a["id"], quantities={"DEMO-REF-SKU": 33},
                            expected_row_version=a["row_version"], budget_minor=18000)
    assert e.value.code == "validation_failed"
    edited = act.edit_quantities(actor(demo_tenant, "planner"), a["id"], quantities={"DEMO-REF-SKU": 25},
                                 expected_row_version=a["row_version"], budget_minor=18000)
    assert edited["payload_hash"] != a["payload_hash"] and edited["total_minor"] == 15000
    with pytest.raises(act.ActionError) as e:   # approval for the old payload is refused
        act.approve(actor(demo_tenant, "approver"), a["id"], payload_hash=a["payload_hash"],
                    expected_row_version=edited["row_version"])
    assert e.value.code == "payload_mismatch"


def test_happy_path_dispatch_reconciles_exactly_one_order(demo_tenant):
    a = prepared(demo_tenant)
    assert approve(demo_tenant, a)["status"] == "QUEUED"
    r = act.dispatch_once(demo_tenant)
    assert r["result"] == "RECONCILED"
    assert act.dispatch_once(demo_tenant) is None
    final = act.get(actor(demo_tenant, "viewer"), a["id"])
    assert final["status"] == "RECONCILED" and final["external_ref"].startswith("SBX-PO-")
    assert sandbox_erp.count_for_key(f"po-{a['id']}") == 1
    order = sandbox_erp.lookup(f"po-{a['id']}")
    assert order["supplier_id"] == "DEMO-REF-B" and order["lines"][0]["quantity"] == 30


def test_double_approval_creates_one_outbox_entry(demo_tenant):
    a = prepared(demo_tenant)
    approve(demo_tenant, a)
    with pytest.raises(act.ActionError):
        approve(demo_tenant, a, who="approver")
    with tenant_session(demo_tenant) as s:
        assert s.execute(text("SELECT count(*) FROM outbox")).scalar() == 1


def test_duplicate_delivery_is_deduplicated_by_sandbox(demo_tenant):
    a = prepared(demo_tenant)
    approve(demo_tenant, a)
    key = f"po-{a['id']}"
    first = sandbox_erp.execute(key, "x", {**a["payload"]})
    second = sandbox_erp.execute(key, "x", {**a["payload"]})
    assert first["po_number"] == second["po_number"] and second["duplicate"]
    assert act.dispatch_once(demo_tenant)["result"] == "RECONCILED"
    assert sandbox_erp.count_for_key(key) == 1


def test_timeout_after_success_goes_unknown_then_reconciles_without_resend(demo_tenant):
    a = prepared(demo_tenant)
    approve(demo_tenant, a)
    key = f"po-{a['id']}"
    sandbox_erp.inject_fault(key, "timeout_after_commit")
    assert act.dispatch_once(demo_tenant)["result"] == "UNKNOWN_OUTCOME"
    assert act.get(actor(demo_tenant, "viewer"), a["id"])["status"] == "UNKNOWN_OUTCOME"
    assert act.dispatch_once(demo_tenant) is None          # the dispatcher does not blindly resend
    r = act.reconcile(actor(demo_tenant, "approver"), a["id"])
    assert r["result"] == "RECONCILED"
    assert sandbox_erp.count_for_key(key) == 1


def test_failure_before_commit_retries_with_backoff(demo_tenant):
    a = prepared(demo_tenant)
    approve(demo_tenant, a)
    sandbox_erp.inject_fault(f"po-{a['id']}", "fail_before_commit")
    r = act.dispatch_once(demo_tenant)
    assert r["result"] == "RETRY"
    with tenant_session(demo_tenant) as s:
        s.execute(text("UPDATE outbox SET next_attempt_at = now()"))
    assert act.dispatch_once(demo_tenant)["result"] == "RECONCILED"
    assert sandbox_erp.count_for_key(f"po-{a['id']}") == 1


def test_expired_lease_after_submit_is_looked_up_not_resent(demo_tenant):
    a = prepared(demo_tenant)
    approve(demo_tenant, a)
    key = f"po-{a['id']}"
    item = act._claim(demo_tenant, "worker-that-dies")
    sandbox_erp.execute(key, "x", item["payload"])           # worker sent, then crashed
    with tenant_session(demo_tenant) as s:
        s.execute(text("UPDATE outbox SET lease_expires_at = now() - interval '1 second'"))
    r = act.dispatch_once(demo_tenant, worker="recovery")
    assert r["result"] == "RECONCILED"
    assert sandbox_erp.count_for_key(key) == 1
    # The dead worker's late write is rejected by the fencing token.
    assert act._finish(demo_tenant, item, "FAILED", "FAILED", error="late") is False


def test_expired_approval_blocks_dispatch(demo_tenant):
    a = prepared(demo_tenant)
    approve(demo_tenant, a)
    with tenant_session(demo_tenant) as s:
        s.execute(text("UPDATE approvals SET expires_at = now() - interval '1 minute'"))
    r = act.dispatch_once(demo_tenant)
    assert r["result"] == "STALE" and "expired" in r["reason"]
    assert sandbox_erp.lookup(f"po-{a['id']}") is None


def test_changed_terms_make_approval_stale(demo_tenant):
    a = prepared(demo_tenant)
    with tenant_session(demo_tenant) as s:   # a new price for B becomes known and effective
        s.execute(text("""INSERT INTO supplier_terms (term_id, tenant_id, supplier_id, sku_id, unit_cost_minor,
            currency, moq, order_multiple, lead_time_days, valid_from, known_at, value_kind, source_kind,
            supersedes_term_id) VALUES ('REF-B-v2', :t, 'DEMO-REF-B', 'DEMO-REF-SKU', 650, 'USD', 10, 5, 2,
            '2026-10-01', now(), 'synthetic', 'generated', 'REF-B-v1')"""), {"t": demo_tenant})
    r = approve(demo_tenant, a)
    assert r["status"] == "STALE"
    assert act.get(actor(demo_tenant, "viewer"), a["id"])["status"] == "STALE"
    with tenant_session(demo_tenant) as s:
        assert s.execute(text("SELECT count(*) FROM outbox")).scalar() == 0


def test_cross_tenant_action_is_invisible(demo_tenant, tenant_a):
    a = prepared(demo_tenant)
    with pytest.raises(act.ActionError) as e:
        act.get(actor(tenant_a, "viewer"), a["id"])
    assert e.value.code == "not_found"
