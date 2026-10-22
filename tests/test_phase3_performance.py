"""Phase 3: admission control, overload responses, timeouts, bounded listings, metrics and worker reliability."""
import asyncio
import uuid
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as PoolTimeout

from supplylens import metrics
from supplylens.actions import service as act
from supplylens.api import admission, routes_core
from supplylens.api.app import app
from supplylens.authz import resolve_actor
from supplylens.db import tenant_session
from supplylens.integrations import sandbox_erp
from supplylens.planning.terms_service import applicable_terms
from supplylens.seed import dev_email, tenant_id, user_id
from supplylens.simulation import demo
from supplylens_opt.planner import Need, PlanRequest, plan
from supplylens_worker import main as worker

H = {"X-Requested-With": "supplylens"}
DEMO = {**H, "X-SupplyLens-Tenant": "demo"}
CUTOFF = datetime(2026, 10, 20, 9, tzinfo=UTC)


def prepared(tenant):
    """An approved-ready draft for the demo reference case (same construction as test_actions)."""
    eff = date(2026, 10, 20)
    res = applicable_terms(tenant, ["DEMO-REF-SKU"], CUTOFF, eff)
    req = PlanRequest(decision_date=eff, need_by=date(2026, 10, 22), currency="USD", budget_minor=18000,
                      needs=[Need(sku_id="DEMO-REF-SKU", required_units=30)], offers=res.applicable)
    result = plan(req)
    decision = {"knowledge_cutoff": CUTOFF.isoformat(), "effective_date": eff.isoformat(), "plan_input_hash": result.input_hash}
    return act.prepare(resolve_actor(user_id(dev_email("planner")), tenant), supplier_id=result.lines[0].supplier_id,
                       lines=result.lines, currency="USD", need_by=req.need_by, decision=decision,
                       evidence={"terms": [l.term_id for l in result.lines]}, versions={"plan": result.input_hash})


def approve(tenant, a):
    return act.approve(resolve_actor(user_id(dev_email("approver")), tenant), a["id"], payload_hash=a["payload_hash"],
                       expected_row_version=a["row_version"])


@pytest.fixture()
def demo_tenant(clean_db, tenant_b):
    demo.load(tenant_b)
    return tenant_b


@pytest.fixture()
def client(demo_tenant):
    c = TestClient(app)
    assert c.post("/api/v1/auth/dev-login", json={"email": dev_email("planner")}, headers=H).status_code == 200
    return c


# ----------------------------------------------------------------------------- admission control
def test_a_workspace_over_its_share_is_refused_while_another_workspace_is_admitted(monkeypatch):
    g = admission.Gate("t", cap=4)
    monkeypatch.setattr(admission.settings, "tenant_share", 0.5)

    async def scenario():
        assert [await g.acquire("demo") for _ in range(3)] == [None, None, None]   # alone, a workspace may use more
        g.release("demo")
        assert await g.acquire("uci-research") is None                    # another workspace is admitted
        assert await g.acquire("demo") == "tenant_share"                  # now 2 of 4 is demo's share while it competes
        g.release("uci-research")
        assert await g.acquire("demo") is None                            # alone again: admitted
    asyncio.run(scenario())
    status, body, headers = admission.refusal("tenant_share", "retrieval")
    assert status == 429 and body["code"] == "workspace_busy" and headers["Retry-After"] == "2"


def test_a_workspace_alone_is_never_refused_for_its_share_even_with_its_own_requests_queued(monkeypatch):
    monkeypatch.setattr(admission.settings, "admission_wait_ms", 2000)
    g = admission.Gate("t", cap=2)

    async def scenario():
        assert [await g.acquire("demo") for _ in range(2)] == [None, None]
        queued = asyncio.create_task(g.acquire("demo"))
        await asyncio.sleep(0.03)
        assert g.waiting_by_tenant == {"demo": 1}
        g.release("demo")
        assert await asyncio.wait_for(queued, 1) is None                  # its own queue never counts against it
        assert g.waiting_by_tenant == {}
        other = asyncio.create_task(g.acquire("uci-research"))           # another workspace queues ...
        await asyncio.sleep(0.03)
        assert await g.acquire("demo") == "tenant_share"                  # ... so demo, at its share, is refused
        g.release("demo")
        assert await asyncio.wait_for(other, 1) is None
    asyncio.run(scenario())


def test_tenant_share_is_enforced_on_the_route(client, monkeypatch):
    g = admission.gates()["retrieval"]
    monkeypatch.setattr(g, "by_tenant", {"demo": g.tenant_cap, "uci-research": 1})
    r = client.get("/api/v1/evidence/search", params={"q": "minimum order"}, headers=DEMO)
    assert r.status_code == 429 and r.json()["code"] == "workspace_busy" and r.headers["Retry-After"] == "2"
    monkeypatch.setattr(g, "by_tenant", {})
    assert client.get("/api/v1/evidence/search", params={"q": "minimum order"}, headers=DEMO).status_code == 200


