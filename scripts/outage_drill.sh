#!/usr/bin/env bash
# Phase 6: database outage and worker crash drill on a scratch PostgreSQL cluster.
#
#   1. scratch cluster, migrate, Demo workspace; start the API (uvicorn) and a worker against it
#   2. worker crash: SIGKILL the worker; approve N orders while no worker runs (they wait in the outbox)
#   3. database outage: crash-stop PostgreSQL (immediate), start a new worker while the database is down,
#      probe the API's /health throughout, keep the database down for OUTAGE_S seconds
#   4. restart PostgreSQL; measure until /health answers 200 and until every order is RECONCILED
#   5. verify: both processes survived, exactly one sandbox order per action, distinct keys; write a JSON report
#
# Needs PostgreSQL server binaries (PGBIN, default: pg_config --bindir) with pgvector, and `uv`. Never touches your
# databases: everything runs on a cluster in a temporary directory that is deleted at the end.
set -euo pipefail
cd "$(dirname "$0")/.."
PGBIN="${PGBIN:-$(pg_config --bindir)}"
export PATH="$PGBIN:$PATH"
export LC_ALL="${LC_ALL:-en_US.UTF-8}"     # macOS: without a valid locale the postmaster refuses to start
PORT="${DRILL_PG_PORT:-55442}"; API_PORT="${DRILL_API_PORT:-18431}"
ORDERS="${DRILL_ORDERS:-5}"; OUTAGE_S="${OUTAGE_S:-20}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/sl_outage.XXXXXX")"; DATA="$WORK/data"
HOSTARGS=(-h 127.0.0.1 -U postgres -p "$PORT")
API_PID=""; W_PID=""
cleanup() {
  [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null || true
  [ -n "$W_PID" ] && kill "$W_PID" 2>/dev/null || true
  pg_ctl -D "$DATA" -m immediate stop >/dev/null 2>&1 || true
  rm -rf "$WORK" storage_outage_drill
}
trap cleanup EXIT
now() { python3 -c 'import time; print(f"{time.time():.3f}")'; }

export SUPPLYLENS_DATABASE_URL="postgresql+psycopg://supplylens_app:supplylens_app_dev@127.0.0.1:$PORT/supplylens"
export SUPPLYLENS_ADMIN_DATABASE_URL="postgresql+psycopg://supplylens_owner:supplylens_owner_dev@127.0.0.1:$PORT/supplylens"
export SUPPLYLENS_MIGRATION_URL="$SUPPLYLENS_ADMIN_DATABASE_URL"
export SUPPLYLENS_STORAGE_DIR=storage_outage_drill SUPPLYLENS_DB_POOL_TIMEOUT_S=2
export SUPPLYLENS_WORKER_HEARTBEAT="$WORK/worker.heartbeat"

echo "== 1. scratch cluster on port $PORT, API on $API_PORT"
initdb -D "$DATA" -U postgres -A trust -E UTF8 >/dev/null
# TCP only: a socket path inside a long temporary directory can exceed the operating system's limit
printf "port = %s\nlisten_addresses = '127.0.0.1'\nunix_socket_directories = ''\n" "$PORT" >> "$DATA/postgresql.conf"
pg_ctl -D "$DATA" -l "$WORK/pg.log" -w start >/dev/null
psql "${HOSTARGS[@]}" -d postgres -v ON_ERROR_STOP=1 -q <<SQL
CREATE ROLE supplylens_owner LOGIN PASSWORD 'supplylens_owner_dev';
CREATE ROLE supplylens_app LOGIN PASSWORD 'supplylens_app_dev' NOBYPASSRLS;
CREATE DATABASE supplylens OWNER supplylens_owner;
SQL
psql "${HOSTARGS[@]}" -d supplylens -q -c "CREATE EXTENSION vector" -c "GRANT CONNECT ON DATABASE supplylens TO supplylens_app"
uv run --no-sync alembic -c services/api/alembic.ini upgrade head 2>&1 | grep -v -E "UV_NATIVE|^INFO" || true
uv run --no-sync python scripts/ops_drill.py setup
# the processes are started with the environment's interpreter, not through `uv run`, so the PIDs below are the real
# server processes (a SIGKILL sent to a `uv run` wrapper leaves its child running: the first version of this drill)
PY="$(uv run --no-sync python -c 'import sys; print(sys.executable)')"
"$PY" -m uvicorn supplylens.api.app:app --host 127.0.0.1 --port "$API_PORT" > "$WORK/api.log" 2>&1 &
API_PID=$!
"$PY" -m supplylens_worker.main > "$WORK/worker1.log" 2>&1 &
W_PID=$!
for _ in $(seq 1 60); do curl -fsS "http://127.0.0.1:$API_PORT/health" >/dev/null 2>&1 && break; sleep 0.5; done

echo "== 2. worker crash (SIGKILL), then $ORDERS approvals with no worker running"
sleep 2; kill -9 "$W_PID"; wait "$W_PID" 2>/dev/null || true; W_PID=""
uv run --no-sync python scripts/ops_drill.py approve "$ORDERS" >/dev/null
BEFORE="$(uv run --no-sync python scripts/ops_drill.py state)"
python3 -c "import json,sys; a=json.loads(sys.argv[1])['actions']; sys.exit(0 if a == {'QUEUED': $ORDERS} else 1)" "$BEFORE" \
  || { echo "orders were dispatched before the outage: the worker was not stopped"; exit 1; }
echo "   waiting in the outbox: $BEFORE"

echo "== 3. database outage for ${OUTAGE_S}s (immediate stop), new worker started while it is down"
T_DOWN=$(now)
pg_ctl -D "$DATA" -m immediate stop >/dev/null
"$PY" -m supplylens_worker.main > "$WORK/worker2.log" 2>&1 &
W_PID=$!
CODES=""
end=$(( $(date +%s) + OUTAGE_S ))
while [ "$(date +%s)" -lt "$end" ]; do
  CODES="$CODES $(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:$API_PORT/health" || echo 000)"
  sleep 2
