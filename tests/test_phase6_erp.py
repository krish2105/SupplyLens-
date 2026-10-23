"""Phase 6: ERP adapter contract, connector failures, order/receipt synchronisation and operational reports.

Part 1 is the adapter conformance suite: every registered adapter must pass it. The sandbox supplies its own test
harness (connector switches, warehouse receipts); a real adapter needs an equivalent harness against a vendor sandbox
tenant before it can be registered (docs/operations/erp-integration.md). Part 2 exercises the dispatcher and the
synchronisation against realistic failures. Everything runs against the local simulator: no real ERP is involved.
"""
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_actions import actor, approve, prepared

from supplylens import operations
from supplylens.actions import service as act
from supplylens.api.app import app
from supplylens.db import admin_engine, tenant_session
from supplylens.integrations import connector, registry, sandbox_erp, schema, sync
from supplylens.integrations.contract import (
    AdapterAuthError,
    AdapterRejected,
    AdapterTimeout,
    AdapterUnavailable,
    ErpAdapter,
)
from supplylens.seed import dev_email
from supplylens.simulation import demo
from supplylens_worker import main as worker

PAYLOAD = {"supplier_id": "SUP-X", "currency": "USD", "need_by": "2026-10-22", "total_minor": 1200,
           "lines": [{"sku_id": "SKU-1", "quantity": 10, "unit": "unit", "unit_cost_minor": 120, "line_minor": 1200,
                      "term_id": "T1"}]}


class SandboxHarness:
    """What the conformance suite needs from a test environment of the target system."""
    def outage(self, on: bool):
        sandbox_erp.set_connector(available=not on)

    def credentials(self, valid: bool):
        sandbox_erp.set_connector(credentials_valid=valid)

    def reject_next(self, key: str):
        sandbox_erp.inject_fault(key, "reject")

    def timeout_after_commit(self, key: str):
        sandbox_erp.inject_fault(key, "timeout_after_commit")

    def receive(self, po: str, sku: str, qty: int, on: date):
        return sandbox_erp.post_receipt(po, sku, qty, on)


HARNESSES = {"sandbox_erp": SandboxHarness()}


@pytest.fixture(params=sorted(registry.REGISTERED))
def target(request, clean_db):
    return registry.REGISTERED[request.param], HARNESSES[request.param]


def key() -> str:
    return f"conf-{uuid.uuid4().hex}"


# ------------------------------------------------------------------------------------------------ 1. conformance
def test_contract_adapter_shape_and_capabilities(target):
    erp, _ = target
    assert isinstance(erp, ErpAdapter)
    caps = erp.capabilities()
    assert {"adapter", "status", "operations", "idempotency", "note"} <= set(caps)
    assert caps["status"] in ("VERIFIED_LOCALLY", "QUALIFIED") and erp.health()["adapter"] == erp.name


def test_contract_submission_is_idempotent_and_read_back_is_complete(target):
    erp, _ = target
    k = key()
    first = erp.submit_purchase_order(k, "ref-1", PAYLOAD)
    second = erp.submit_purchase_order(k, "ref-1", PAYLOAD)
    assert first["po_number"] == second["po_number"] and second["duplicate"] and not first["duplicate"]
    o = erp.lookup_purchase_order(k)
    assert o["po_number"] == first["po_number"] and o["supplier_id"] == "SUP-X" and o["total_minor"] == 1200
    assert o["currency"].strip() == "USD" and str(o["need_by"]) == "2026-10-22" and o["status"] in ("OPEN", "CONFIRMED")
    assert [(l["sku_id"], l["quantity"], l["unit_cost_minor"]) for l in o["lines"]] == [("SKU-1", 10, 120)]
    assert [x["po_number"] for x in erp.orders_for(["ref-1"])] == [first["po_number"]]
    assert erp.lookup_purchase_order(key()) is None