def test_a_full_class_queues_briefly_and_admits_when_a_slot_frees(monkeypatch):
    monkeypatch.setattr(admission.settings, "admission_wait_ms", 2000)
    g = admission.Gate("t", cap=1)

    async def scenario():
        assert await g.acquire("a") is None
        waiter = asyncio.create_task(g.acquire("b"))
        await asyncio.sleep(0.05)
        assert g.waiting == 1 and not waiter.done()
        g.release("a")
        assert await asyncio.wait_for(waiter, 1) is None             # admitted, not refused
        assert g.inflight == 1 and g.queued == 1
    asyncio.run(scenario())


def test_the_queue_is_bounded_and_waiting_is_bounded(monkeypatch):
    monkeypatch.setattr(admission.settings, "admission_wait_ms", 30)
    monkeypatch.setattr(admission.settings, "admission_queue", 1)
    g = admission.Gate("t", cap=1)

    async def scenario():
        assert await g.acquire(None) is None
        first = asyncio.create_task(g.acquire(None))
        await asyncio.sleep(0.005)
        assert await g.acquire(None) == "queue_full"                    # queue holds one; the next is refused at once
        assert await first == "wait_timeout"                            # the queued one gives up after the wait
        assert g.rejected == {"queue_full": 1, "wait_timeout": 1} and g.inflight == 1 and g.waiting == 0
    asyncio.run(scenario())


