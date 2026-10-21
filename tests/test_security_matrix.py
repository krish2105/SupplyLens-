"""SEC-01: cross-tenant and cross-role denial matrix over the HTTP API, direct RLS and retrieval.

Data lives in the Demo workspace; probes come from the UCI Research workspace or from roles
without the permission. Expected: zero rows, chunks, actions or metadata disclosed.
"""
import uuid
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from supplylens.api.app import app
from supplylens.db import control_session, tenant_session
from supplylens.knowledge.retrieve import search
from supplylens.simulation import demo
from supplylens_worker.main import tick

DEMO = {"X-Requested-With": "supplylens", "X-SupplyLens-Tenant": "demo"}
OTHER = {"X-Requested-With": "supplylens", "X-SupplyLens-Tenant": "uci-research"}
RUN = {"mode": "draft", "sku_ids": ["DEMO-REF-SKU"], "knowledge_cutoff": "2026-10-20T09:00:00Z", "effective_date": "2026-10-20",
       "budget_minor": 18000, "currency": "USD", "allow_shortfall": False}


def login(c, role):
    c.post("/api/v1/auth/dev-login", json={"email": f"{role}@dev.supplylens.local"}, headers={"X-Requested-With": "supplylens"})


@pytest.fixture(scope="module")
def world():
    from conftest import TENANT_TABLES_CLEAR_ORDER  # noqa: F401  (ensures conftest env applied)

    from supplylens.db import admin_engine
    from supplylens.seed import seed, tenant_id
    seed()
    with admin_engine().begin() as conn:
        tables = conn.execute(text("select string_agg(quote_ident(tablename), ', ') from pg_tables where schemaname='public' "
                                   "and tablename not in ('alembic_version','tenants','users','memberships')")).scalar()
        conn.execute(text(f"TRUNCATE {tables}, sandbox_erp.purchase_orders, sandbox_erp.fault_injection CASCADE"))
    demo.load(tenant_id("demo"))
    c = TestClient(app)
    login(c, "planner")
    run_id = c.post("/api/v1/agent-runs", json=RUN, headers={**DEMO, "Idempotency-Key": "sec-run"}).json()["run_id"]
    tick()
    detail = c.get(f"/api/v1/agent-runs/{run_id}", headers=DEMO).json()
    action = c.get(f"/api/v1/actions/{detail['actions'][0]['id']}", headers=DEMO).json()
    docs = c.get("/api/v1/documents", headers=DEMO).json()
    fr = None
    return {"run_id": run_id, "action": action, "version_id": docs[0]["version_id"], "demo": tenant_id("demo"),
            "uci": tenant_id("uci-research"), "forecast": fr}


# ---------------------------------------------------------------- cross-tenant reads (HTTP)
CROSS_GET = [
    "/api/v1/actions/{action}", "/api/v1/agent-runs/{run}", "/api/v1/documents/versions/{version}",
    "/api/v1/forecasts/{fake}", "/api/v1/datasets/{fake}/quarantine",
]
CROSS_LIST_EMPTY = ["/api/v1/agent-runs/{run}/events", "/api/v1/actions", "/api/v1/agent-runs", "/api/v1/documents",
                    "/api/v1/sandbox/orders", "/api/v1/scenarios", "/api/v1/audit"]


@pytest.mark.parametrize("path", CROSS_GET)
def test_cross_tenant_object_reads_are_not_found(world, path):
    c = TestClient(app)
    login(c, "tenant_admin")
    p = path.format(action=world["action"]["id"], run=world["run_id"], version=world["version_id"], fake=uuid.uuid4())
    r = c.get(p, headers=OTHER)
    assert r.status_code == 404 or (r.status_code == 200 and r.json().get("rows") == [])


@pytest.mark.parametrize("path", CROSS_LIST_EMPTY)
def test_cross_tenant_lists_disclose_nothing_from_demo(world, path):
    c = TestClient(app)
    login(c, "tenant_admin")
    body = c.get(path.format(run=world["run_id"]), headers=OTHER).json()
    blob = str(body)
    assert world["action"]["id"] not in blob and str(world["run_id"]) not in blob and "DEMO-REF" not in blob


