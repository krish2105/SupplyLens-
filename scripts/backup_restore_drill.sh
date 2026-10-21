#!/usr/bin/env bash
# Backup/restore rehearsal (ARC-06 / BUS-014 local evidence). Restores into an ISOLATED database
# (supplylens_restore_drill), verifies record counts, document bytes and model artifact hashes, then
# drops the drill database. Never touches the source database except to read it.
set -euo pipefail
cd "$(dirname "$0")/.."
SRC="${1:-supplylens}"; DRILL=supplylens_restore_drill
STAMP=$(date -u +%Y%m%dT%H%M%SZ); OUT=artifacts/reports/restore_drill_$STAMP.json
BK=storage/backups; mkdir -p "$BK" artifacts/reports
T0=$(python3 -c 'import time;print(time.time())')
pg_dump -h /tmp -Fc -d "$SRC" -f "$BK/$SRC-$STAMP.dump"
T1=$(python3 -c 'import time;print(time.time())')
psql -h /tmp -d postgres -qc "DROP DATABASE IF EXISTS $DRILL" -c "CREATE DATABASE $DRILL OWNER supplylens_owner"
# pgvector is not a trusted extension: a superuser must create it before restoring (found by the first drill).
psql -h /tmp -d "$DRILL" -qc "CREATE EXTENSION IF NOT EXISTS vector"
# Extension entries are recreated above, so they are excluded from the restore list.
pg_restore -l "$BK/$SRC-$STAMP.dump" | grep -v -E ' EXTENSION ' > "$BK/restore-$STAMP.list"
pg_restore -h /tmp -d "$DRILL" --no-owner --role=supplylens_owner --exit-on-error -L "$BK/restore-$STAMP.list" "$BK/$SRC-$STAMP.dump"
psql -h /tmp -d "$DRILL" -Atc "select 1 from pg_tables where tablename='chunks'" | grep -q 1 || { echo "restore incomplete"; exit 1; }
T2=$(python3 -c 'import time;print(time.time())')
uv run python - "$SRC" "$DRILL" "$OUT" "$T0" "$T1" "$T2" "$BK/$SRC-$STAMP.dump" <<'PY'
import hashlib, json, subprocess, sys
from pathlib import Path
src, drill, out, t0, t1, t2, dump = sys.argv[1:8]
tables = ["datasets", "sales_lines", "return_lines", "quarantine", "sales_daily", "products", "supplier_terms", "documents",
          "document_versions", "chunks", "clause_labels", "public_awards", "model_versions", "forecast_runs", "agent_runs",
          "agent_events", "actions", "approvals", "outbox", "audit_events"]
def q(db, sql):
    return subprocess.run(["psql", "-h", "/tmp", "-d", db, "-Atc", sql], capture_output=True, text=True, check=True).stdout.strip()
counts = {t: (int(q(src, f"select count(*) from {t}")), int(q(drill, f"select count(*) from {t}"))) for t in tables}
erp = (int(q(src, "select count(*) from sandbox_erp.purchase_orders")), int(q(drill, "select count(*) from sandbox_erp.purchase_orders")))
# Document bytes live in the storage adapter: every restored version must resolve to bytes with its recorded hash.
docs = [l.split("|") for l in q(drill, "select storage_key, sha256 from document_versions").splitlines() if l]
bad_docs = [k for k, h in docs if hashlib.sha256((Path("storage") / k).read_bytes()).hexdigest() != h]
arts = []
for line in q(drill, "select artifact_path, artifact_sha256 from model_versions where artifact_sha256 is not null").splitlines():
    path, js = line.split("|", 1)
    for a in json.loads(js):
        f = Path(path) / a["file"]
        arts.append({"file": str(f), "ok": f.exists() and hashlib.sha256(f.read_bytes()).hexdigest() == a["sha256"]})
reconciled = int(q(drill, "select count(*) from actions where status='RECONCILED'"))
report = {"source_db": src, "drill_db": drill, "dump_file": dump, "dump_bytes": Path(dump).stat().st_size,
          "backup_seconds": round(float(t1) - float(t0), 2), "restore_seconds": round(float(t2) - float(t1), 2),
          "tables": {t: {"source": a, "restored": b, "match": a == b} for t, (a, b) in counts.items()},
          "sandbox_erp_orders": {"source": erp[0], "restored": erp[1], "match": erp[0] == erp[1]},
          "document_versions_verified": len(docs) - len(bad_docs), "document_versions_failed": bad_docs,
          "model_artifacts_verified": sum(a["ok"] for a in arts), "model_artifacts_failed": [a["file"] for a in arts if not a["ok"]],
          "reconciled_actions_in_restore": reconciled,
          "all_ok": all(a == b for a, b in counts.values()) and erp[0] == erp[1] and not bad_docs and all(a["ok"] for a in arts),
          "scope_note": "Local single-host rehearsal: logical dump + restore. Not point-in-time recovery; not an off-host backup."}
Path(out).write_text(json.dumps(report, indent=2))
print(json.dumps({k: report[k] for k in ("backup_seconds", "restore_seconds", "dump_bytes", "document_versions_verified",
                                          "model_artifacts_verified", "reconciled_actions_in_restore", "all_ok")}))
PY
psql -h /tmp -d postgres -qc "DROP DATABASE $DRILL"
echo "report: $OUT"
