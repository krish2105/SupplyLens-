#!/usr/bin/env bash
# Run a command and, if it fails, put the tail of its output into a workflow annotation (::error::) so the failure is
# readable from the check-run API / PR page without downloading logs.   usage: scripts/ci_annotate.sh <command> [args...]
set +e
out="$(mktemp)"
"$@" 2>&1 | tee "$out"
rc="${PIPESTATUS[0]}"
if [ "$rc" -ne 0 ] && [ -n "${GITHUB_ACTIONS:-}" ]; then
  msg="$(tail -n 30 "$out" | sed 's/%/%25/g; s/\r//g' | awk '{printf "%s%%0A", $0}' | cut -c1-3500)"
  echo "::error title=$1 failed (exit $rc)::$msg"
fi
exit "$rc"