def test_cross_tenant_terms_and_evidence_return_nothing(world):
    c = TestClient(app)
    login(c, "viewer")
    t = c.get("/api/v1/terms", params={"sku_id": "DEMO-REF-SKU"}, headers=OTHER).json()
    assert t["applicable"] == [] and t["history"] == []
    ev = c.get("/api/v1/evidence/search", params={"q": "DEMO-REF-SKU minimum order quantity"}, headers=OTHER).json()
    assert all("DEMO-REF" not in r["excerpt"] for r in ev["results"])


def test_cross_tenant_sse_stream_emits_no_events(world):
    c = TestClient(app)
    login(c, "viewer")
    r = c.get(f"/api/v1/agent-runs/{world['run_id']}/stream", params={"ws": "uci-research"})
    assert r.status_code == 404 and "run_event" not in r.text


# ---------------------------------------------------------------- cross-tenant writes (HTTP)
CROSS_POST = [
    ("approve", lambda w: (f"/api/v1/actions/{w['action']['id']}/approve", {"payload_hash": w["action"]["payload_hash"], "expected_row_version": w["action"]["row_version"]}), "approver"),
    ("reject", lambda w: (f"/api/v1/actions/{w['action']['id']}/reject", {"reason": "x", "expected_row_version": w["action"]["row_version"]}), "approver"),
    ("edit", lambda w: (f"/api/v1/actions/{w['action']['id']}/edit", {"quantities": {"DEMO-REF-SKU": 35}, "expected_row_version": w["action"]["row_version"]}), "planner"),
    ("reconcile", lambda w: (f"/api/v1/actions/{w['action']['id']}/reconcile", {}), "approver"),
    ("fault", lambda w: ("/api/v1/sandbox/faults", {"action_id": w["action"]["id"], "mode": "timeout_after_commit"}), "planner"),
]


@pytest.mark.parametrize("name,build,role", CROSS_POST, ids=[x[0] for x in CROSS_POST])
def test_cross_tenant_mutations_are_rejected(world, name, build, role):
    c = TestClient(app)
    login(c, role)
    path, body = build(world)
    r = c.post(path, json=body, headers={**OTHER, "Idempotency-Key": f"x-{name}-{uuid.uuid4()}"})
    assert r.status_code in (404, 409)
    with tenant_session(world["demo"]) as s:
        assert s.execute(text("SELECT status FROM actions WHERE id=:i"), {"i": world["action"]["id"]}).scalar() == "PENDING_APPROVAL"


# ---------------------------------------------------------------- role matrix (same tenant)
ROLE_DENIED = [
    ("viewer", "POST", "/api/v1/agent-runs", RUN), ("approver", "POST", "/api/v1/agent-runs", RUN),
    ("tenant_admin", "POST", "/api/v1/agent-runs", RUN),
    ("viewer", "POST", "/api/v1/scenarios", {}), ("approver", "POST", "/api/v1/scenarios", {}),
    ("tenant_admin", "POST", "/api/v1/scenarios", {}),
    ("viewer", "POST", "/api/v1/forecasts", {"sku_ids": ["X"]}), ("approver", "POST", "/api/v1/forecasts", {"sku_ids": ["X"]}),
    ("viewer", "APPROVE", None, None), ("planner", "APPROVE", None, None), ("tenant_admin", "APPROVE", None, None),
    ("viewer", "REJECT", None, None), ("planner", "REJECT", None, None), ("tenant_admin", "REJECT", None, None),
    ("viewer", "EDIT", None, None), ("approver", "EDIT", None, None), ("tenant_admin", "EDIT", None, None),
    ("viewer", "RECONCILE", None, None),
]