def test_contract_failures_are_classified_and_create_nothing(target):
    erp, h = target
    k = key()
    h.outage(True)
    with pytest.raises(AdapterUnavailable):
        erp.submit_purchase_order(k, "ref-o", PAYLOAD)
    with pytest.raises(AdapterUnavailable):
        erp.lookup_purchase_order(k)
    h.outage(False)
    h.credentials(False)
    with pytest.raises(AdapterAuthError):
        erp.submit_purchase_order(k, "ref-o", PAYLOAD)
    with pytest.raises(AdapterAuthError):
        erp.health()
    h.credentials(True)
    h.reject_next(k)
    with pytest.raises(AdapterRejected) as e:
        erp.submit_purchase_order(k, "ref-o", PAYLOAD)
    assert e.value.retryable is False
    assert erp.lookup_purchase_order(k) is None and erp.orders_for(["ref-o"]) == []


def test_contract_timeout_may_have_applied_and_lookup_tells(target):
    erp, h = target
    k = key()
    h.timeout_after_commit(k)
    with pytest.raises(AdapterTimeout):
        erp.submit_purchase_order(k, "ref-t", PAYLOAD)
    assert erp.lookup_purchase_order(k) is not None                 # it did apply: look up, never resend blindly
    assert erp.submit_purchase_order(k, "ref-t", PAYLOAD)["duplicate"]


def test_contract_receipt_feed_is_ordered_and_resumable(target):
    erp, h = target
    k = key()
    po = erp.submit_purchase_order(k, "ref-r", PAYLOAD)["po_number"]
    a = h.receive(po, "SKU-1", 4, date(2026, 10, 21))
    b = h.receive(po, "SKU-1", 6, date(2026, 10, 22))
    feed = erp.receipts_since(["ref-r"], 0)
    assert [r["receipt_id"] for r in feed] == [a["receipt_id"], b["receipt_id"]]
    assert feed[0]["sequence"] < feed[1]["sequence"] and feed[0]["caller_ref"] == "ref-r" and feed[0]["quantity"] == 4
    assert [r["receipt_id"] for r in erp.receipts_since(["ref-r"], feed[0]["sequence"])] == [b["receipt_id"]]
    assert erp.receipts_since(["someone-else"], 0) == []
    # fully received: the target refuses to cancel
    with pytest.raises(AdapterRejected):
        erp.cancel_purchase_order(k, "too late")


def test_contract_cancellation_is_idempotent(target):
    erp, _ = target
    k = key()
    erp.submit_purchase_order(k, "ref-c", PAYLOAD)
    assert erp.cancel_purchase_order(k, "not needed")["status"] == "CANCELLED"
    assert erp.cancel_purchase_order(k, "not needed")["duplicate"]
    assert erp.lookup_purchase_order(k)["status"] == "CANCELLED"


def test_unregistered_adapter_refuses_instead_of_guessing(monkeypatch):
    monkeypatch.setattr(registry.settings, "erp_adapter", "acme_erp")
    with pytest.raises(registry.UnregisteredAdapter):
        registry.adapter()


# ------------------------------------------------------------------------------------------------ 2. dispatcher
@pytest.fixture()
def demo_tenant(clean_db, tenant_b):
    demo.load(tenant_b)
    return tenant_b


def queued(tenant):
    a = prepared(tenant)
    assert approve(tenant, a)["status"] == "QUEUED"
    return a


def outbox(tenant, aid):
    with tenant_session(tenant) as s:
        return s.execute(text("SELECT status, attempts, failure_kind, last_error FROM outbox WHERE action_id=:a"),
                         {"a": aid}).mappings().first()


def alert(tenant, k):
    with tenant_session(tenant) as s:
        return s.execute(text("SELECT status, severity, detail FROM alerts WHERE dedupe_key=:k"), {"k": k}).mappings().first()


def ready(tenant):
    with tenant_session(tenant) as s:
        s.execute(text("UPDATE outbox SET next_attempt_at = now() WHERE status = 'PENDING'"))


def due(tenant):
    with tenant_session(tenant) as s:
        s.execute(text("UPDATE outbox SET next_attempt_at = now() WHERE status = 'PENDING'"))
        s.execute(text("UPDATE erp_connector_state SET paused_until = now() - interval '1 second' "
                       "WHERE paused_until IS NOT NULL"))


