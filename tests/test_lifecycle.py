"""BUS-023: tenant export and deletion over real data, end to end through the API and the worker."""
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from supplylens import lifecycle
from supplylens.api.app import app
from supplylens.config import settings
from supplylens.db import admin_engine, control_session, tenant_session
from supplylens.seed import create_tenant, tenant_id
from supplylens.simulation import demo
from supplylens_worker.main import tick

SLUG = "lifecycle-customer"
H = {"X-Requested-With": "supplylens", "X-SupplyLens-Tenant": SLUG}
RUN = {"mode": "draft", "sku_ids": ["DEMO-REF-SKU"], "knowledge_cutoff": "2026-10-20T09:00:00Z",
       "effective_date": "2026-10-20", "budget_minor": 18000, "currency": "USD", "allow_shortfall": False}


def login(c, role):
    r = c.post("/api/v1/auth/dev-login", json={"email": f"{role}@dev.supplylens.local"},
               headers={"X-Requested-With": "supplylens"})
    assert r.status_code == 200


def drop_tenant(slug):
    """Test cleanup of control-plane rows (the product never removes the tenant row itself)."""
    tid = tenant_id(slug)
    with admin_engine().begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
        for t in reversed(lifecycle.tenant_tables(c)):
            c.execute(text(f'DELETE FROM "{t}" WHERE tenant_id=:t'), {"t": tid})
        c.execute(text("DELETE FROM tenant_deletions WHERE tenant_id=:t"), {"t": tid})
        c.execute(text("DELETE FROM memberships WHERE tenant_id=:t"), {"t": tid})
        c.execute(text("DELETE FROM tenants WHERE id=:t"), {"t": tid})


@pytest.fixture()
def customer():
    drop_tenant(SLUG)
    tid = create_tenant(SLUG, "Lifecycle customer", "customer")
    demo.load(tid)
    c = TestClient(app)
    # create realistic operational records: a run, a prepared + approved + dispatched order, audit, jobs
    login(c, "planner")
    run_id = c.post("/api/v1/agent-runs", json=RUN, headers={**H, "Idempotency-Key": "lc-run"}).json()["run_id"]
    tick()
    detail = c.get(f"/api/v1/agent-runs/{run_id}", headers=H).json()
    action = c.get(f"/api/v1/actions/{detail['actions'][0]['id']}", headers=H).json()
    login(c, "approver")
    r = c.post(f"/api/v1/actions/{action['id']}/approve", headers={**H, "Idempotency-Key": "lc-appr"},
               json={"payload_hash": action["payload_hash"], "expected_row_version": action["row_version"]})
    assert r.status_code == 200
    tick()
    yield {"client": c, "tid": tid, "action_id": action["id"]}
    drop_tenant(SLUG)


def counts(tid):
    with tenant_session(tid) as s:
        return {t: s.execute(text(f'SELECT count(*) FROM "{t}"')).scalar() for t in lifecycle.tenant_tables(s.connection())}


def request_export(c, include_vectors=False):
    login(c, "tenant_admin")
    r = c.post("/api/v1/admin/exports", json={"include_vectors": include_vectors}, headers={**H, "Idempotency-Key": f"ex-{include_vectors}"})
    assert r.status_code == 202, r.text
    tick()
    ex = [e for e in c.get("/api/v1/admin/exports", headers=H).json() if e["id"] == r.json()["export_id"]][0]
    return ex


def test_export_is_verified_and_reconciles_with_the_database(customer):
    c, tid = customer["client"], customer["tid"]
    ex = request_export(c)
    assert ex["status"] == "READY" and ex["manifest"]["verified"] is True
    live = counts(tid)
    for t in ("actions", "approvals", "outbox", "audit_events", "document_versions", "chunks", "supplier_terms"):
        assert ex["manifest"]["tables"][t] > 0
    # Everything exported since the snapshot except the export bookkeeping itself must reconcile with live counts.
    resp = c.get(f"/api/v1/admin/exports/{ex['id']}/download", headers=H)
    assert resp.status_code == 200 and hashlib.sha256(resp.content).hexdigest() == ex["sha256"]
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        manifest = json.loads(z.read("manifest.json"))
        assert lifecycle.verify_archive(Path(settings.storage_path / f"exports/{tid}/{ex['id']}.zip")) == []
        docs = [n for n in z.namelist() if n.startswith("documents/")]
        assert len(docs) == manifest["documents"]["count"] > 0
        rows = [json.loads(line) for line in z.read("tables/actions.ndjson").splitlines()]
        assert {r["id"] for r in rows} == {customer["action_id"]}
        assert "embedding" not in json.loads(z.read("tables/chunks.ndjson").splitlines()[0])
    # Rows written after the snapshot (the export's own job/audit bookkeeping) are the only differences.
    diffs = lifecycle.reconcile_export(tid, manifest)
    assert set(diffs) <= {"jobs", "audit_events"}, diffs
    assert manifest["vectors"]["included"] is False and manifest["caches"]["idempotency_keys"]["exported"] is False
    assert live["actions"] == manifest["tables"]["actions"]["rows"]


