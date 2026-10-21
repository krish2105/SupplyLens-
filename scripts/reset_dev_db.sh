#!/usr/bin/env bash
# DESTRUCTIVE for the local dev database only: empties all tenant data, then re-runs bootstrap.
set -euo pipefail
cd "$(dirname "$0")/.."
DB="${1:-supplylens}"
TABLES=$(psql -h /tmp -d "$DB" -Atc "select string_agg(quote_ident(tablename), ', ') from pg_tables where schemaname='public' and tablename not in ('alembic_version','tenants','users','memberships')")
psql -h /tmp -d "$DB" -qc "TRUNCATE $TABLES, sandbox_erp.purchase_orders, sandbox_erp.fault_injection CASCADE"
uv run python -m supplylens.bootstrap