def test_an_outage_pauses_dispatch_without_spending_retries_then_recovers_with_one_order(demo_tenant):
    t, a = demo_tenant, queued(demo_tenant)
    sandbox_erp.set_connector(available=False)
    for _ in range(3):
        assert act.dispatch_once(t)["result"] == "PAUSED"
        ready(t)
    st = connector.state(t)
    assert st["status"] == "UNAVAILABLE" and st["consecutive_failures"] == 3 and st["paused_until"] is not None
    assert outbox(t, a["id"])["attempts"] == 0                       # before Phase 6 the third failure was attempt 3 of 5
    assert act.get(actor(t, "viewer"), a["id"])["status"] == "QUEUED"
    assert alert(t, connector.ALERT_UNAVAILABLE)["status"] == "OPEN"
    with tenant_session(t) as s:                                     # cool-down still running: nothing is claimed
        s.execute(text("UPDATE outbox SET next_attempt_at = now()"))
    assert act.dispatch_once(t) is None
    for _ in range(20):                                              # a long outage: still no attempt spent, no FAILED
        due(t)
        assert act.dispatch_once(t)["result"] == "PAUSED"
    assert outbox(t, a["id"])["attempts"] == 0
    sandbox_erp.set_connector(available=True)
    due(t)
    assert act.dispatch_once(t)["result"] == "RECONCILED"
    assert sandbox_erp.count_for_key(f"po-{a['id']}") == 1
    assert connector.state(t)["status"] == "OK" and alert(t, connector.ALERT_UNAVAILABLE)["status"] == "RESOLVED"


def test_expired_credentials_stop_dispatch_until_a_health_check_succeeds(demo_tenant):
    t, a = demo_tenant, queued(demo_tenant)
    sandbox_erp.set_connector(credentials_valid=False)
    assert act.dispatch_once(t)["result"] == "PAUSED"
    assert connector.state(t)["status"] == "CREDENTIALS_INVALID"
    assert alert(t, connector.ALERT_CREDENTIALS)["severity"] == "high"
    due(t)
    assert act.dispatch_once(t) is None                              # no retries against bad credentials
    assert connector.probe(t, force=True)["status"] == "CREDENTIALS_INVALID"
    sandbox_erp.set_connector(credentials_valid=True)                # an operator renews the credentials
    assert connector.probe(t, force=True) == {"status": "OK", "checked": True, "adapter": "sandbox_erp",
                                               "qualification": "VERIFIED_LOCALLY"}
    due(t)
    assert act.dispatch_once(t)["result"] == "RECONCILED" and sandbox_erp.count_for_key(f"po-{a['id']}") == 1
    assert alert(t, connector.ALERT_CREDENTIALS)["status"] == "RESOLVED"


def test_a_business_rejection_fails_at_once_and_is_never_retried(demo_tenant):
    t, a = demo_tenant, queued(demo_tenant)
    sandbox_erp.inject_fault(f"po-{a['id']}", "reject")
    r = act.dispatch_once(t)
    assert r["result"] == "REJECTED" and "supplier blocked" in r["reason"]
    ob = outbox(t, a["id"])
    assert ob["status"] == "FAILED" and ob["failure_kind"] == "rejected" and ob["attempts"] == 1
    assert act.get(actor(t, "viewer"), a["id"])["status"] == "FAILED"
    assert sandbox_erp.count_for_key(f"po-{a['id']}") == 0
    with pytest.raises(act.ActionError) as e:
        act.retry_failed(actor(t, "approver"), a["id"])
    assert e.value.code == "rejected_by_target"


def test_unknown_outcome_cannot_be_reconciled_during_an_outage_and_is_after_it(demo_tenant):
    t, a = demo_tenant, queued(demo_tenant)
    sandbox_erp.inject_fault(f"po-{a['id']}", "timeout_after_commit")
    assert act.dispatch_once(t)["result"] == "UNKNOWN_OUTCOME"
    sandbox_erp.set_connector(available=False)
    with pytest.raises(act.ActionError) as e:
        act.reconcile(actor(t, "approver"), a["id"])
    assert e.value.code == "erp_unavailable" and e.value.http == 503
    assert outbox(t, a["id"])["status"] == "UNKNOWN_OUTCOME"         # nothing guessed
    sandbox_erp.set_connector(available=True)
    assert act.reconcile(actor(t, "approver"), a["id"])["result"] == "RECONCILED"
    assert sandbox_erp.count_for_key(f"po-{a['id']}") == 1


