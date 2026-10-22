#!/usr/bin/env bash
# ARC-06 / BUS-014 / BUS-020: point-in-time-recovery drill on a scratch PostgreSQL cluster.
#
#   1. start a cluster with continuous WAL archiving (wal_level=replica, archive_mode=on)
#   2. migrate, load the Demo workspace, create real orders through the application
#   3. take a physical base backup (pg_basebackup)
#   4. create one more order (it exists only in archived WAL), note the target time T
#   5. operator error: truncate the orders tables, delete the sandbox orders
#   6. stop the server, restore the base backup, replay archived WAL up to T, promote
#   7. verify every count equals its value at T, every order is accounted for, and write a JSON report
#
# Needs PostgreSQL server binaries (PGBIN, default: pg_config --bindir) and `uv`. Never touches your dev database.
# Works as a normal user, or as root (cluster commands then run as the postgres user).
set -euo pipefail
cd "$(dirname "$0")/.."
PGBIN="${PGBIN:-$(pg_config --bindir)}"
export PATH="$PGBIN:$PATH"
PORT="${PITR_PORT:-55432}"; RPORT=$((PORT + 1))
WORK="$(mktemp -d "${TMPDIR:-/tmp}/sl_pitr.XXXXXX")"
ARCHIVE="$WORK/wal_archive"; BASE="$WORK/base"; DATA="$WORK/data"; RDATA="$WORK/restored"
mkdir -p "$ARCHIVE" "$BASE"
if [ "$(id -u)" = 0 ]; then
  chown postgres:postgres "$WORK" "$ARCHIVE" "$BASE"
  pg() { runuser -u postgres -- env PATH="$PATH" "$@"; }
else
  pg() { "$@"; }
fi
HOSTARGS=(-h 127.0.0.1 -U postgres)
cleanup() { pg pg_ctl -D "$DATA" -m immediate stop >/dev/null 2>&1 || true; pg pg_ctl -D "$RDATA" -m immediate stop >/dev/null 2>&1 || true; rm -rf "$WORK" storage_pitr; }
trap cleanup EXIT

now() { python3 -c 'import time; print(f"{time.time():.3f}")'; }
URL() { echo "postgresql+psycopg://$1@127.0.0.1:$2/supplylens"; }
export SUPPLYLENS_STORAGE_DIR=storage_pitr
appenv() {  # database URLs for the application, pointing at port $1
  export SUPPLYLENS_DATABASE_URL="$(URL supplylens_app:supplylens_app_dev "$1")"
  export SUPPLYLENS_ADMIN_DATABASE_URL="$(URL supplylens_owner:supplylens_owner_dev "$1")"
  export SUPPLYLENS_MIGRATION_URL="$SUPPLYLENS_ADMIN_DATABASE_URL"
}

echo "== 1. cluster with WAL archiving on port $PORT"
pg initdb -D "$DATA" -U postgres -A trust -E UTF8 >/dev/null   # superuser is "postgres" whichever OS user runs this
cat >> "$DATA/postgresql.conf" <<CONF
port = $PORT
listen_addresses = '127.0.0.1'
unix_socket_directories = '$WORK'
wal_level = replica
archive_mode = on
archive_timeout = 30
archive_command = 'test ! -f $ARCHIVE/%f && cp %p $ARCHIVE/%f'
CONF
pg pg_ctl -D "$DATA" -l "$WORK/pg.log" -w start >/dev/null
psql "${HOSTARGS[@]}" -p "$PORT" -d postgres -v ON_ERROR_STOP=1 -q <<SQL
CREATE ROLE supplylens_owner LOGIN PASSWORD 'supplylens_owner_dev';
CREATE ROLE supplylens_app LOGIN PASSWORD 'supplylens_app_dev' NOBYPASSRLS;
CREATE DATABASE supplylens OWNER supplylens_owner;
SQL
psql "${HOSTARGS[@]}" -p "$PORT" -d supplylens -q -c "CREATE EXTENSION vector" -c "GRANT CONNECT ON DATABASE supplylens TO supplylens_app"

echo "== 2. migrate and create 2 orders through the application"
appenv "$PORT"
uv run --no-sync alembic -c services/api/alembic.ini upgrade head 2>&1 | grep -v UV_NATIVE || true
for i in 1 2; do uv run --no-sync python tests/rehearsal_workload.py >/dev/null; done

echo "== 3. base backup"
T_BACKUP_START=$(now)
pg pg_basebackup -h 127.0.0.1 -U postgres -p "$PORT" -D "$BASE" -Ft -z -X stream -c fast >/dev/null
T_BACKUP_END=$(now)