def test_compute_and_retrieval_have_separate_caps(client, monkeypatch):
    monkeypatch.setattr(admission.settings, "admission_wait_ms", 20)
    g = admission.gates()
    monkeypatch.setattr(g["compute"], "inflight", g["compute"].cap)
    r = client.post("/api/v1/scenarios", json={"name": "x"}, headers={**DEMO, "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 503 and r.json()["code"] == "overloaded"
    assert client.get("/api/v1/evidence/search", params={"q": "lead time"}, headers=DEMO).status_code == 200


# ----------------------------------------------------------------------------- database limits
def test_an_exhausted_connection_pool_answers_503_with_retry_after(client, monkeypatch):
    def busy(*a, **k):
        raise PoolTimeout("QueuePool limit reached")
    monkeypatch.setattr(routes_core, "tenant_session", busy)
    r = client.get("/api/v1/inventory", headers=DEMO)
    assert r.status_code == 503 and r.json()["code"] == "overloaded" and r.headers["Retry-After"] == "3"


def test_a_retrieval_past_its_statement_timeout_is_cancelled_with_503(client, monkeypatch):
    from supplylens.knowledge import retrieve
    monkeypatch.setattr(retrieve.settings, "retrieval_statement_timeout_ms", 50)
    monkeypatch.setattr(retrieve, "embed", lambda *a, **k: None)
    # The demo corpus is tiny, so make the statement slow on purpose (a one-time filter: 0.5 s against a 50 ms budget).
    monkeypatch.setattr(retrieve, "BASE_FILTER", "pg_sleep(0.5) IS NOT NULL AND " + retrieve.BASE_FILTER)
    r = client.get("/api/v1/evidence/search", params={"q": "minimum order"}, headers=DEMO)
    assert r.status_code == 503 and r.json()["code"] == "query_timeout" and r.headers["Retry-After"] == "3"
    monkeypatch.undo()
    assert client.get("/api/v1/evidence/search", params={"q": "minimum order"}, headers=DEMO).status_code == 200


def test_app_connections_carry_a_statement_timeout_and_owner_connections_do_not():
    from supplylens.db import admin_engine, app_engine
    with app_engine().connect() as c:
        assert c.execute(text("SHOW statement_timeout")).scalar() == "30s"
    with admin_engine().connect() as c:
        assert c.execute(text("SHOW statement_timeout")).scalar() == "0"


# ----------------------------------------------------------------------------- bounded listings
def test_inventory_pages_with_total_and_next_offset(client, monkeypatch):
    full = client.get("/api/v1/inventory", headers=DEMO).json()
    n = len(full["items"])
    assert n >= 2 and full["total"] == n and full["next_offset"] is None and full["offset"] == 0
    first = client.get("/api/v1/inventory", params={"limit": 1}, headers=DEMO).json()
    assert [i["sku_id"] for i in first["items"]] == [full["items"][0]["sku_id"]]
    assert first["total"] == n and first["next_offset"] == 1
    last = client.get("/api/v1/inventory", params={"limit": 1, "offset": n - 1}, headers=DEMO).json()
    assert last["items"][0]["sku_id"] == full["items"][-1]["sku_id"] and last["next_offset"] is None
    past = client.get("/api/v1/inventory", params={"offset": n + 5}, headers=DEMO).json()
    assert past["items"] == [] and past["total"] == n
    monkeypatch.setattr(routes_core.settings, "list_max_rows", 1)        # the server bound applies without a limit
    capped = client.get("/api/v1/inventory", headers=DEMO).json()
    assert len(capped["items"]) == 1 and capped["next_offset"] == 1
    assert client.get("/api/v1/inventory", params={"limit": 0}, headers=DEMO).status_code == 422


def test_documents_are_bounded_and_report_the_total(client):
    full = client.get("/api/v1/documents", headers=DEMO)
    n = len(full.json())
    assert n >= 2 and full.headers["X-Total-Count"] == str(n)
    page = client.get("/api/v1/documents", params={"limit": 1, "offset": 1}, headers=DEMO)
    assert page.json() == full.json()[1:2] and page.headers["X-Total-Count"] == str(n)
    assert all(isinstance(d["chunks"], int) for d in full.json())


# ----------------------------------------------------------------------------- metrics
def test_metrics_endpoint_exists_only_with_a_token_and_reports_per_workspace_use(client, monkeypatch):
    assert client.get("/metrics").status_code == 404
    monkeypatch.setattr("supplylens.api.app.settings.metrics_token", "t" * 32)
    metrics.reset()
    client.get("/api/v1/inventory", headers=DEMO)
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = client.get("/metrics", headers={"Authorization": "Bearer " + "t" * 32})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    body = r.text
    assert 'supplylens_http_requests_total{method="GET",route="/api/v1/inventory",status="2xx"} 1' in body
    assert 'supplylens_http_request_duration_seconds_count{method="GET",route="/api/v1/inventory"} 1' in body
    assert f'supplylens_tenant_requests_total{{workspace="{tenant_id("demo")}"}} 1' in body
    for series in ('supplylens_admission_capacity{class="retrieval"}', "supplylens_db_pool_checked_out",
                   'supplylens_jobs{status="QUEUED"}', 'supplylens_outbox{status="PENDING"}',
                   'supplylens_db_connections{state="active"}'):
        assert series in body, series
    assert "planner@" not in body and "q=" not in body                     # no user ids or query text in labels


# ----------------------------------------------------------------------------- worker reliability
def test_a_dispatch_interrupted_too_often_is_parked_for_reconciliation_not_resent(demo_tenant):
    a = prepared(demo_tenant)
    approve(demo_tenant, a)
    with tenant_session(demo_tenant) as s:
        s.execute(text("UPDATE outbox SET status='IN_FLIGHT', attempts=:n, lease_owner='dead', "
                       "lease_expires_at=now() - interval '1 second' WHERE action_id=:i"),
                  {"n": act.OUTBOX_MAX_ATTEMPTS, "i": a["id"]})
    op = None
    with tenant_session(demo_tenant) as s:
        op = s.execute(text("SELECT operation_id FROM outbox WHERE action_id=:i"), {"i": a["id"]}).scalar()
    r = act.dispatch_once(demo_tenant, "w")
    assert r["result"] == "DEAD_LETTER"
    assert sandbox_erp.lookup(op) is None                                   # nothing was sent
    with tenant_session(demo_tenant) as s:
        status = s.execute(text("SELECT status FROM actions WHERE id=:i"), {"i": a["id"]}).scalar()
        alert = s.execute(text("SELECT kind FROM alerts WHERE dedupe_key = :k AND status = 'OPEN'"),
                          {"k": f"failed_reconciliation:{a['id']}"}).scalar()
    assert status == "UNKNOWN_OUTCOME" and alert == "failed_reconciliation"
    assert act.dispatch_once(demo_tenant, "w") is None                      # parked, not claimed again


def test_one_failing_workspace_does_not_stop_the_worker_for_the_others(demo_tenant, tenant_a, monkeypatch):
    seen = []

    def tenant_tick(t):
        seen.append(t)
        if t == tenant_a:
            raise RuntimeError("database blip in one workspace")
        return 1
    monkeypatch.setattr(worker, "tenant_tick", tenant_tick)
    assert worker.tick() >= 1 and demo_tenant in seen and tenant_a in seen


def test_dispatches_per_workspace_and_tick_are_bounded(demo_tenant, monkeypatch):
    calls = []
    monkeypatch.setattr(worker.actions, "dispatch_once", lambda t, w: calls.append(t) or {"result": "RECONCILED"})
    monkeypatch.setattr(worker.jobs, "claim", lambda t, w: None)
    monkeypatch.setattr(worker, "refresh_runs", lambda t: None)
    monkeypatch.setattr(worker, "alert_tick", lambda t: None)
    assert worker.tenant_tick(demo_tenant) == worker.DISPATCH_PER_TICK