def test_worker_crash_after_submit_then_outage_still_looks_up_first(demo_tenant):
    t, a = demo_tenant, queued(demo_tenant)
    k = f"po-{a['id']}"
    item = act._claim(t, "worker-that-dies")
    sandbox_erp.execute(k, str(a["id"]), item["payload"])          # sent, then the worker crashed
    with tenant_session(t) as s:
        s.execute(text("UPDATE outbox SET lease_expires_at = now() - interval '1 second'"))
    sandbox_erp.set_connector(available=False)
    assert act.dispatch_once(t, worker="recovery")["result"] == "PAUSED"
    assert outbox(t, a["id"])["attempts"] == 1                      # > 0: the next claim is attempt 2, lookup first
    sandbox_erp.set_connector(available=True)
    due(t)
    assert act.dispatch_once(t, worker="recovery")["result"] == "RECONCILED"
    assert sandbox_erp.count_for_key(k) == 1


def test_old_schema_keeps_the_previous_behaviour(demo_tenant, monkeypatch):
    """The hosted database is migrated after the deploy (PD-009): new code must dispatch on schema 0010."""
    monkeypatch.setattr(schema, "has_0011", lambda: False)
    t, a = demo_tenant, queued(demo_tenant)
    assert connector.may_dispatch(t) == (True, None) and connector.state(t) is None
    assert act.dispatch_once(t)["result"] == "RECONCILED" and sandbox_erp.count_for_key(f"po-{a['id']}") == 1
    assert sync.sync_tenant(t) == {"skipped": "database not migrated to 0011"}


# ------------------------------------------------------------------------------------------------ 3. cancellation
def reconciled(tenant):
    a = queued(tenant)
    assert act.dispatch_once(tenant)["result"] == "RECONCILED"
    return act.get(actor(tenant, "viewer"), a["id"])


def ledger(tenant, aid):
    with tenant_session(tenant) as s:
        return s.execute(text("SELECT ordered_units, received_units, cancelled_units, status FROM purchase_order_lines "
                              "WHERE action_id=:a"), {"a": aid}).mappings().first()


def test_cancelling_a_placed_order_needs_approval_rights_and_releases_open_units(demo_tenant):
    t = demo_tenant
    a = reconciled(t)
    with pytest.raises(Exception, match="action.approve"):
        act.cancel_order(actor(t, "planner"), a["id"], reason="no longer needed")
    r = act.cancel_order(actor(t, "approver"), a["id"], reason="no longer needed")
    assert r["status"] == "CANCELLED" and r["released_units"] == 30
    assert sandbox_erp.lookup(a["outbox"]["operation_id"])["status"] == "CANCELLED"
    assert dict(ledger(t, a["id"])) == {"ordered_units": 30, "received_units": 0, "cancelled_units": 30, "status": "CANCELLED"}
    with pytest.raises(act.ActionError) as e:
        act.cancel_order(actor(t, "approver"), a["id"], reason="again")
    assert e.value.code == "invalid_state"


def test_the_target_refusing_a_cancellation_changes_nothing_here(demo_tenant):
    t = demo_tenant
    a = reconciled(t)
    sandbox_erp.post_receipt(a["external_ref"], "DEMO-REF-SKU", 30, date(2026, 10, 21))  # all received in the ERP
    with pytest.raises(act.ActionError) as e:
        act.cancel_order(actor(t, "approver"), a["id"], reason="too late")
    assert e.value.code == "cancel_refused"
    assert ledger(t, a["id"])["cancelled_units"] == 0


