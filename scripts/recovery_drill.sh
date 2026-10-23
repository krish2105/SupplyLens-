#!/usr/bin/env bash
# Phase 6: measured RPO and RTO for the loss of the primary's disk, at a realistic data volume.
#
#   1. scratch cluster with WAL archiving (archive_timeout = ARCHIVE_TIMEOUT, default 60 s as in docker-compose.yml)
#   2. copy a real local database into it (SOURCE_DB, default supplylens_load; read-only pg_dump), migrate to head
#   3. physical base backup
#   4. a writer commits one row every 0.2 s and logs each acknowledged commit OUTSIDE the database
#   5. after LOAD_S seconds: crash-stop PostgreSQL and delete its data directory (the disk is lost; the archive survives)
#   6. restore: base backup + every archived WAL segment, promote; migration check; API /health answers 200
#   7. measure: RPO = time between the loss and the newest acknowledged write that survived; lost acknowledged writes;
#      RTO = time from the loss to a healthy API (detection and decision time are NOT included); write a JSON report
#
# Needs PostgreSQL server binaries (PGBIN) with pgvector, `uv`, and read access to SOURCE_DB on the local server. Never
# writes to SOURCE_DB; the scratch cluster lives in a temporary directory that is deleted at the end.
set -euo pipefail
cd "$(dirname "$0")/.."
PGBIN="${PGBIN:-$(pg_config --bindir)}"
export PATH="$PGBIN:$PATH"
export LC_ALL="${LC_ALL:-en_US.UTF-8}"     # macOS: without a valid locale the postmaster refuses to start
SOURCE_DB="${SOURCE_DB:-supplylens_load}"; SOURCE_HOST="${SOURCE_HOST:-localhost}"
PORT="${DRILL_PG_PORT:-55452}"; API_PORT="${DRILL_API_PORT:-18441}"
ARCHIVE_TIMEOUT="${ARCHIVE_TIMEOUT:-60}"; LOAD_S="${LOAD_S:-180}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/sl_recovery.XXXXXX")"
DATA="$WORK/data"; ARCHIVE="$WORK/wal_archive"; BASE="$WORK/base"; RDATA="$WORK/restored"; LOG="$WORK/acks.log"
mkdir -p "$ARCHIVE" "$BASE"
HOSTARGS=(-h 127.0.0.1 -U postgres -p "$PORT")
API_PID=""; WR_PID=""
cleanup() {
  [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null || true
  [ -n "$WR_PID" ] && kill "$WR_PID" 2>/dev/null || true
  pg_ctl -D "$DATA" -m immediate stop >/dev/null 2>&1 || true
  pg_ctl -D "$RDATA" -m immediate stop >/dev/null 2>&1 || true
  rm -rf "$WORK" storage_recovery_drill
}
trap cleanup EXIT
now() { python3 -c 'import time; print(f"{time.time():.3f}")'; }
export SUPPLYLENS_DATABASE_URL="postgresql+psycopg://supplylens_app:supplylens_app_dev@127.0.0.1:$PORT/supplylens"
export SUPPLYLENS_ADMIN_DATABASE_URL="postgresql+psycopg://supplylens_owner:supplylens_owner_dev@127.0.0.1:$PORT/supplylens"
export SUPPLYLENS_MIGRATION_URL="$SUPPLYLENS_ADMIN_DATABASE_URL" SUPPLYLENS_STORAGE_DIR=storage_recovery_drill
PY="$(uv run --no-sync python -c 'import sys; print(sys.executable)')"

conf() {  # TCP only: a socket path inside a long temporary directory can exceed the operating system's limit
  printf "port = %s\nlisten_addresses = '127.0.0.1'\nunix_socket_directories = ''\n" "$PORT" >> "$1/postgresql.conf"
}

echo "== 1. cluster with WAL archiving (archive_timeout=${ARCHIVE_TIMEOUT}s) on port $PORT"
initdb -D "$DATA" -U postgres -A trust -E UTF8 >/dev/null
conf "$DATA"
cat >> "$DATA/postgresql.conf" <<CONF
wal_level = replica
archive_mode = on
archive_timeout = $ARCHIVE_TIMEOUT
archive_command = 'test ! -f $ARCHIVE/%f && cp %p $ARCHIVE/%f'
max_wal_size = 4GB
CONF
pg_ctl -D "$DATA" -l "$WORK/pg.log" -w start >/dev/null
psql "${HOSTARGS[@]}" -d postgres -v ON_ERROR_STOP=1 -q <<SQL
CREATE ROLE supplylens_owner LOGIN PASSWORD 'supplylens_owner_dev';
CREATE ROLE supplylens_app LOGIN PASSWORD 'supplylens_app_dev' NOBYPASSRLS;
CREATE DATABASE supplylens OWNER supplylens_owner;
SQL
psql "${HOSTARGS[@]}" -d supplylens -q -c "CREATE EXTENSION vector" -c "GRANT CONNECT ON DATABASE supplylens TO supplylens_app"

echo "== 2. copy $SOURCE_DB (read-only dump) and migrate"
T0=$(now)
pg_dump -h "$SOURCE_HOST" -Fc -d "$SOURCE_DB" -f "$WORK/source.dump"
pg_restore -l "$WORK/source.dump" | grep -v -E ' EXTENSION ' > "$WORK/source.list"
pg_restore "${HOSTARGS[@]}" -d supplylens --no-owner --role=supplylens_owner -L "$WORK/source.list" "$WORK/source.dump" \
  2> "$WORK/restore.err" || { grep -v -E "already exists|^pg_restore: (warning|from TOC)" "$WORK/restore.err" | head -5; }
"$PY" -m alembic -c services/api/alembic.ini upgrade head 2>&1 | grep -v -E "UV_NATIVE|^INFO" || true
DBBYTES="$(psql "${HOSTARGS[@]}" -d postgres -Atc "SELECT pg_database_size('supplylens')")"
COUNT_SQL="SELECT json_build_object('sales_lines',(SELECT count(*) FROM sales_lines),'products',(SELECT count(*) FROM products),'chunks',(SELECT count(*) FROM chunks),'chunk_vectors',(SELECT count(*) FROM chunk_vectors),'actions',(SELECT count(*) FROM actions),'audit_events',(SELECT count(*) FROM audit_events))"
COUNTS_BEFORE="$(psql "${HOSTARGS[@]}" -d supplylens -Atc "$COUNT_SQL")"
echo "   $(python3 -c "print(round($DBBYTES/2**20))") MB in $(python3 -c "print(round($(now)-$T0))") s; counts $COUNTS_BEFORE"

echo "== 3. base backup"
T_B0=$(now)
pg_basebackup -h 127.0.0.1 -U postgres -p "$PORT" -D "$BASE" -Ft -z -X stream -c fast >/dev/null
T_B1=$(now)
BASEBYTES="$(du -sk "$BASE" | cut -f1)"

echo "== 4. writer: one acknowledged commit every 0.2 s for ${LOAD_S}s"
"$PY" scripts/ops_drill.py write-loop "$((LOAD_S + 600))" "$LOG" &
WR_PID=$!
sleep "$LOAD_S"

echo "== 5. disaster: crash-stop and delete the data directory"
T_LOSS=$(now)
pg_ctl -D "$DATA" -m immediate stop >/dev/null
rm -rf "$DATA"
sleep 1; kill "$WR_PID" 2>/dev/null || true; wait "$WR_PID" 2>/dev/null || true; WR_PID=""
SEGMENTS=$(ls "$ARCHIVE" | grep -c -v -E '\.(backup|history)$' || true)

echo "== 6. restore: base backup + archived WAL, promote"
T_R0=$(now)
mkdir -p "$RDATA"; chmod 700 "$RDATA"
tar -xzf "$BASE/base.tar.gz" -C "$RDATA"
[ -f "$BASE/pg_wal.tar.gz" ] && tar -xzf "$BASE/pg_wal.tar.gz" -C "$RDATA/pg_wal"
cat >> "$RDATA/postgresql.conf" <<CONF
archive_mode = off
restore_command = 'cp $ARCHIVE/%f %p'
CONF
touch "$RDATA/recovery.signal"
pg_ctl -D "$RDATA" -l "$WORK/restored.log" -w -t 600 start >/dev/null
until psql "${HOSTARGS[@]}" -d postgres -Atc "SELECT NOT pg_is_in_recovery()" 2>/dev/null | grep -q t; do sleep 0.5; done
T_R1=$(now)
"$PY" -m alembic -c services/api/alembic.ini current 2>/dev/null | grep -q "(head)" && AT_HEAD=true || AT_HEAD=false
COUNTS_AFTER="$(psql "${HOSTARGS[@]}" -d supplylens -Atc "$COUNT_SQL")"
"$PY" -m uvicorn supplylens.api.app:app --host 127.0.0.1 --port "$API_PORT" > "$WORK/api.log" 2>&1 &
API_PID=$!
for _ in $(seq 1 120); do [ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$API_PORT/health")" = 200 ] && break; sleep 0.5; done
T_SERVICE=$(now)
HEALTH="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$API_PORT/health")"
WRITTEN="$("$PY" scripts/ops_drill.py written)"
PGVER="$(psql "${HOSTARGS[@]}" -d postgres -Atc 'SHOW server_version')"