def test_export_with_vectors_includes_embeddings_when_present(customer):
    c, tid = customer["client"], customer["tid"]
    with tenant_session(tid) as s:
        # Start from a known state: with a local embedding service running, ingestion already embeds every chunk.
        s.execute(text("DELETE FROM chunk_vectors"))
        s.execute(text("INSERT INTO chunk_vectors (chunk_id, tenant_id, version_id, embedding) SELECT id, tenant_id, "
                       "version_id, (SELECT array_agg(0.001)::vector(1024) FROM generate_series(1, 1024)) "
                       "FROM chunks ORDER BY id LIMIT 3"))
    ex = request_export(c, include_vectors=True)
    assert ex["status"] == "READY" and ex["manifest"]["vectors"] == {
        "chunks_with_embedding": 3, "included": True, "note": "in tables/chunks.ndjson"}
    zbytes = c.get(f"/api/v1/admin/exports/{ex['id']}/download", headers=H).content
    with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
        embedded = [json.loads(x) for x in z.read("tables/chunks.ndjson").splitlines()]
        assert sum(1 for r in embedded if r.get("embedding")) == 3


def test_tampered_archive_fails_verification(customer, tmp_path):
    c, tid = customer["client"], customer["tid"]
    ex = request_export(c)
    src = settings.storage_path / f"exports/{tid}/{ex['id']}.zip"
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(bad, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "tables/actions.ndjson":
                data = data.replace(b"PENDING", b"PENDINX")[:-1] + b"\n" if b"PENDING" in data else data + b"{}\n"
            zout.writestr(item.filename, data)
    problems = lifecycle.verify_archive(bad)
    assert any("actions" in p for p in problems)


def test_only_admins_export_and_viewers_cannot(customer):
    c = customer["client"]
    for role in ("viewer", "planner", "approver"):
        login(c, role)
        assert c.post("/api/v1/admin/exports", json={}, headers={**H, "Idempotency-Key": f"x-{role}"}).status_code == 403


def test_deletion_requires_confirmation_and_a_downloaded_export(customer):
    c = customer["client"]
    login(c, "tenant_admin")
    body = {"confirm_slug": SLUG, "export_id": "00000000-0000-0000-0000-000000000000", "reason": "customer offboarding"}
    r = c.post("/api/v1/admin/tenant-deletion", json=body, headers={**H, "Idempotency-Key": "d1"})
    assert r.status_code == 422 and r.json()["code"] == "export_required"
    ex = request_export(c)
    r = c.post("/api/v1/admin/tenant-deletion", json={**body, "export_id": ex["id"], "confirm_slug": "wrong"},
               headers={**H, "Idempotency-Key": "d2"})
    assert r.status_code == 422 and r.json()["code"] == "confirmation_mismatch"
    r = c.post("/api/v1/admin/tenant-deletion", json={**body, "export_id": ex["id"]}, headers={**H, "Idempotency-Key": "d3"})
    assert r.status_code == 422 and r.json()["code"] == "export_not_downloaded"
    for role in ("planner", "approver", "viewer"):
        login(c, role)
        assert c.post("/api/v1/admin/tenant-deletion", json={**body, "export_id": ex["id"]},
                      headers={**H, "Idempotency-Key": f"d4{role}"}).status_code == 403
    assert counts(customer["tid"])["actions"] == 1   # nothing was deleted


def test_research_and_demo_workspaces_cannot_be_deleted():
    c = TestClient(app)
    login(c, "tenant_admin")
    r = c.post("/api/v1/admin/tenant-deletion", json={"confirm_slug": "demo", "reason": "should be refused",
                                                      "export_id": "00000000-0000-0000-0000-000000000000"},
               headers={"X-Requested-With": "supplylens", "X-SupplyLens-Tenant": "demo", "Idempotency-Key": "dd"})
    assert r.status_code == 422 or r.status_code == 403
    with pytest.raises(lifecycle.LifecycleError) as e:
        lifecycle.check_deletable(tenant_id("demo"), "00000000-0000-0000-0000-000000000000")
    assert e.value.code == "deletion_not_allowed"


def test_full_deletion_removes_everything_and_leaves_a_certificate(customer):
    c, tid = customer["client"], customer["tid"]
    ex = request_export(c)
    c.get(f"/api/v1/admin/exports/{ex['id']}/download", headers=H)
    with tenant_session(tid) as s:
        docs_dir = settings.storage_path / "documents" / str(tid)
        assert docs_dir.exists()
        assert s.execute(text("SELECT count(*) FROM actions")).scalar() == 1
    with admin_engine().connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM sandbox_erp.purchase_orders WHERE caller_ref=:a"),
                            {"a": customer["action_id"]}).scalar() == 1
    before = counts(tid)
    r = c.post("/api/v1/admin/tenant-deletion", headers={**H, "Idempotency-Key": "del-1"},
               json={"confirm_slug": SLUG, "export_id": ex["id"], "reason": "customer offboarding request #42"})
    assert r.status_code == 202, r.text
    deletion_id = r.json()["deletion_id"]
    tick()

    cert = c.get(f"/api/v1/deletions/{deletion_id}").json()
    assert cert["tenant_slug"] == SLUG and cert["certificate"]["rows_remaining"] == {}
    deleted = cert["certificate"]["rows_deleted"]
    for t in ("actions", "approvals", "outbox", "chunks", "document_versions", "supplier_terms"):
        assert deleted[t] == before[t] > 0, t
    assert deleted["audit_events"] > 0
    assert deleted["sandbox_erp.purchase_orders"] == 1
    assert cert["certificate"]["files_removed"]["documents"] > 0 and "backups" in cert["certificate"]
    # nothing left: tables, sandbox orders, document bytes, exports, workspace access
    left = {t: n for t, n in counts(tid).items() if n}
    assert left == {"jobs": 1}, left          # the deletion job's own completion receipt (audit rows purged too)
    assert cert["certificate"]["audit_events_deleted"] > before["audit_events"]   # incl. the deletion request itself
    with admin_engine().connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM sandbox_erp.purchase_orders WHERE caller_ref=:a"),
                            {"a": customer["action_id"]}).scalar() == 0
    assert not (settings.storage_path / "documents" / str(tid)).exists()
    assert not (settings.storage_path / "exports" / str(tid)).exists()
    assert c.get("/api/v1/actions", headers=H).status_code == 404            # workspace no longer resolves
    me = c.get("/api/v1/me").json()
    assert SLUG not in [m["slug"] for m in me["memberships"]]
    with control_session() as s:
        assert s.execute(text("SELECT count(*) FROM memberships WHERE tenant_id=:t"), {"t": tid}).scalar() == 0
        assert s.execute(text("SELECT deleted_at IS NOT NULL FROM tenants WHERE id=:t"), {"t": tid}).scalar()
    # other workspaces untouched
    login(c, "viewer")
    assert c.get("/api/v1/documents", headers={**H, "X-SupplyLens-Tenant": "demo"}).status_code == 200


