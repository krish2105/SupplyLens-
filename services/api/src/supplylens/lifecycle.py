"""Tenant export and deletion (BUS-023).

Export writes one ZIP per request from a single REPEATABLE READ snapshot: every tenant table as NDJSON, every
stored document by SHA-256, optionally the embedding vectors, and a manifest with per-file row counts and hashes.
The archive is re-opened and verified before the export is marked READY.

Deletion removes every tenant row (tables are discovered from the catalog, so new tables are covered
automatically), document bytes, exports, tenant-scoped model artifacts and caches, then proves the tenant is empty
and records a certificate in the control plane. Only customer workspaces can be deleted, only after the customer
has downloaded a verified export. Backups taken before a deletion still contain the data until the operator purges
them; `reapply_deletions` re-deletes tenants after a restore from such a backup.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import text

from .config import REPO_ROOT, settings
from .db import app_engine, tenant_session

EXPORT_FORMAT = "supplylens-export/1"
CACHE_TABLES = ("rate_limit_buckets", "idempotency_keys")
NOT_EXPORTED = set(CACHE_TABLES) | {"tenant_exports"}
EXPORT_MAX_AGE = timedelta(days=7)
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
BACKUP_NOTE = ("Logical dumps and any volume snapshots taken before this deletion still contain this workspace's "
               "data until the operator purges them per their retention policy. After restoring such a backup run "
               "`python -m supplylens.lifecycle reapply-deletions` to delete the workspace again.")


class LifecycleError(Exception):
    def __init__(self, code: str, message: str, http: int = 409):
        super().__init__(message)
        self.code, self.http = code, http


# ------------------------------------------------------------------------------------------ catalog
def tenant_tables(conn) -> list[str]:
    """Row-level-secured tables carrying tenant_id, parents before children (foreign-key order)."""
    names = [r[0] for r in conn.execute(text("""
        SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id' AND NOT a.attisdropped
        WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relrowsecurity ORDER BY c.relname"""))]
    if not all(_IDENT.match(n) for n in names):      # guards the identifiers interpolated into SQL below; must survive python -O
        raise RuntimeError(f"unexpected table name in the tenant catalog: {names}")
    edges = conn.execute(text("""
        SELECT conrelid::regclass::text, confrelid::regclass::text FROM pg_constraint
        WHERE contype = 'f' AND connamespace = 'public'::regnamespace""")).all()
    parents = {n: set() for n in names}
    for child, parent in edges:
        if child in parents and parent in parents and child != parent:
            parents[child].add(parent)
    ordered: list[str] = []
    ready = sorted(n for n, p in parents.items() if not p)
    while ready:
        n = ready.pop(0)
        ordered.append(n)
        for m in sorted(parents):
            if n in parents[m]:
                parents[m].discard(n)
                if not parents[m] and m not in ordered and m not in ready:
                    ready.append(m)
    return ordered + sorted(set(names) - set(ordered))   # cycles (none today) fall back to name order


def _pk_order(conn, table: str) -> str:
    cols = [r[0] for r in conn.execute(text("""
        SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY (i.indkey)
        WHERE i.indrelid = CAST(:t AS regclass) AND i.indisprimary ORDER BY array_position(i.indkey, a.attnum)"""),
        {"t": f"public.{table}"})]
    return (" ORDER BY " + ", ".join(f'"{c}"' for c in cols)) if cols else ""


# ------------------------------------------------------------------------------------------ export
def _storage_file(key: str) -> Path:
    root = settings.storage_path.resolve()
    p = (root / key).resolve()
    if not p.is_relative_to(root):
        raise LifecycleError("bad_storage_key", f"storage key escapes the storage root: {key}")
    return p


def export_paths(tenant_id, export_id) -> tuple[Path, str]:
    rel = f"exports/{tenant_id}/{export_id}.zip"
    return settings.storage_path / rel, rel


def run_export(tenant_id, export_id) -> dict:
    with tenant_session(tenant_id) as s:
        row = s.execute(text("SELECT include_vectors FROM tenant_exports WHERE id=:i"), {"i": export_id}).first()
        if row is None:
            raise LifecycleError("not_found", "export not found", 404)
        s.execute(text("UPDATE tenant_exports SET status='RUNNING', error=NULL WHERE id=:i"), {"i": export_id})
    include_vectors = row.include_vectors
    dest, rel = export_paths(tenant_id, export_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(".zip.part")
    try:
        manifest = _write_archive(tenant_id, export_id, include_vectors, part)
        problems = verify_archive(part)
        if problems:
            raise LifecycleError("verification_failed", "; ".join(problems))
        part.replace(dest)
        digest = _sha256_file(dest)
        manifest["verified"] = True
        with tenant_session(tenant_id) as s:
            s.execute(text("""UPDATE tenant_exports SET status='READY', file_path=:p, bytes=:b, sha256=:h,
                manifest=CAST(:m AS jsonb), finished_at=now() WHERE id=:i"""),
                      {"p": rel, "b": dest.stat().st_size, "h": digest, "m": json.dumps(manifest), "i": export_id})
        return {"export_id": str(export_id), "bytes": dest.stat().st_size, "sha256": digest,
                "rows": sum(t["rows"] for t in manifest["tables"].values())}
    except Exception as e:
        part.unlink(missing_ok=True)
        with tenant_session(tenant_id) as s:
            s.execute(text("UPDATE tenant_exports SET status='FAILED', error=:e, finished_at=now() WHERE id=:i"),
                      {"e": f"{type(e).__name__}: {e}"[:500], "i": export_id})
        raise


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _write_archive(tenant_id, export_id, include_vectors: bool, part: Path) -> dict:
    manifest: dict = {"format": EXPORT_FORMAT, "export_id": str(export_id), "tenant_id": str(tenant_id),
                      "created_at": datetime.now(UTC).isoformat(), "snapshot": "REPEATABLE READ",
                      "include_vectors": include_vectors, "tables": {}, "documents": {}, "vectors": {}, "caches": {}}
    with app_engine().connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        manifest["tenant_slug"] = conn.execute(text("SELECT slug FROM tenants WHERE id=:t"), {"t": tenant_id}).scalar()
        tables = tenant_tables(conn)
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            for t in tables:
                if t in CACHE_TABLES:
                    manifest["caches"][t] = {"rows": conn.execute(text(f'SELECT count(*) FROM "{t}"')).scalar(),
                                             "exported": False, "note": "transient; cleared on deletion"}
                    continue
                if t in NOT_EXPORTED:
                    continue
                expr = "to_jsonb(t)"
                if t == "chunks":
                    expr = ("to_jsonb(t) - 'embedding'" + (" || jsonb_build_object('embedding', t.embedding::text)"
                                                           if include_vectors else ""))
                expected = conn.execute(text(f'SELECT count(*) FROM "{t}"')).scalar()
                h, n, nbytes = hashlib.sha256(), 0, 0
                res = conn.execution_options(stream_results=True).execute(
                    text(f'SELECT ({expr})::text FROM "{t}" t{_pk_order(conn, t)}'))
                with z.open(f"tables/{t}.ndjson", "w", force_zip64=True) as f:
                    for (line,) in res:
                        b = (line + "\n").encode()
                        f.write(b)
                        h.update(b)
                        n += 1
                        nbytes += len(b)
                if n != expected:
                    raise LifecycleError("count_mismatch", f"{t}: wrote {n} rows but the snapshot holds {expected}")
                manifest["tables"][t] = {"rows": n, "bytes": nbytes, "sha256": h.hexdigest()}
            manifest["vectors"] = {
                "chunks_with_embedding": conn.execute(text("SELECT count(*) FROM chunks WHERE embedding IS NOT NULL")).scalar(),
                "included": include_vectors,
                "note": "embedding vectors are rebuildable from documents" if not include_vectors else "in tables/chunks.ndjson"}
            docs = conn.execute(text("SELECT DISTINCT sha256, storage_key FROM document_versions ORDER BY sha256")).all()
            total = 0
            for digest, key in docs:
                data = _storage_file(key).read_bytes()
                if hashlib.sha256(data).hexdigest() != digest:
                    raise LifecycleError("document_corrupt", f"stored document {digest[:12]} does not match its hash")
                z.writestr(f"documents/{digest}", data)
                total += len(data)
            manifest["documents"] = {"count": len(docs), "bytes": total, "missing": 0}
            z.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def verify_archive(path: Path) -> list[str]:
    """Re-open the archive and check every file against the manifest: row counts, hashes, document bytes."""
    problems: list[str] = []
    with zipfile.ZipFile(path) as z:
        if z.testzip():
            problems.append("archive CRC failure")
        manifest = json.loads(z.read("manifest.json"))
        for t, info in manifest["tables"].items():
            h, n = hashlib.sha256(), 0
            with z.open(f"tables/{t}.ndjson") as f:
                for line in f:
                    h.update(line)
                    n += 1
            if n != info["rows"]:
                problems.append(f"{t}: {n} rows in archive, manifest says {info['rows']}")
            if h.hexdigest() != info["sha256"]:
                problems.append(f"{t}: hash mismatch")
        names = set(z.namelist())
        for digest in {n.split("/", 1)[1] for n in names if n.startswith("documents/")}:
            if hashlib.sha256(z.read(f"documents/{digest}")).hexdigest() != digest:
                problems.append(f"document {digest[:12]} corrupt in archive")
        if len([n for n in names if n.startswith("documents/")]) != manifest["documents"]["count"]:
            problems.append("document count differs from manifest")
    return problems


def reconcile_export(tenant_id, manifest: dict) -> dict[str, tuple[int, int]]:
    """Current live row counts against an export manifest: {table: (exported, live)} for every difference."""
    diffs = {}
    with tenant_session(tenant_id) as s:
        for t, info in manifest["tables"].items():
            live = s.execute(text(f'SELECT count(*) FROM "{t}"')).scalar()
            if live != info["rows"]:
                diffs[t] = (info["rows"], live)
    return diffs


# ------------------------------------------------------------------------------------------ deletion
PRIVILEGED = ("audit_events",)   # append-only for the app role; removed by sl_finalize_tenant_deletion


def _purge_rows(tenant_id, keep_job_id=None, engine=None) -> dict[str, int]:
    """Delete every tenant row (children first). Returns rows deleted per table. Append-only tables are left to
    sl_finalize_tenant_deletion unless an owner-role `engine` is supplied (operator re-deletion after a restore)."""
    deleted: dict[str, int] = {}
    with tenant_session(tenant_id, engine) as s:
        tables = tenant_tables(s.connection())
        action_ids = [str(r[0]) for r in s.execute(text("SELECT id FROM actions"))]
        if action_ids:
            deleted["sandbox_erp.purchase_orders"] = s.execute(
                text("DELETE FROM sandbox_erp.purchase_orders WHERE caller_ref = ANY(:a)"), {"a": action_ids}).rowcount
        for t in reversed(tables):
            if t in PRIVILEGED and engine is None:
                continue
            if t == "jobs" and keep_job_id:
                n = s.execute(text('DELETE FROM jobs WHERE tenant_id=:t AND id <> :j'),
                              {"t": tenant_id, "j": keep_job_id}).rowcount
            else:
                n = s.execute(text(f'DELETE FROM "{t}" WHERE tenant_id=:t'), {"t": tenant_id}).rowcount
            deleted[t] = n
    return deleted


def _remaining(tenant_id, keep_job_id=None, engine=None) -> dict[str, int]:
    out = {}
    with tenant_session(tenant_id, engine) as s:
        for t in tenant_tables(s.connection()):
            if t in PRIVILEGED and engine is None:
                continue
            n = s.execute(text(f'SELECT count(*) FROM "{t}"')).scalar()
            if t == "jobs" and keep_job_id:
                n -= 1
            if n:
                out[t] = n
    return out


def _purge_files(tenant_id) -> dict[str, int]:
    root = settings.storage_path.resolve()
    counts = {}
    for kind in ("documents", "exports"):
        d = (root / kind / str(tenant_id)).resolve()
        counts[kind] = sum(1 for p in d.rglob("*") if p.is_file()) if d.exists() and d.is_relative_to(root) else 0
        if d.exists() and d.is_relative_to(root):
            shutil.rmtree(d)
    art = (REPO_ROOT / "artifacts" / "tenants" / str(tenant_id))
    counts["model_artifacts"] = sum(1 for p in art.rglob("*") if p.is_file()) if art.exists() else 0
    if art.exists():
        shutil.rmtree(art)
    return counts


def check_deletable(tenant_id, export_id) -> dict:
    with tenant_session(tenant_id) as s:
        kind = s.execute(text("SELECT kind FROM tenants WHERE id=:t"), {"t": tenant_id}).scalar()
        ex = s.execute(text("SELECT status, downloaded_at, finished_at FROM tenant_exports WHERE id=:i"),
                       {"i": export_id}).first()
    if kind != "customer":
        raise LifecycleError("deletion_not_allowed", "only customer workspaces can be deleted", 403)
    if ex is None or ex.status != "READY":
        raise LifecycleError("export_required", "a verified, completed export is required before deletion", 422)
    if ex.downloaded_at is None:
        raise LifecycleError("export_not_downloaded", "download the export before deleting the workspace", 422)
    if datetime.now(UTC) - ex.finished_at > EXPORT_MAX_AGE:
        raise LifecycleError("export_too_old", "the export is older than 7 days; create a fresh one", 422)
    return {"kind": kind}


def run_deletion(tenant_id, deletion_id, requested_by, export_id, job_id=None) -> dict:
    check_deletable(tenant_id, export_id)
    with tenant_session(tenant_id) as s:
        slug = s.execute(text("SELECT slug FROM tenants WHERE id=:t"), {"t": tenant_id}).scalar()
        vectors = s.execute(text("SELECT count(*) FROM chunks WHERE embedding IS NOT NULL")).scalar()
        caches = {t: s.execute(text(f'SELECT count(*) FROM "{t}"')).scalar() for t in CACHE_TABLES}
        audit = s.execute(text("SELECT count(*) FROM audit_events")).scalar()
    deleted = _purge_rows(tenant_id, keep_job_id=job_id)
    files = _purge_files(tenant_id)
    remaining = _remaining(tenant_id, keep_job_id=job_id)
    if remaining:
        raise LifecycleError("residual_rows", f"rows remain after deletion: {remaining}")
    cert = {"deletion_id": str(deletion_id), "tenant_slug": slug, "completed_at": datetime.now(UTC).isoformat(),
            "rows_deleted": {**deleted, "audit_events": audit}, "rows_remaining": remaining, "vectors_deleted": vectors,
            "caches_cleared": caches, "files_removed": files, "export_id": str(export_id),
            "retained": ["this certificate", "one job record as a completion receipt"],
            "physical_reclamation": "dead tuples are reclaimed by autovacuum; run VACUUM FULL for immediate reclamation",
            "backups": BACKUP_NOTE}
    with tenant_session(tenant_id) as s:
        removed = s.execute(text("SELECT sl_finalize_tenant_deletion(:i, :t, :u, :e, CAST(:c AS jsonb))"),
                            {"i": deletion_id, "t": tenant_id, "u": requested_by, "e": export_id,
                             "c": json.dumps(cert)}).scalar()
    cert["audit_events_deleted"] = removed
    return cert


def reapply_deletions(ledger: list[str] | None = None) -> dict[str, dict]:
    """After restoring a backup taken before a deletion, delete again every tenant recorded as deleted.

    The control-plane record can itself be lost in such a restore, so `ledger` accepts tenant ids kept outside the
    database (deletion certificates are downloadable from /api/v1/deletions/{id}). Runs with the owner role
    because append-only tables (audit_events) are removed too."""
    from .db import admin_engine, control_session
    with control_session() as s:
        gone = {str(r.tenant_id) for r in s.execute(text("SELECT tenant_id FROM tenant_deletions"))}
    gone |= set(ledger or [])
    eng = admin_engine()
    out = {}
    for t in sorted(gone):
        left = _remaining(t, engine=eng)
        files = [p for p in (settings.storage_path / "documents" / t, settings.storage_path / "exports" / t) if p.exists()]
        if left or files:
            out[t] = {"reappeared": left, "deleted": _purge_rows(t, engine=eng), "files": _purge_files(t)}
    return out


def new_id() -> uuid.UUID:
    return uuid.uuid4()


if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["reapply-deletions"]:
        print(json.dumps(reapply_deletions(sys.argv[2:]), indent=2, default=str))
    else:
        raise SystemExit("usage: python -m supplylens.lifecycle reapply-deletions [tenant-id ...]")
