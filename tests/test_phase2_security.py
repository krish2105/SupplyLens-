"""Security regression tests for Phase 2 (docs/agent-handoff/phases/PHASE-02.md). Finding IDs are in the test names.

Negative tests first: every probe asserts that nothing was disclosed or changed, not only the status code.
"""
import uuid
from datetime import UTC, date, datetime

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import text

from supplylens.actions import service as act
from supplylens.agent.graph import create_run
from supplylens.api import guards
from supplylens.api.app import app
from supplylens.api.deps import COOKIE, serializer
from supplylens.authz import resolve_actor
from supplylens.config import Settings, settings
from supplylens.db import admin_engine, control_session, tenant_session
from supplylens.integrations import sandbox_erp
from supplylens.onboarding import csv_import as ci
from supplylens.onboarding import service as onb
from supplylens.planning.terms_service import applicable_terms
from supplylens.seed import dev_email, tenant_id, user_id
from supplylens.simulation import demo
from supplylens_opt.planner import Need, PlanRequest, plan
from supplylens_worker.main import run_job, tick

H = {"X-Requested-With": "supplylens"}
DEMO = {**H, "X-SupplyLens-Tenant": "demo"}
UCI = {**H, "X-SupplyLens-Tenant": "uci-research"}
CUTOFF = datetime(2026, 10, 20, 9, tzinfo=UTC)
EFF = date(2026, 10, 20)


def who(tenant, role):
    return resolve_actor(user_id(dev_email(role)), tenant)


def login(role, client=None):
    c = client or TestClient(app)
    r = c.post("/api/v1/auth/dev-login", json={"email": dev_email(role)}, headers=H)
    assert r.status_code == 200, r.text
    return c


@pytest.fixture()
def demo_tenant(clean_db, tenant_b):
    demo.load(tenant_b)
    return tenant_b


def approved(tenant):
    res = applicable_terms(tenant, ["DEMO-REF-SKU"], CUTOFF, EFF)
    result = plan(PlanRequest(decision_date=EFF, need_by=date(2026, 10, 22), currency="USD", budget_minor=18000,
                              needs=[Need(sku_id="DEMO-REF-SKU", required_units=30)], offers=res.applicable))
    a = act.prepare(who(tenant, "planner"), supplier_id=result.lines[0].supplier_id, lines=result.lines, currency="USD",
                    need_by=date(2026, 10, 22), decision={"knowledge_cutoff": CUTOFF.isoformat(), "effective_date": EFF.isoformat(),
                                                           "plan_input_hash": result.input_hash, "budget_minor": 18000},
                    evidence={}, versions={})
    act.approve(who(tenant, "approver"), a["id"], payload_hash=a["payload_hash"], expected_row_version=a["row_version"])
    return a


# =========================================================================================== SEC-P2-02 sessions
def _session_row(c):
    sid = serializer.loads(c.cookies[COOKIE])["sid"]
    with control_session() as s:
        return sid, s.execute(text("SELECT user_id, revoked_at, revoked_reason FROM auth_sessions WHERE id=:i"),
                              {"i": sid}).first()


def test_SEC_P2_02_dev_sign_in_creates_a_server_side_session(demo_tenant):
    c = login("viewer")
    sid, row = _session_row(c)
    assert row is not None and row.revoked_at is None and str(row.user_id) == str(user_id(dev_email("viewer")))


def test_SEC_P2_02_sign_out_revokes_the_session_so_a_copied_cookie_stops_working(demo_tenant):
    c = login("viewer")
    stolen = c.cookies[COOKIE]
    assert c.get("/api/v1/overview", headers=DEMO).status_code == 200
    assert c.post("/api/v1/auth/logout", headers=H).status_code == 200
    replay = TestClient(app)
    replay.cookies.set(COOKIE, stolen)
    r = replay.get("/api/v1/overview", headers=DEMO)
    assert r.status_code == 401 and r.json()["code"] == "session_revoked"


def test_SEC_P2_02_an_idle_session_expires_and_is_revoked(demo_tenant):
    c = login("viewer")
    sid, _ = _session_row(c)
    with admin_engine().begin() as conn:
        conn.execute(text("UPDATE auth_sessions SET checked_at = now() - interval '3 hours' WHERE id=:i"), {"i": sid})
    r = c.get("/api/v1/overview", headers=DEMO)
    assert r.status_code == 401 and r.json()["code"] == "session_expired"
    assert _session_row(c)[1].revoked_reason == "idle timeout"


def test_SEC_P2_02_stateless_cookies_from_before_phase_2_are_refused(demo_tenant):
    c = TestClient(app)
    c.cookies.set(COOKIE, serializer.dumps({"uid": str(user_id(dev_email("approver")))}))
    assert c.get("/api/v1/overview", headers=DEMO).status_code == 401


