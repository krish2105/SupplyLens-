#!/usr/bin/env bash
# Run the ARC-07 / BUS-015 reference workload: cold interactive run, warm interactive run, then single-user batch benchmarks.
#
#   RESTART_DB_CMD="..."     command that restarts PostgreSQL (empties shared buffers). Optional; skip => "cold" means API restart only.
#   RESTART_STACK_CMD="..."  command that restarts the API/worker/embedder against the load database
#   TAG=name                 suffix for the report files          RETRIEVAL_RATE=5   retrieval requests/second (ARC-07: 5)
#   PHASES="cold warm batch" which phases to run                  COLD_SECONDS / WARM_SECONDS / SETTLE_SECONDS
set -euo pipefail
cd "$(dirname "$0")/../.."
TAG="${TAG:-run}"; OUT=artifacts/reports; RATE="${RETRIEVAL_RATE:-5}"; PHASES="${PHASES:-cold warm batch}"; mkdir -p "$OUT"
[ -n "${RESTART_DB_CMD:-}" ] && bash -c "$RESTART_DB_CMD"
[ -n "${RESTART_STACK_CMD:-}" ] && bash -c "$RESTART_STACK_CMD"
for i in $(seq 1 60); do curl -fsS -o /dev/null http://127.0.0.1:8100/api/v1/auth/dev-users 2>/dev/null && break; sleep 1; done
for phase in $PHASES; do
  case "$phase" in
    cold) uv run --no-sync python scripts/loadtest/run_load.py --phase interactive --retrieval-rate "$RATE" --seconds "${COLD_SECONDS:-90}" \
            --condition "cold (PostgreSQL + API restarted; OS page cache NOT dropped), retrieval ${RATE}/s" --out "$OUT/loadtest-$TAG-cold.json" > /dev/null ;;
    warm) uv run --no-sync python scripts/loadtest/run_load.py --phase interactive --retrieval-rate "$RATE" --seconds "${WARM_SECONDS:-240}" \
            --condition "warm, retrieval ${RATE}/s" --out "$OUT/loadtest-$TAG-warm.json" > /dev/null ;;
    batch) uv run --no-sync python scripts/loadtest/run_load.py --phase batch --condition "warm, one user" --out "$OUT/loadtest-$TAG-batch.json" > /dev/null ;;
  esac
  sleep "${SETTLE_SECONDS:-30}"
done
echo "reports in $OUT/loadtest-$TAG-*.json"