def test_cancel_order_route_is_idempotent(demo_tenant):
    t = demo_tenant
    a = reconciled(t)
    c = TestClient(app)
    h = {"X-Requested-With": "supplylens", "X-SupplyLens-Tenant": "demo", "Idempotency-Key": "cancel-1"}
    c.post("/api/v1/auth/dev-login", json={"email": dev_email("approver")}, headers=h)
    r1 = c.post(f"/api/v1/actions/{a['id']}/cancel-order", json={"reason": "duplicate request test"}, headers=h)
    r2 = c.post(f"/api/v1/actions/{a['id']}/cancel-order", json={"reason": "duplicate request test"}, headers=h)
    assert r1.status_code == r2.status_code == 200 and r2.json().pop("idempotent_replay") is True
    assert {k: v for k, v in r2.json().items() if k != "idempotent_replay"} == r1.json()
    with tenant_session(t) as s:
        assert s.execute(text("SELECT count(*) FROM audit_events WHERE action='order.cancelled_in_erp'")).scalar() == 1


# ------------------------------------------------------------------------------------------------ 4. synchronisation
def test_partial_receipts_sync_once_and_complete_the_line(demo_tenant):
    t = demo_tenant
    a = reconciled(t)
    sandbox_erp.post_receipt(a["external_ref"], "DEMO-REF-SKU", 12, date(2026, 10, 21))
    r = sync.sync_tenant(t)
    assert r["receipts_booked"] == 1 and dict(ledger(t, a["id"]))["status"] == "PARTIAL"
    assert ledger(t, a["id"])["received_units"] == 12
    assert sync.sync_tenant(t)["receipts_booked"] == 0              # the feed resumes from its cursor
    with tenant_session(t) as s:                                    # a lost cursor re-reads the feed: no double booking
        s.execute(text("UPDATE erp_connector_state SET receipts_cursor = 0"))
    assert sync.sync_tenant(t)["receipts_booked"] == 0 and ledger(t, a["id"])["received_units"] == 12
    sandbox_erp.post_receipt(a["external_ref"], "DEMO-REF-SKU", 18, date(2026, 10, 22))
    sync.sync_tenant(t)
    assert dict(ledger(t, a["id"])) == {"ordered_units": 30, "received_units": 30, "cancelled_units": 0, "status": "RECEIVED"}
    with tenant_session(t) as s:
        sources = s.execute(text("SELECT detail->>'source' FROM audit_events WHERE action='order.received'")).scalars().all()
    assert sources == ["erp", "erp"]


def test_an_over_delivery_in_the_erp_becomes_an_exception_not_a_booking(demo_tenant):
    t = demo_tenant
    a = reconciled(t)
    rid = sandbox_erp.post_receipt(a["external_ref"], "DEMO-REF-SKU", 35, date(2026, 10, 21))["receipt_id"]
    r = sync.sync_tenant(t)
    assert r["receipt_exceptions"] == 1 and ledger(t, a["id"])["received_units"] == 0
    al = alert(t, f"erp_sync:receipt:{rid}")
    assert al["severity"] == "high" and al["detail"]["code"] == "over_receipt"


def test_a_receipt_before_local_reconciliation_waits_and_is_booked_after(demo_tenant):
    t, a = demo_tenant, queued(demo_tenant)
    sandbox_erp.inject_fault(f"po-{a['id']}", "timeout_after_commit")
    assert act.dispatch_once(t)["result"] == "UNKNOWN_OUTCOME"
    po = sandbox_erp.lookup(f"po-{a['id']}")["po_number"]
    sandbox_erp.post_receipt(po, "DEMO-REF-SKU", 10, date(2026, 10, 21))
    r = sync.sync_tenant(t)
    assert r["receipts_held"] == 1 and r["receipt_exceptions"] == 0
    act.reconcile(actor(t, "approver"), a["id"])
    assert sync.sync_tenant(t)["receipts_booked"] == 1 and ledger(t, a["id"])["received_units"] == 10