def test_SEC_P2_02_session_cookie_attributes(demo_tenant, monkeypatch):
    monkeypatch.setattr(settings, "cookie_secure", True)
    r = TestClient(app).post("/api/v1/auth/dev-login", json={"email": dev_email("viewer")}, headers=H)
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "secure" in cookie and "path=/" in cookie


def test_SEC_P2_02_cors_is_closed_to_other_origins(demo_tenant):
    c = login("viewer")
    pre = c.options("/api/v1/overview", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    get = c.get("/api/v1/overview", headers={**DEMO, "Origin": "https://evil.example"})
    for r in (pre, get):
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers}
        assert "access-control-allow-credentials" not in {k.lower() for k in r.headers}


# =========================================================================================== SEC-P2-03 resource limits
def _tiny_app():
    a = FastAPI()

    @a.post("/api/v1/auth/dev-login")
    def dev_login():
        return {"ok": True}

    @a.post("/echo")
    async def echo(request: Request):
        return {"n": len(await request.body())}
    return a


def test_SEC_P2_03_oversized_bodies_are_refused_before_authentication():
    r = TestClient(app).post("/api/v1/onboarding/batches", headers={**DEMO, "Content-Length": str(guards.MAX_BODY_BYTES + 1)},
                             content=b"x")
    assert r.status_code == 413 and r.json()["code"] == "payload_too_large"


def test_SEC_P2_03_streamed_bodies_are_counted_not_trusted():
    limited = guards.BodyLimit(_tiny_app(), max_bytes=1000)
    c = TestClient(limited)
    assert c.post("/echo", content=b"a" * 900).json() == {"n": 900}

    def chunks():
        for _ in range(5):
            yield b"b" * 400
    r = c.post("/echo", content=chunks())             # no Content-Length: counted as it streams
    assert r.status_code == 413


