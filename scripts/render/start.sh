#!/bin/sh
# Render start: API and worker in one container (one paid service for the demo). If either process exits, the container
# exits so Render restarts both; the worker's jobs are leased, so a restart never loses or duplicates work.
set -eu
eval "$(python scripts/render/env.py)"
python -m supplylens_worker.main &
WORKER=$!
uvicorn supplylens.api.app:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*' &
API=$!
while kill -0 "$WORKER" 2>/dev/null && kill -0 "$API" 2>/dev/null; do sleep 5; done
echo "a process exited; stopping the container" >&2
kill "$WORKER" "$API" 2>/dev/null || true
exit 1
