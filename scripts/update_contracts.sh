#!/usr/bin/env bash
# Regenerate packages/contracts/openapi.json and api.d.ts from the running code. Commit the result;
# scripts/check_contracts.sh (and CI) fail if the committed files drift from the code.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run python scripts/export_openapi.py packages/contracts/openapi.json >/dev/null
npx --prefix apps/web openapi-typescript packages/contracts/openapi.json --default-non-nullable false -o packages/contracts/api.d.ts >/dev/null
echo "contracts updated: $(python3 -c "import json;print(len(json.load(open('packages/contracts/openapi.json'))['paths']))") paths"
