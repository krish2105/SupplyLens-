"""BUS-020 rehearsals: failed migration, deployment rollback, connector outage and model outage.

Pass criteria for every rehearsal: no unaccounted orders (each sandbox order maps to exactly one action) and no
silent loss of audit evidence. Migration rehearsals run against a scratch database created through libpq's
environment (PGHOST/PGUSER/PGPASSWORD, a superuser); they are skipped when none is available.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from supplylens.actions import service as svc
from supplylens.api.app import app
from supplylens.config import REPO_ROOT
from supplylens.db import admin_engine, tenant_session
from supplylens.integrations import sandbox_erp
from supplylens.seed import seed, tenant_id
from supplylens.simulation import demo
from supplylens_worker.main import tick

MIGRATIONS = REPO_ROOT / "services" / "api" / "migrations"
HEAD = "0010"                     # current migration head; update with each new migration
DEMO = {"X-Requested-With": "supplylens", "X-SupplyLens-Tenant": "demo"}
RUN = {"mode": "draft", "sku_ids": ["DEMO-REF-SKU"], "knowledge_cutoff": "2026-10-20T09:00:00Z",
       "effective_date": "2026-10-20", "budget_minor": 18000, "currency": "USD", "allow_shortfall": False}
HOST = os.environ.get("SUPPLYLENS_TEST_DB_HOST", "localhost")


# ----------------------------------------------------------------------------- scratch database harness
def _superuser():
    import psycopg
    try:
        return psycopg.connect(dbname="postgres", autocommit=True, connect_timeout=5)
    except Exception as e:
        pytest.skip(f"needs a PostgreSQL superuser through libpq environment variables: {e}")


class Scratch:
    def __init__(self):
        self.name = "sl_rehearsal_" + uuid.uuid4().hex[:8]
        self.owner_url = f"postgresql+psycopg://supplylens_owner:supplylens_owner_dev@{HOST}:5432/{self.name}"
        self.app_url = f"postgresql+psycopg://supplylens_app:supplylens_app_dev@{HOST}:5432/{self.name}"
        self.storage = f"storage_{self.name}"

    def __enter__(self):
        import psycopg
        with _superuser() as c:
            c.execute(f"CREATE DATABASE {self.name} OWNER supplylens_owner")
        with psycopg.connect(dbname=self.name, autocommit=True) as c:
            c.execute("CREATE EXTENSION vector")
            c.execute(f"GRANT CONNECT ON DATABASE {self.name} TO supplylens_app")
        return self

    def __exit__(self, *a):
        with _superuser() as c:
            c.execute(f"DROP DATABASE IF EXISTS {self.name} WITH (FORCE)")
        shutil.rmtree(REPO_ROOT / self.storage, ignore_errors=True)

    def env(self):
        return {**os.environ, "SUPPLYLENS_MIGRATION_URL": self.owner_url, "SUPPLYLENS_DATABASE_URL": self.app_url,
                "SUPPLYLENS_ADMIN_DATABASE_URL": self.owner_url, "SUPPLYLENS_STORAGE_DIR": self.storage}

    def alembic(self, *args, script_dir: Path | None = None):
        ini = REPO_ROOT / "services" / "api" / "alembic.ini"
        if script_dir is not None:
            ini = script_dir / "alembic.ini"
        return subprocess.run([sys.executable, "-m", "alembic", "-c", str(ini), *args], env=self.env(),
                              capture_output=True, text=True, cwd=REPO_ROOT, timeout=300)

    def sql(self, query: str, **params):
        from sqlalchemy import create_engine
        eng = create_engine(self.owner_url)
        with eng.begin() as c:
            r = c.execute(text(query), params)
            return r.all() if r.returns_rows else None

    def version(self) -> str:
        return self.sql("SELECT version_num FROM alembic_version")[0][0]

    def workload(self) -> dict:
        out = subprocess.run([sys.executable, str(REPO_ROOT / "tests" / "rehearsal_workload.py")], env=self.env(),
                             capture_output=True, text=True, cwd=REPO_ROOT, timeout=300)
        assert out.returncode == 0, out.stderr[-1500:]
        return json.loads(out.stdout)

    def counts(self) -> dict:
        tid = tenant_id("demo")
        from sqlalchemy import create_engine
        eng = create_engine(self.owner_url)
        with eng.begin() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
            out = {n: c.execute(text(f"SELECT count(*) FROM {n}")).scalar()
                   for n in ("actions", "approvals", "outbox", "audit_events", "agent_runs", "agent_events")}
            out["sandbox_orders"] = c.execute(text("SELECT count(*) FROM sandbox_erp.purchase_orders")).scalar()
            # the open-order ledger lives in public at 0007+ and is parked in retired_0007 below it (never dropped)
            ledger = c.execute(text("SELECT COALESCE(to_regclass('public.purchase_order_lines'), "
                                    "to_regclass('retired_0007.purchase_order_lines'))::text")).scalar()
            out["open_order_lines"] = c.execute(text(f"SELECT count(*) FROM {ledger}")).scalar() if ledger else None
        return out


@pytest.fixture()
def scratch():
    with Scratch() as s:
        r = s.alembic("upgrade", "head")
        assert r.returncode == 0, r.stderr[-1500:]
        yield s


def broken_scripts(tmp: Path) -> Path:
    """A copy of the migrations plus a migration after HEAD that makes visible changes and then fails."""
    shutil.copytree(MIGRATIONS, tmp / "migrations")
    (tmp / "migrations" / "versions" / "9999_broken.py").write_text(textwrap.dedent(f'''
        """Rehearsal-only migration: changes data and schema, then fails midway."""
        from alembic import op

        revision = "9999"
        down_revision = "{HEAD}"


        def upgrade():
            op.execute("ALTER TABLE actions ADD COLUMN rehearsal_flag integer")
            op.execute("CREATE TABLE rehearsal_partial (x integer)")
            op.execute("UPDATE sandbox_erp.purchase_orders SET status = 'MIGRATED'")
            op.execute("SELECT 1/0")


        def downgrade():
            pass
    '''))
    (tmp / "alembic.ini").write_text(f"[alembic]\nscript_location = {tmp / 'migrations'}\nprepend_sys_path = {REPO_ROOT}\n"
                                     "[loggers]\nkeys = root\n[handlers]\nkeys = console\n[formatters]\nkeys = generic\n"
                                     "[logger_root]\nlevel = WARNING\nhandlers = console\n[handler_console]\n"
                                     "class = StreamHandler\nargs = (sys.stderr,)\nformatter = generic\n"
                                     "[formatter_generic]\nformat = %(levelname)s %(name)s %(message)s\n")
    return tmp


# ----------------------------------------------------------------------------- rehearsal 1: failed migration
def test_failed_migration_leaves_schema_data_orders_and_audit_untouched(scratch):
    before = scratch.workload()
    assert before["status"] == "RECONCILED" and before["counts"]["sandbox_orders"] == 1
    po_before = scratch.sql("SELECT po_number, status FROM sandbox_erp.purchase_orders")
    with tempfile.TemporaryDirectory() as td:
        script_dir = broken_scripts(Path(td))
        r = scratch.alembic("upgrade", "head", script_dir=script_dir)
    assert r.returncode != 0 and "division by zero" in r.stderr
    assert scratch.version() == HEAD                                                # version pointer did not move
    assert scratch.sql("SELECT count(*) FROM information_schema.columns "
                       "WHERE table_name='actions' AND column_name='rehearsal_flag'")[0][0] == 0     # DDL rolled back
    assert scratch.sql("SELECT to_regclass('rehearsal_partial')")[0][0] is None
    assert scratch.sql("SELECT po_number, status FROM sandbox_erp.purchase_orders") == po_before    # DML rolled back
    assert scratch.counts() == before["counts"]


# ----------------------------------------------------------------------------- rehearsal 2: deployment rollback
def test_rollback_to_previous_release_keeps_operational_records_and_audit(scratch):
    before = scratch.workload()
    assert before["counts"]["audit_events"] > 0
    assert before["counts"]["open_order_lines"] == 1           # the reconciled order entered the open-order ledger
    for previous in ("0008", "0007"):                          # one release back, then two (through the 0007 parking)
        r = scratch.alembic("downgrade", previous)
        assert r.returncode == 0, r.stderr[-800:]
        assert scratch.version() == previous
        assert scratch.counts() == before["counts"]           # orders, approvals, outbox and audit trail intact
        r = scratch.alembic("upgrade", "head")                # roll forward again
        assert r.returncode == 0, r.stderr[-800:]
        assert scratch.version() == HEAD and scratch.counts() == before["counts"]
    # the app role is still unable to rewrite history after the round trip
    from sqlalchemy import create_engine
    eng = create_engine(scratch.app_url)
    with eng.begin() as c, pytest.raises(Exception, match="permission denied"):
        c.execute(text("DELETE FROM audit_events"))


def test_rollback_refuses_to_destroy_deletion_certificates(scratch):
    scratch.workload()
    scratch.sql("""INSERT INTO tenants (id, slug, name, kind) VALUES (gen_random_uuid(), 'gone', 'Gone', 'customer')""")
    scratch.sql("""INSERT INTO tenant_deletions (id, tenant_id, tenant_slug, requested_by, certificate)
        SELECT gen_random_uuid(), t.id, 'gone', u.id, '{"rows_deleted": {}}'::jsonb FROM tenants t, users u
        WHERE t.slug = 'gone' LIMIT 1""")
    r = scratch.alembic("downgrade", "0004")
    assert r.returncode != 0 and "deletion certificates" in r.stderr
    assert scratch.version() == HEAD                          # the whole downgrade rolled back, including 0006-HEAD
    assert scratch.sql("SELECT count(*) FROM tenant_deletions")[0][0] == 1


def test_migrations_0006_and_0010_move_existing_vectors_and_change_no_value(scratch):
    """0006 moves vectors inline, 0010 into chunk_vectors; both copy under row-level security, per tenant, and the vector
    values are bit-for-bit unchanged, including after rolling 0010 back."""
    import psycopg
    from sqlalchemy import create_engine
    assert scratch.alembic("downgrade", "0005").returncode == 0
    tid, doc, ver = tenant_id("demo"), uuid.uuid4(), uuid.uuid4()
    scratch.sql("INSERT INTO tenants (id, slug, name, kind) VALUES (:i, 'demo', 'Demo', 'customer') ON CONFLICT DO NOTHING", i=tid)
    rng_vecs = [[((i * 7919 + j * 104729) % 2000 - 1000) / 997.0 for j in range(1024)] for i in range(40)]
    with create_engine(scratch.owner_url).begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
        c.execute(text("INSERT INTO documents (id, tenant_id, title, doc_type, source_kind) VALUES (:d,:t,'x','contract','generated')"),
                  {"d": doc, "t": tid})
        c.execute(text("""INSERT INTO document_versions (id, tenant_id, document_id, version_label, file_name, sha256, storage_key,
            known_at, valid_from, parser_version) VALUES (:v,:t,:d,'v1','f',:h,'k',now(),'2011-01-01','p')"""),
                  {"v": ver, "t": tid, "d": doc, "h": uuid.uuid4().hex})
        for i, vec in enumerate(rng_vecs):
            c.execute(text("INSERT INTO chunks (id, tenant_id, version_id, ordinal, section, char_start, char_end, body, embedding) "
                           "VALUES (gen_random_uuid(), :t, :v, :o, 's', 0, 1, 'body', CAST(:e AS vector))"),
                      {"t": tid, "v": ver, "o": i, "e": "[" + ",".join(f"{x:.6f}" for x in vec) + "]"})

    def snapshot():
        with create_engine(scratch.owner_url).begin() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
            return c.execute(text("SELECT md5(string_agg(embedding::text, '|' ORDER BY ordinal)), count(*) FROM chunks")).one()

    def toast_rows():
        with psycopg.connect(dbname=scratch.name, autocommit=True) as c:
            toast = c.execute("SELECT reltoastrelid::regclass::text FROM pg_class WHERE oid = 'chunks'::regclass").fetchone()[0]
            return c.execute(f"SELECT count(*) FROM {toast}").fetchone()[0]

    before, toasted_before = snapshot(), toast_rows()
    assert before[1] == 40 and toasted_before > 0                         # at 0005 the vectors live in TOAST
    r = scratch.alembic("upgrade", "0009")
    assert r.returncode == 0, r.stderr[-800:]
    assert snapshot() == before                                           # identical values, none lost
    assert toast_rows() == 0                                              # all inline now
    storage = dict(scratch.sql("SELECT attname, attstorage::text FROM pg_attribute WHERE attrelid='chunks'::regclass "
                               "AND attname IN ('embedding','body','tsv')"))
    assert storage == {"embedding": "p", "body": "m", "tsv": "m"}
    assert scratch.sql("SELECT count(*) FROM pg_indexes WHERE indexname IN ('sales_daily_tenant_day','supplier_terms_tenant_sku')")[0][0] == 2

    # 0010: the vectors move to chunk_vectors, bit for bit, under the same row-level security; chunks loses the column.
    def moved():
        with create_engine(scratch.owner_url).begin() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
            return c.execute(text("""SELECT md5(string_agg(v.embedding::text, '|' ORDER BY c.ordinal)), count(*)
                                     FROM chunks c JOIN chunk_vectors v ON v.chunk_id = c.id""")).one()
    r = scratch.alembic("upgrade", "head")
    assert r.returncode == 0, r.stderr[-800:]
    assert moved() == before
    assert scratch.sql("SELECT count(*) FROM pg_attribute WHERE attrelid='chunks'::regclass AND attname='embedding' "
                       "AND NOT attisdropped")[0][0] == 0
    assert scratch.sql("SELECT relforcerowsecurity FROM pg_class WHERE oid='chunk_vectors'::regclass")[0][0] is True
    assert scratch.sql("SELECT attstorage::text FROM pg_attribute WHERE attrelid='chunk_vectors'::regclass "
                       "AND attname='embedding'")[0][0] == "p"
    r = scratch.alembic("downgrade", "0009")                              # rollback restores the column and every value
    assert r.returncode == 0, r.stderr[-800:]
    assert snapshot() == before
    assert scratch.alembic("upgrade", "head").returncode == 0


# ----------------------------------------------------------------------------- shared invariants
def assert_orders_accounted(tid):
    """Every sandbox order maps to exactly one action of the tenant; no operation key is duplicated."""
    with tenant_session(tid) as s:
        actions = {str(r.id): r for r in s.execute(text("SELECT id, status, external_ref FROM actions"))}
    with admin_engine().connect() as c:
        orders = c.execute(text("SELECT po_number, idempotency_key, caller_ref FROM sandbox_erp.purchase_orders")).all()
    ours = [o for o in orders if o.caller_ref in actions]
    assert len({o.idempotency_key for o in ours}) == len(ours), "duplicate order for one operation key"
    assert len({o.caller_ref for o in ours}) == len(ours), "two orders for one action"
    for o in ours:
        assert actions[o.caller_ref].external_ref in (o.po_number, None)
    for a in actions.values():
        if a.status in ("RECONCILED", "CONFIRMED"):
            assert any(o.po_number == a.external_ref for o in ours), "action claims an order the target does not hold"
    return len(ours)


def login(c, role):
    c.post("/api/v1/auth/dev-login", json={"email": f"{role}@dev.supplylens.local"}, headers={"X-Requested-With": "supplylens"})


@pytest.fixture()
def world(clean_db):
    seed()
    demo.load(tenant_id("demo"))
    with admin_engine().begin() as c:
        c.execute(text("TRUNCATE alerts, rate_limit_buckets, idempotency_keys"))
    return TestClient(app)


def approved_action(c, tag):
    login(c, "planner")
    run_id = c.post("/api/v1/agent-runs", json=RUN, headers={**DEMO, "Idempotency-Key": f"{tag}-run-{uuid.uuid4().hex}"}).json()["run_id"]
    for _ in range(10):
        tick()
        d = c.get(f"/api/v1/agent-runs/{run_id}", headers=DEMO).json()
        if d["status"] not in ("QUEUED", "RUNNING"):
            break
    action = c.get(f"/api/v1/actions/{d['actions'][0]['id']}", headers=DEMO).json()
    login(c, "approver")
    r = c.post(f"/api/v1/actions/{action['id']}/approve", headers={**DEMO, "Idempotency-Key": f"{tag}-ap-{uuid.uuid4().hex}"},
               json={"payload_hash": action["payload_hash"], "expected_row_version": action["row_version"]})
    assert r.status_code == 200
    return action["id"]


# ----------------------------------------------------------------------------- rehearsal 3: connector outage
def test_connector_outage_then_recovery_creates_exactly_one_order(world):
    c, t = world, tenant_id("demo")
    aid = approved_action(c, "outage")
    with tenant_session(t) as s:
        audit_before = s.execute(text("SELECT count(*) FROM audit_events")).scalar()
    # the ERP is down: every attempt is refused before it commits, until the retry budget is spent
    for _ in range(5):
        sandbox_erp.inject_fault(f"po-{aid}", "fail_before_commit")
        with tenant_session(t) as s:
            s.execute(text("UPDATE outbox SET next_attempt_at = now() WHERE status='PENDING'"))
        svc.dispatch_once(t, "rehearsal")
    a = c.get(f"/api/v1/actions/{aid}", headers=DEMO).json()
    assert a["status"] == "FAILED" and a["outbox"]["attempts"] == 5
    assert assert_orders_accounted(t) == 0                                           # nothing was created remotely
    with tenant_session(t) as s:
        dispatch_audit = s.execute(text("SELECT count(*) FROM audit_events WHERE action LIKE 'dispatch.%'")).scalar()
        assert s.execute(text("SELECT count(*) FROM audit_events")).scalar() > audit_before
        alert = s.execute(text("SELECT kind, status FROM alerts WHERE dedupe_key = :k"),
                          {"k": f"failed_reconciliation:{aid}"}).first()
    assert dispatch_audit >= 5 and alert and alert.status == "OPEN"                  # every attempt left evidence
    # the connector returns: a planner or approver re-queues under the same key
    login(c, "viewer")
    assert c.post(f"/api/v1/actions/{aid}/retry", headers={**DEMO, "Idempotency-Key": "rt-v"}).status_code == 403
    login(c, "approver")
    assert c.post(f"/api/v1/actions/{aid}/retry", headers={**DEMO, "Idempotency-Key": "rt-1"}).status_code == 200
    tick()
    a = c.get(f"/api/v1/actions/{aid}", headers=DEMO).json()
    assert a["status"] == "RECONCILED"
    assert assert_orders_accounted(t) == 1
    with tenant_session(t) as s:
        assert s.execute(text("SELECT status FROM alerts WHERE dedupe_key = :k"), {"k": f"failed_reconciliation:{aid}"}).scalar() == "RESOLVED"
    # retrying something that is not failed, or whose remote order exists, is refused
    r = c.post(f"/api/v1/actions/{aid}/retry", headers={**DEMO, "Idempotency-Key": "rt-2"})
    assert r.status_code == 409 and r.json()["code"] == "invalid_state"


def test_retry_refused_when_the_remote_order_already_exists(world):
    c, t = world, tenant_id("demo")
    aid = approved_action(c, "dup")
    for _ in range(5):          # response lost every time, but the order is committed on the first attempt
        sandbox_erp.inject_fault(f"po-{aid}", "timeout_after_commit")
        with tenant_session(t) as s:
            s.execute(text("UPDATE outbox SET next_attempt_at = now() WHERE status='PENDING'"))
        svc.dispatch_once(t, "rehearsal")
        if c.get(f"/api/v1/actions/{aid}", headers=DEMO).json()["status"] == "UNKNOWN_OUTCOME":
            break
    # force the FAILED state a crashed retry loop could leave behind, with the remote order present
    with tenant_session(t) as s:
        s.execute(text("UPDATE outbox SET status='FAILED' WHERE action_id=:a"), {"a": aid})
        s.execute(text("UPDATE actions SET status='FAILED' WHERE id=:a"), {"a": aid})
    r = c.post(f"/api/v1/actions/{aid}/retry", headers={**DEMO, "Idempotency-Key": "rt-dup"})
    assert r.status_code == 409 and r.json()["code"] == "remote_order_exists"
    assert assert_orders_accounted(t) == 1


# ----------------------------------------------------------------------------- rehearsal 4: model outage
def test_embedding_outage_degrades_retrieval_but_the_workflow_still_completes(world, monkeypatch):
    """There is no generative LLM. The model dependency that can fail is the embedding service: retrieval must
    fall back to lexical search, say so, and the investigation must still produce a cited, approvable draft."""
    c, t = world, tenant_id("demo")
    with tenant_session(t) as s:    # pretend vectors exist so the outage matters
        s.execute(text("INSERT INTO chunk_vectors (chunk_id, tenant_id, version_id, embedding) SELECT id, tenant_id, version_id, "
                       "(SELECT array_agg(0.001)::vector(1024) FROM generate_series(1,1024)) FROM chunks "
                       "WHERE id NOT IN (SELECT chunk_id FROM chunk_vectors) LIMIT 2"))
    monkeypatch.setattr("supplylens.knowledge.embed.embed", lambda *a, **k: None)
    monkeypatch.setattr("supplylens.knowledge.retrieve.embed", lambda *a, **k: None)
    login(c, "viewer")
    ev = c.get("/api/v1/evidence/search", params={"q": "minimum order quantity DEMO-REF-SKU"}, headers=DEMO).json()
    assert ev["mode"] == "lexical_only" and ev["degraded"] and ev["results"]
    aid = approved_action(c, "emb")
    tick()
    assert c.get(f"/api/v1/actions/{aid}", headers=DEMO).json()["status"] == "RECONCILED"
    assert assert_orders_accounted(t) == 1
    login(c, "tenant_admin")
    c.post("/api/v1/alerts/evaluate", headers=DEMO)
    q = c.get("/api/v1/alerts", headers=DEMO).json()["alerts"]
    assert any(a["kind"] == "model_unavailable" and a["dedupe_key"] == "model_unavailable:embeddings" for a in q)
