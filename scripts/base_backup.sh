#!/usr/bin/env bash
# Take a physical base backup of the compose database into the `basebackups` volume. Together with the WAL archive
# (continuously copied to the `walarchive` volume) it allows point-in-time recovery: see docs/operations/runbook.md.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose exec -T -u postgres db sh -c \
  'd=/basebackups/base_$(date -u +%Y%m%dT%H%M%SZ) && pg_basebackup -D "$d" -Ft -z -X none -c fast && echo "base backup written to $d" && ls -la "$d"'