echo "== 7. measure and report"
REPORT="artifacts/reports/recovery_drill_$(date -u +%Y%m%dT%H%M%SZ).json"
mkdir -p artifacts/reports
python3 - "$REPORT" "$LOG" "$WRITTEN" "$T_LOSS" "$T_R0" "$T_R1" "$T_SERVICE" "$T_B0" "$T_B1" "$DBBYTES" "$BASEBYTES" \
  "$SEGMENTS" "$ARCHIVE_TIMEOUT" "$LOAD_S" "$COUNTS_BEFORE" "$COUNTS_AFTER" "$AT_HEAD" "$HEALTH" "$PGVER" "$SOURCE_DB" <<'PY'
import json, platform, sys
(report, log, written, t_loss, t_r0, t_r1, t_svc, t_b0, t_b1, dbbytes, basekb, segs, at, load_s, before, after, at_head,
 health, pgver, source) = sys.argv[1:]
acks = [tuple(map(float, l.split())) for l in open(log) if l and not l.startswith("#")]
w = json.loads(written)
t_loss = float(t_loss)
survived = [t for i, t in acks if i <= w["max_id"]]
lost = [(i, t) for i, t in acks if i > w["max_id"]]
newest_surviving = max(survived) if survived else None
rpo = round(t_loss - newest_surviving, 1) if newest_surviving else None
before, after = json.loads(before), json.loads(after)
ok = (bool(acks) and health == "200" and at_head == "true" and before == after and rpo is not None
      and all(i <= w["max_id"] or t > newest_surviving for i, t in acks))