@pytest.mark.parametrize("role,method,path,body", ROLE_DENIED, ids=[f"{r}-{m}-{p or ''}" for r, m, p, _ in ROLE_DENIED])
def test_role_matrix_denials(world, role, method, path, body):
    c = TestClient(app)
    login(c, role)
    a = world["action"]
    if method == "APPROVE":
        path, body = f"/api/v1/actions/{a['id']}/approve", {"payload_hash": a["payload_hash"], "expected_row_version": a["row_version"]}
    elif method == "REJECT":
        path, body = f"/api/v1/actions/{a['id']}/reject", {"reason": "no", "expected_row_version": a["row_version"]}
    elif method == "EDIT":
        path, body = f"/api/v1/actions/{a['id']}/edit", {"quantities": {"DEMO-REF-SKU": 35}, "expected_row_version": a["row_version"]}
    elif method == "RECONCILE":
        path, body = f"/api/v1/actions/{a['id']}/reconcile", {}
    r = c.post(path, json=body, headers={**DEMO, "Idempotency-Key": f"role-{uuid.uuid4()}"})
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------- session / transport
def test_no_session_is_401(world):
    assert TestClient(app).get("/api/v1/actions", headers=DEMO).status_code == 401


def test_forged_cookie_is_401(world):
    c = TestClient(app)
    c.cookies.set("sl_session", "forged.cookie.value")
    assert c.get("/api/v1/actions", headers=DEMO).status_code == 401


def test_missing_csrf_header_blocks_mutation(world):
    c = TestClient(app)
    login(c, "approver")
    a = world["action"]
    r = c.post(f"/api/v1/actions/{a['id']}/approve", json={"payload_hash": a["payload_hash"], "expected_row_version": a["row_version"]},
               headers={"X-SupplyLens-Tenant": "demo", "Idempotency-Key": "csrf"})
    assert r.status_code == 403


def test_query_param_workspace_not_accepted_for_mutations(world):
    c = TestClient(app)
    login(c, "planner")
    r = c.post("/api/v1/agent-runs?ws=demo", json=RUN, headers={"X-Requested-With": "supplylens", "Idempotency-Key": "qp"})
    assert r.status_code == 400


def test_unknown_workspace_indistinguishable_from_forbidden(world):
    c = TestClient(app)
    login(c, "viewer")
    a = c.get("/api/v1/overview", headers={**DEMO, "X-SupplyLens-Tenant": "does-not-exist"})
    assert a.status_code == 404 and a.json()["code"] == "tenant_not_found"


def test_deactivated_user_loses_access_on_next_request(world):
    from supplylens.db import admin_engine
    c = TestClient(app)
    login(c, "viewer")
    assert c.get("/api/v1/actions", headers=DEMO).status_code == 200
    with admin_engine().begin() as conn:
        conn.execute(text("UPDATE users SET active=false WHERE email='viewer@dev.supplylens.local'"))
    try:
        assert c.get("/api/v1/actions", headers=DEMO).status_code == 404
    finally:
        with admin_engine().begin() as conn:
            conn.execute(text("UPDATE users SET active=true WHERE email='viewer@dev.supplylens.local'"))


# ---------------------------------------------------------------- direct database (RLS) and retrieval
RLS_TABLES = ["actions", "approvals", "outbox", "agent_runs", "agent_events", "documents", "document_versions", "chunks",
              "supplier_terms", "inventory_positions", "products", "suppliers", "audit_events", "idempotency_keys", "jobs",
              "warehouse_slots", "tenant_settings", "forecast_runs", "plan_runs"]


@pytest.mark.parametrize("table", RLS_TABLES)
def test_direct_sql_from_other_tenant_sees_no_demo_rows(world, table):
    with tenant_session(world["uci"]) as s:
        n = s.execute(text(f"SELECT count(*) FROM {table} WHERE tenant_id = :d"), {"d": world["demo"]}).scalar()
    assert n == 0


def test_no_tenant_context_sees_no_rows(world):
    with control_session() as s:
        for t in ("actions", "chunks", "agent_events"):
            assert s.execute(text(f"SELECT count(*) FROM {t}")).scalar() == 0


def test_vector_retrieval_never_crosses_tenants(world):
    res = search(world["uci"], "minimum order quantity reference component", as_of=datetime(2100, 1, 1, tzinfo=UTC),
                 role="planner", mode="known", effective_date=date(2026, 10, 20), k=20)
    assert all("Reference" not in r.title for r in res["results"])