done
kill -0 "$W_PID" 2>/dev/null && W_ALIVE_DURING=true || W_ALIVE_DURING=false
kill -0 "$API_PID" 2>/dev/null && API_ALIVE_DURING=true || API_ALIVE_DURING=false

echo "== 4. database back; measuring recovery"
pg_ctl -D "$DATA" -l "$WORK/pg.log" -w start >/dev/null
T_UP=$(now); T_API=""; T_ORDERS=""
for _ in $(seq 1 240); do
  if [ -z "$T_API" ] && [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:$API_PORT/health")" = 200 ]; then T_API=$(now); fi
  S="$(uv run --no-sync python scripts/ops_drill.py state 2>/dev/null || echo '{}')"
  if python3 -c "import json,sys; d=json.loads(sys.argv[1]); a=d.get('actions',{}); sys.exit(0 if a and set(a)=={'RECONCILED'} else 1)" "$S"; then
    T_ORDERS=$(now); break
  fi
  sleep 0.5
done
[ -z "$T_API" ] && [ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$API_PORT/health")" = 200 ] && T_API=$(now)
AFTER="$(uv run --no-sync python scripts/ops_drill.py state)"
kill -0 "$W_PID" 2>/dev/null && W_ALIVE=true || W_ALIVE=false
kill -0 "$API_PID" 2>/dev/null && API_ALIVE=true || API_ALIVE=false
RECOVERED_LINES=$(grep -c "worker tick failed" "$WORK/worker2.log" || true)

echo "== 5. verify and report"
REPORT="artifacts/reports/outage_drill_$(date -u +%Y%m%dT%H%M%SZ).json"
mkdir -p artifacts/reports
python3 - "$REPORT" "$ORDERS" "$OUTAGE_S" "$BEFORE" "$AFTER" "$T_DOWN" "$T_UP" "${T_API:-}" "${T_ORDERS:-}" "$CODES" \
  "$W_ALIVE_DURING" "$API_ALIVE_DURING" "$W_ALIVE" "$API_ALIVE" "$RECOVERED_LINES" <<'PY'
import json, platform, sys
(report, n, outage, before, after, t_down, t_up, t_api, t_orders, codes, w_during, api_during, w_alive, api_alive,
 failed_ticks) = sys.argv[1:]
before, after, n = json.loads(before), json.loads(after), int(n)
acts = after["actions"]
ok = (acts == {"RECONCILED": n} and after["sandbox_orders"] == n == after["distinct_keys"] and w_alive == "true"
      and api_alive == "true" and bool(t_api) and bool(t_orders) and before["actions"] == {"QUEUED": n}
      and set(codes.split()) == {"503"})
out = {"drill": "database outage and worker crash", "ok": ok, "orders": n, "outage_seconds_planned": int(outage),
       "outage_seconds_actual": round(float(t_up) - float(t_down), 1),
       "state_before_outage": before, "state_after_recovery": after,
       "health_codes_during_outage": codes.split(),
       "api_alive_during_outage": api_during == "true", "worker_alive_during_outage": w_during == "true",
       "api_alive_after": api_alive == "true", "worker_alive_after": w_alive == "true",
       "worker_failed_ticks_logged": int(failed_ticks or 0),
       "seconds_db_up_to_api_healthy": round(float(t_api) - float(t_up), 1) if t_api else None,
       "seconds_db_up_to_all_orders_reconciled": round(float(t_orders) - float(t_up), 1) if t_orders else None,
       "exactly_one_order_per_action": after["sandbox_orders"] == n == after["distinct_keys"],
       "host": platform.node(),
       "notes": "scratch cluster on one machine; the worker was killed before approval, so orders waited in the outbox "
                "through the outage. Recovery times exclude detection and the time to restart the database."}
open(report, "w").write(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))
sys.exit(0 if ok else 1)
PY
echo "report: $REPORT"
