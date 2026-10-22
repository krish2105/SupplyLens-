#!/usr/bin/env bash
# Retrieval-rate sweep: same 20 interactive users, retrieval at increasing fixed rates, to find where latency leaves the target.
set -euo pipefail
cd "$(dirname "$0")/../.."
RATES="${RATES:-1 2 3 4 5}"; SECONDS_EACH="${SECONDS_EACH:-90}"; OUT=artifacts/reports; TAG="${TAG:-sweep}"
for r in $RATES; do
  uv run --no-sync python scripts/loadtest/run_load.py --phase interactive --condition "warm, retrieval ${r}/s" --retrieval-rate "$r" --seconds "$SECONDS_EACH" --out "$OUT/loadtest-$TAG-${r}rps.json" > /dev/null
  sleep "${SETTLE_SECONDS:-45}"
done
