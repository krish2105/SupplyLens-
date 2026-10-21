#!/usr/bin/env bash
# ARC-02: regenerate OpenAPI + TypeScript types and fail if the committed contract drifted.
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
uv run python scripts/export_openapi.py "$tmp/openapi.json" >/dev/null
npx --prefix apps/web openapi-typescript "$tmp/openapi.json" --default-non-nullable false -o "$tmp/api.d.ts" >/dev/null
diff -u packages/contracts/openapi.json "$tmp/openapi.json"
diff -u packages/contracts/api.d.ts "$tmp/api.d.ts"
echo "contracts match"