def test_backup_restore_then_reapply_deletion(customer):
    """A backup taken before deletion brings the data back; reapply_deletions removes it again."""
    c, tid = customer["client"], customer["tid"]
    ex = request_export(c)
    c.get(f"/api/v1/admin/exports/{ex['id']}/download", headers=H)
    c.post("/api/v1/admin/tenant-deletion", headers={**H, "Idempotency-Key": "del-2"},
           json={"confirm_slug": SLUG, "export_id": ex["id"], "reason": "offboarding with restore rehearsal"})
    tick()
    assert {t for t, n in counts(tid).items() if n} == {"jobs"}
    # simulate the restore of pre-deletion rows
    with tenant_session(tid) as s:
        s.execute(text("INSERT INTO products (tenant_id, sku_id, description, unit, source_kind) "
                       "VALUES (:t,'RESTORED-1','came back from backup','unit','generated')"), {"t": tid})
        s.execute(text("INSERT INTO audit_events (tenant_id, action, entity, entity_id, detail) "
                       "VALUES (:t,'restored.event','x','1','{}')"), {"t": tid})
    out = lifecycle.reapply_deletions()
    assert out[str(tid)]["reappeared"]["products"] == 1 and out[str(tid)]["reappeared"]["audit_events"] >= 1
    with admin_engine().begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
        assert c.execute(text("SELECT count(*) FROM audit_events WHERE tenant_id=:t"), {"t": tid}).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM products WHERE tenant_id=:t"), {"t": tid}).scalar() == 0
    # the ledger form works even when the control-plane record was lost with the restore
    out2 = lifecycle.reapply_deletions([str(tid)])
    assert out2 == {}