def test_a_supplier_cancellation_in_the_erp_releases_supply_and_alerts(demo_tenant):
    t = demo_tenant
    a = reconciled(t)
    sandbox_erp.post_receipt(a["external_ref"], "DEMO-REF-SKU", 10, date(2026, 10, 21))
    sync.sync_tenant(t)
    sandbox_erp.cancel_by_supplier(a["external_ref"], "out of stock")
    r = sync.sync_tenant(t)
    assert r["released_units"] == 20
    assert dict(ledger(t, a["id"])) == {"ordered_units": 30, "received_units": 10, "cancelled_units": 20, "status": "RECEIVED"}
    assert alert(t, f"erp_sync:closed:{a['id']}")["severity"] == "high"
    assert sync.sync_tenant(t)["released_units"] == 0


def test_an_order_the_erp_holds_but_supplylens_records_as_failed_is_drift(demo_tenant):
    t, a = demo_tenant, queued(demo_tenant)
    sandbox_erp.inject_fault(f"po-{a['id']}", "timeout_after_commit")
    act.dispatch_once(t)
    with tenant_session(t) as s:                                     # a person wrongly marks it failed
        s.execute(text("UPDATE actions SET status='FAILED' WHERE id=:a"), {"a": a["id"]})
        s.execute(text("UPDATE outbox SET status='FAILED' WHERE action_id=:a"), {"a": a["id"]})
    assert sync.sync_tenant(t)["drift"] == 1
    assert alert(t, f"erp_sync:drift:{a['id']}")["detail"]["local_status"] == "FAILED"
    sandbox_erp.cancel_by_supplier(sandbox_erp.lookup(f"po-{a['id']}")["po_number"])
    sync.sync_tenant(t)
    assert alert(t, f"erp_sync:drift:{a['id']}")["status"] == "RESOLVED"


def test_a_delayed_receipt_raises_an_overdue_alert_that_clears_on_receipt(demo_tenant):
    t = demo_tenant
    a = reconciled(t)                                                # expected 2026-10-22
    with tenant_session(t) as s:
        s.execute(text("UPDATE tenant_settings SET operational_as_of = '2026-10-23T12:00:00Z'"))
    assert sync.overdue(t) == 0                                      # within the 2-day grace
    with tenant_session(t) as s:
        s.execute(text("UPDATE tenant_settings SET operational_as_of = '2026-10-27T12:00:00Z'"))
    assert sync.overdue(t) == 1
    assert alert(t, f"overdue_receipt:{a['id']}")["detail"]["days_overdue"] == 5
    assert operations.reconciliation(t)["ledger"]["overdue_lines"] == 1
    sandbox_erp.post_receipt(a["external_ref"], "DEMO-REF-SKU", 30, date(2026, 10, 26))
    sync.sync_tenant(t)
    assert alert(t, f"overdue_receipt:{a['id']}")["status"] == "RESOLVED"


def test_sync_during_an_outage_changes_nothing_and_counts_as_a_failure(demo_tenant):
    t = demo_tenant
    a = reconciled(t)
    sandbox_erp.post_receipt(a["external_ref"], "DEMO-REF-SKU", 5, date(2026, 10, 21))
    sandbox_erp.set_connector(available=False)
    assert "error" in sync.sync_tenant(t)
    assert ledger(t, a["id"])["received_units"] == 0 and connector.state(t)["consecutive_failures"] == 1


# ------------------------------------------------------------------------------------------------ 5. operations
def test_health_reports_a_stopped_worker_and_a_paused_connector(demo_tenant):
    t = demo_tenant
    h = operations.health(t)
    assert h["workers"]["status"] == "failing" and h["status"] == "failing"     # no worker has ever ticked here
    worker.heartbeat()
    h = operations.health(t)
    assert h["workers"]["status"] == "ok" and h["workers"]["live"] == 1
    with admin_engine().begin() as c:
        c.execute(text("UPDATE worker_heartbeats SET last_tick_at = now() - interval '2 minutes'"))
    assert operations.health(t)["workers"]["status"] == "failing"
    worker.heartbeat()
    queued(t)
    sandbox_erp.set_connector(credentials_valid=False)
    act.dispatch_once(t)
    h = operations.health(t)
    assert h["status"] == "failing" and any("CREDENTIALS_INVALID" in p for p in h["problems"])
    with tenant_session(t) as s:
        s.execute(text("UPDATE outbox SET next_attempt_at = now() - interval '10 minutes'"))
    assert any("waited" in p for p in operations.health(t)["problems"])