out = {"drill": "primary disk loss: base backup + archived WAL", "ok": ok, "source_database": source,
       "database_bytes": int(dbbytes), "base_backup_bytes_gz": int(basekb) * 1024,
       "base_backup_seconds": round(float(t_b1) - float(t_b0), 1), "archive_timeout_s": int(at),
       "write_load_seconds": int(load_s), "acknowledged_writes": len(acks), "acknowledged_writes_lost": len(lost),
       "lost_window_seconds": round(max(t for _, t in lost) - min(t for _, t in lost), 1) if lost else 0.0,
       "rpo_seconds_measured": rpo, "wal_segments_archived": int(segs),
       "restore_seconds": round(float(t_r1) - float(t_r0), 1),
       "rto_seconds_loss_to_healthy_api": round(float(t_svc) - t_loss, 1),
       "migrations_at_head_after_restore": at_head == "true", "api_health_after_restore": int(health),
       "table_counts_before_loss": before, "table_counts_after_restore": after,
       "postgres_server_version": pgver, "host": platform.node(),
       "notes": "One machine: the WAL archive sat on the same disk as the primary, which a real deployment must not do. "
                "RTO excludes detecting the loss and deciding to restore; RPO is bounded by archive_timeout because the "
                "segment being written when the disk is lost was never archived."}
open(report, "w").write(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))
sys.exit(0 if ok else 1)
PY
echo "report: $REPORT"