echo "== 4. one more order after the backup (recoverable from WAL only)"
uv run --no-sync python tests/rehearsal_workload.py >/dev/null
sleep 1
TARGET="$(psql "${HOSTARGS[@]}" -p "$PORT" -d postgres -Atc "SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US') || '+00'")"
EXPECTED="$(uv run --no-sync python tests/rehearsal_workload.py --counts 2>/dev/null | tail -1)"
echo "   target time: $TARGET"; echo "   counts at T: $EXPECTED"
sleep 2

echo "== 5. operator error: truncate order tables and delete sandbox orders"
T_DISASTER=$(now)
psql "${HOSTARGS[@]}" -p "$PORT" -d supplylens -q -c "TRUNCATE sandbox_erp.purchase_orders" \
  -c "SELECT set_config('app.tenant_id', '', false)" -c "TRUNCATE actions, approvals, outbox CASCADE" 
AFTER="$(uv run --no-sync python tests/rehearsal_workload.py --counts 2>/dev/null | tail -1)"
echo "   counts after the error: $AFTER"
psql "${HOSTARGS[@]}" -p "$PORT" -d postgres -Atq -c "SELECT pg_switch_wal()" >/dev/null
sleep 3                       # let the archiver ship the final segment
ARCHIVED=$(ls "$ARCHIVE" | wc -l)
pg pg_ctl -D "$DATA" -m immediate stop >/dev/null   # crash-stop, as in a real incident

echo "== 6. restore: base backup + WAL replay to the target time"
T_RESTORE_START=$(now)
mkdir -p "$RDATA"; [ "$(id -u)" = 0 ] && chown postgres:postgres "$RDATA"
chmod 700 "$RDATA"
pg tar -xzf "$BASE/base.tar.gz" -C "$RDATA"
# pg_basebackup -X stream puts the WAL needed for consistency in pg_wal.tar.gz
[ -f "$BASE/pg_wal.tar.gz" ] && pg tar -xzf "$BASE/pg_wal.tar.gz" -C "$RDATA/pg_wal"
cat >> "$RDATA/postgresql.conf" <<CONF
port = $RPORT
archive_mode = off
restore_command = 'cp $ARCHIVE/%f %p'
recovery_target_time = '$TARGET'
recovery_target_action = 'promote'
recovery_target_inclusive = true
CONF
touch "$RDATA/recovery.signal"
pg pg_ctl -D "$RDATA" -l "$WORK/restored.log" -w -t 120 start >/dev/null
until psql "${HOSTARGS[@]}" -p "$RPORT" -d postgres -Atc "SELECT NOT pg_is_in_recovery()" 2>/dev/null | grep -q t; do sleep 0.5; done
T_RESTORE_END=$(now)

echo "== 7. verify"
appenv "$RPORT"
RESTORED="$(uv run --no-sync python tests/rehearsal_workload.py --counts 2>/dev/null | tail -1)"
echo "   restored counts: $RESTORED"
PGVER="$(psql "${HOSTARGS[@]}" -p "$RPORT" -d postgres -Atc 'SHOW server_version')"
DBBYTES="$(psql "${HOSTARGS[@]}" -p "$RPORT" -d postgres -Atc "SELECT pg_database_size('supplylens')")"
REPORT="artifacts/reports/pitr_drill_$(date -u +%Y%m%dT%H%M%SZ).json"
mkdir -p artifacts/reports
python3 - "$EXPECTED" "$AFTER" "$RESTORED" "$TARGET" "$REPORT" "$ARCHIVED" "$T_BACKUP_START" "$T_BACKUP_END" "$T_DISASTER" "$T_RESTORE_START" "$T_RESTORE_END" "$PGVER" "$DBBYTES" <<'PY'
import json, sys, platform
exp, after, got, target, report, archived, b0, b1, dis, r0, r1, pgver, dbbytes = sys.argv[1:]
exp, after, got = json.loads(exp), json.loads(after), json.loads(got)
ok = got == exp and after != exp and exp["sandbox_orders"] == exp["actions"] > 0
out = {"drill": "point-in-time recovery", "ok": ok, "target_time_utc": target,
       "counts_at_target": exp, "counts_after_operator_error": after, "counts_after_restore": got,
       "orders_accounted": got["sandbox_orders"] == got["actions"],
       "wal_segments_archived": int(archived), "archive_timeout_s": 30,
       "backup_seconds": round(float(b1) - float(b0), 1), "restore_seconds_rto": round(float(r1) - float(r0), 1),
       "rpo_bound_s": 30,    # a lost primary disk loses at most the WAL not yet archived: archive_timeout bounds it
       "postgres_server_version": pgver, "database_bytes_restored": int(dbbytes), "host": platform.node(),
       "notes": "scratch cluster on one machine; data are Demo-workspace fictional orders. RTO here is for a database of "
                "this size only: restore time grows with base-backup size and WAL to replay"}
open(report, "w").write(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))
sys.exit(0 if ok else 1)
PY
echo "report: $REPORT"