def test_reconciliation_report_counts_unaccounted_orders_and_service_levels(demo_tenant):
    t = demo_tenant
    reconciled(t)
    b = queued(t)
    sandbox_erp.inject_fault(f"po-{b['id']}", "timeout_after_commit")
    act.dispatch_once(t)
    r = operations.reconciliation(t)
    assert r["actions_by_status"]["RECONCILED"] == 1 and r["unaccounted_orders"] == 1
    assert [x["status"] for x in r["needs_attention"]] == ["UNKNOWN_OUTCOME"]
    assert "never resends" in r["needs_attention"][0]["next_step"]
    sl = r["service_levels"]
    assert sl["approved"] == 2 and sl["reconciled"] == 1 and sl["unknown_outcomes"] == 1
    assert sl["p95_s"] is not None and sl["approved_to_reconciled_within_5_min"] == 1.0
    assert r["ledger"]["open_units"] == 30


def test_operations_endpoints_follow_the_role_matrix(demo_tenant):
    c = TestClient(app)
    h = {"X-Requested-With": "supplylens", "X-SupplyLens-Tenant": "demo"}

    def as_(role):
        c.post("/api/v1/auth/dev-login", json={"email": dev_email(role)}, headers=h)

    as_("viewer")
    assert c.get("/api/v1/ops/health", headers=h).status_code == 403
    assert c.get("/api/v1/ops/reconciliation", headers=h).status_code == 403
    assert c.post("/api/v1/sandbox/connector", json={"available": False}, headers=h).status_code == 403
    as_("planner")
    assert c.get("/api/v1/ops/reconciliation", headers=h).status_code == 200
    assert c.post("/api/v1/ops/connector/test", headers=h).status_code == 403
    as_("tenant_admin")
    body = c.get("/api/v1/ops/health", headers=h).json()
    assert body["database"]["schema_0011"] is True and "connector" in body
    assert c.post("/api/v1/ops/connector/test", headers=h).json()["status"] == "OK"


def test_an_unreachable_database_is_a_503_with_retry_after_not_a_500(monkeypatch):
    import psycopg
    from sqlalchemy.exc import OperationalError

    from supplylens.api import app as app_module

    class Down:
        def connect(self):
            raise OperationalError("SELECT 1", {}, psycopg.OperationalError("connection refused"))

    monkeypatch.setattr(app_module, "app_engine", lambda: Down())
    r = TestClient(app).get("/health")
    assert r.status_code == 503 and r.json()["code"] == "database_unavailable" and r.headers["Retry-After"] == "5"


def test_metrics_expose_the_dispatch_and_worker_gauges(demo_tenant):
    from supplylens import metrics
    queued(demo_tenant)
    with tenant_session(demo_tenant) as s:
        s.execute(text("UPDATE outbox SET next_attempt_at = now() - interval '90 seconds'"))
    worker.heartbeat()
    metrics._queue_cache.update(at=0.0, lines=[])
    lines: list[str] = []
    metrics._queue_depth(lines)
    got = {l.split()[0]: float(l.split()[1]) for l in lines if not l.startswith("#") and "{" not in l}
    assert got["supplylens_outbox_oldest_pending_seconds"] >= 90
    assert got["supplylens_erp_connectors_not_ok"] == 0 and got["supplylens_worker_heartbeat_age_seconds"] < 30


def test_reading_connector_state_never_creates_a_row(demo_tenant):
    """Workspace deletion must leave nothing behind; the worker reads connector state right after deleting a workspace."""
    assert connector.state(demo_tenant)["status"] == "OK" and connector.may_dispatch(demo_tenant) == (True, None)
    assert connector.probe(demo_tenant)["checked"] is False
    sync.sync_tenant(demo_tenant)
    with tenant_session(demo_tenant) as s:
        assert s.execute(text("SELECT count(*) FROM erp_connector_state")).scalar() == 0