def test_SEC_P2_03_sign_in_attempts_are_throttled_per_client():
    c = TestClient(guards.SignInThrottle(_tiny_app(), per_minute=3, trust_forwarded_for=False))
    codes = [c.post("/api/v1/auth/dev-login").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    # a caller-chosen X-Forwarded-For does not buy new attempts unless the deployment trusts its proxy
    assert c.post("/api/v1/auth/dev-login", headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 429
    trusted = TestClient(guards.SignInThrottle(_tiny_app(), per_minute=1, trust_forwarded_for=True))
    assert trusted.post("/api/v1/auth/dev-login", headers={"X-Forwarded-For": "203.0.113.1"}).status_code == 200
    assert trusted.post("/api/v1/auth/dev-login", headers={"X-Forwarded-For": "203.0.113.1"}).status_code == 429
    assert trusted.post("/api/v1/auth/dev-login", headers={"X-Forwarded-For": "203.0.113.2"}).status_code == 200


def test_SEC_P2_03_workspace_creation_is_rate_limited(demo_tenant, monkeypatch):
    from supplylens.api import ratelimit
    calls = []
    monkeypatch.setattr(ratelimit, "take", lambda t, b, per, burst=None: calls.append(b) or 7)
    r = login("tenant_admin").post("/api/v1/onboarding/workspaces", headers=DEMO,
                                    json={"slug": "rate-probe", "name": "Rate", "currency": "USD", "weekly_budget_minor": 1})
    assert r.status_code == 429 and calls and calls[0].startswith("workspace_create:")
    with control_session() as s:
        assert s.execute(text("SELECT count(*) FROM tenants WHERE slug='rate-probe'")).scalar() == 0


# =========================================================================================== SEC-P2-04 error disclosure
class _DbError(Exception):
    def __init__(self, sqlstate, msg):
        super().__init__(msg)
        self.sqlstate = sqlstate


def test_SEC_P2_04_only_deliberate_database_refusals_reach_the_client():
    deliberate = type("E", (Exception,), {})("wrapped")
    deliberate.orig = _DbError("P0001", "only an active administrator of this workspace can change memberships\nCONTEXT: x")
    leak = type("E", (Exception,), {})("wrapped")
    leak.orig = _DbError("23503", 'insert or update on table "memberships" violates foreign key constraint "fk_x"')
    assert onb._refusal(deliberate, "generic") == "only an active administrator of this workspace can change memberships"
    assert onb._refusal(leak, "generic") == "generic"


def test_SEC_P2_04_integration_status_does_not_echo_exception_text(demo_tenant, monkeypatch):
    monkeypatch.setattr(sandbox_erp, "health", lambda: (_ for _ in ()).throw(RuntimeError("password=hunter2 host=db.internal")))
    body = login("viewer").get("/api/v1/integrations", headers=DEMO).text
    assert "hunter2" not in body and "db.internal" not in body


# =========================================================================================== P2-PRIV-01 / P3-ONB-01
def test_P2_PRIV_01_personal_data_is_removed_before_it_is_stored(demo_tenant):
    admin = who(demo_tenant, "tenant_admin")
    data = b"day,sku_id,location_id,units\n2026-09-01,DEMO-REF-SKU,WH-01,3\n2026-09-02,ann@example.com,WH-01,3\n"
    b = onb.upload(admin, kind="sales", file_name="s.csv", data=data, rights="our own ERP export")
    with tenant_session(demo_tenant) as s:
        stored = s.execute(text("SELECT raw::text FROM import_rows WHERE batch_id=:b"), {"b": b["id"]}).scalars().all()
    assert not any("ann@example.com" in r for r in stored) and any(ci.REDACTED in r for r in stored)
    v = onb.validate_batch(admin, b["id"], b["mapping"])
    assert v["rows_quarantined"] == 1 and "personal data" in " ".join(v["quarantined_sample"][0]["errors"])
    assert "ann@example.com" not in str(onb.get(who(demo_tenant, "viewer"), b["id"]))


@pytest.mark.parametrize("data,code", [
    (b"day,sku_id,location_id,units\n2026-09-01,\"" + b"x" * 140_000 + b"\",WH,1\n", "malformed_csv"),
    (b"day,sku_id,location_id,units\n2026-09-01,A\x00B,WH,1\n", "binary_content"),
])
def test_P3_ONB_01_malformed_files_are_refused_cleanly_not_with_a_server_error(demo_tenant, data, code):
    with pytest.raises(onb.OnboardingError) as e:
        onb.upload(who(demo_tenant, "tenant_admin"), kind="sales", file_name="bad.csv", data=data, rights="our own ERP export")
    assert e.value.code == code


# =========================================================================================== SEC-P2-05 tenant isolation
def test_SEC_P2_05_every_tenant_table_forces_row_level_security_with_a_check():
    """Completeness: a new table with tenant_id cannot ship without FORCE RLS and a USING + WITH CHECK policy."""
    with admin_engine().connect() as c:
        rows = c.execute(text("""
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                   bool_or(p.qual IS NOT NULL AND p.with_check IS NOT NULL) AS checked
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN information_schema.columns col ON col.table_schema = 'public' AND col.table_name = c.relname
                 AND col.column_name = 'tenant_id'
            LEFT JOIN pg_policies p ON p.schemaname = 'public' AND p.tablename = c.relname
            WHERE n.nspname = 'public' AND c.relkind = 'r'
              AND c.relname NOT IN ('memberships', 'tenant_deletions')      -- control plane, read-only to the app (D-009)
            GROUP BY 1, 2, 3""")).all()
    assert len(rows) >= 38
    bad = [r.relname for r in rows if not (r.relrowsecurity and r.relforcerowsecurity and r.checked)]
    assert bad == []


def test_SEC_P2_05_no_tenant_table_leaks_rows_to_another_tenant(demo_tenant):
    approved(demo_tenant)
    act.dispatch_once(demo_tenant)
    with admin_engine().connect() as c:
        tables = c.execute(text("""SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname='public' AND c.relforcerowsecurity""")).scalars().all()
    uci = tenant_id("uci-research")
    with tenant_session(uci) as s:
        leaked = {t: s.execute(text(f'SELECT count(*) FROM "{t}" WHERE tenant_id = :d'), {"d": demo_tenant}).scalar()
                  for t in tables}
    assert {t: n for t, n in leaked.items() if n} == {}


def test_SEC_P2_05_phase_1_object_routes_refuse_other_tenants(demo_tenant):
    a = approved(demo_tenant)
    sandbox_erp.inject_fault(f"po-{a['id']}", "alter_line_price")
    act.dispatch_once(demo_tenant)                              # CONFIRMED (read-back mismatch) in Demo
    with tenant_session(demo_tenant) as s:
        before = s.execute(text("SELECT status, row_version FROM actions WHERE id=:i"), {"i": a["id"]}).first()
    approver, planner = login("approver"), login("planner")
    probes = [
        (approver, "post", f"/api/v1/actions/{a['id']}/accept-remote", {"reason": "cross-tenant probe"}),
        (approver, "post", f"/api/v1/actions/{a['id']}/reconcile", {}),
        (planner, "post", f"/api/v1/actions/{a['id']}/retry", {}),
        (planner, "post", f"/api/v1/actions/{a['id']}/cancel-open", {"sku_id": "DEMO-REF-SKU", "reason": "probe"}),
        (planner, "post", f"/api/v1/actions/{a['id']}/receipts", {"sku_id": "DEMO-REF-SKU", "quantity": 1,
                                                                    "received_on": "2026-10-21"}),
        (planner, "get", f"/api/v1/onboarding/batches/{uuid.uuid4()}", None),
        (planner, "post", f"/api/v1/alerts/{uuid.uuid4()}/acknowledge", {}),
    ]
    for c, method, url, body in probes:
        kw = {"headers": {**UCI, "Idempotency-Key": uuid.uuid4().hex}}
        if body is not None:
            kw["json"] = body
        r = getattr(c, method)(url, **kw)
        assert r.status_code in (403, 404), (url, r.status_code, r.text)
        assert "DEMO-REF" not in r.text
    with tenant_session(demo_tenant) as s:
        after = s.execute(text("SELECT status, row_version FROM actions WHERE id=:i"), {"i": a["id"]}).first()
    assert tuple(after) == tuple(before) == ("CONFIRMED", before.row_version)


# =========================================================================================== SEC-P2-09 worker context
def test_SEC_P2_09_a_job_cannot_execute_another_tenants_run(demo_tenant):
    run = create_run(who(demo_tenant, "planner"), mode="draft", inp={"sku_ids": ["DEMO-REF-SKU"]})
    uci = tenant_id("uci-research")
    forged = {"id": uuid.uuid4(), "kind": "agent_run", "payload": {"run_id": str(run)}, "attempts": 1, "fencing_token": 1}
    with tenant_session(uci) as s:                    # a job in UCI's queue naming Demo's run
        s.execute(text("""INSERT INTO jobs (id, tenant_id, kind, payload, status, attempts, fencing_token)
            VALUES (:i, :t, 'agent_run', CAST(:p AS jsonb), 'RUNNING', 1, 1)"""),
                  {"i": forged["id"], "t": uci, "p": f'{{"run_id": "{run}"}}'})
    run_job(uci, forged)
    with tenant_session(uci) as s:
        status, error = s.execute(text("SELECT status, error FROM jobs WHERE id=:i"), {"i": forged["id"]}).first()
    with tenant_session(demo_tenant) as s:
        demo_status = s.execute(text("SELECT status FROM agent_runs WHERE id=:r"), {"r": run}).scalar()
        drafts = s.execute(text("SELECT count(*) FROM actions WHERE agent_run_id=:r"), {"r": run}).scalar()
    assert status == "FAILED" and "not found" in error and demo_status == "QUEUED" and drafts == 0


def test_SEC_P2_09_a_queued_run_stops_when_its_creator_loses_access(demo_tenant):
    run = create_run(who(demo_tenant, "planner"), mode="draft", inp={
        "sku_ids": ["DEMO-REF-SKU"], "knowledge_cutoff": CUTOFF.isoformat(), "effective_date": EFF.isoformat(),
        "currency": "USD", "budget_minor": 18000})
    with admin_engine().begin() as c:
        c.execute(text("DELETE FROM memberships WHERE tenant_id=:t AND user_id=:u"),
                  {"t": demo_tenant, "u": user_id(dev_email("planner"))})
    try:
        tick()
        with tenant_session(demo_tenant) as s:
            st = s.execute(text("SELECT status FROM agent_runs WHERE id=:r"), {"r": run}).scalar()
            drafts = s.execute(text("SELECT count(*) FROM actions WHERE agent_run_id=:r"), {"r": run}).scalar()
        assert st == "FAILED" and drafts == 0
    finally:
        with admin_engine().begin() as c:
            c.execute(text("INSERT INTO memberships (tenant_id, user_id, role) VALUES (:t, :u, 'planner') ON CONFLICT DO NOTHING"),
                      {"t": demo_tenant, "u": user_id(dev_email("planner"))})


# =========================================================================================== SEC-P2-01 fixture safety
def test_SEC_P2_01_disposable_flag_is_refused_outside_development():
    safe = dict(session_secret="x" * 40, alert_webhook_secret="y" * 40, cookie_secure=True, admin_database_url=None,
                database_url="postgresql+psycopg://supplylens_app:s3cret@db/sl")
    with pytest.raises(ValueError, match="E2E_DISPOSABLE"):
        Settings(environment="demo", dev_auth=True, e2e_disposable=True, **safe)


def test_SEC_P2_01_auth_config_reports_disposable_only_when_declared(monkeypatch):
    c = TestClient(app)
    assert c.get("/api/v1/auth/config").json()["disposable"] is False
    monkeypatch.setattr(settings, "e2e_disposable", True)
    assert c.get("/api/v1/auth/config").json()["disposable"] is True


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://supplylens_owner:x@localhost:5432/supplylens",          # the developer's real database
    "postgresql+psycopg://supplylens_owner:x@db.example.com:5432/supplylens_test",  # a remote host
])
def test_SEC_P2_01_test_fixtures_refuse_databases_that_are_not_disposable(monkeypatch, url):
    import conftest
    monkeypatch.setenv("SUPPLYLENS_ADMIN_DATABASE_URL", url)
    with pytest.raises(pytest.UsageError, match="refusing to run"):
        conftest._refuse_unless_disposable_test_database()
