#!/usr/bin/env bash
# Create local SupplyLens databases and roles on the Homebrew PostgreSQL 17 server.
# Owner role runs migrations; app role is a non-owner without BYPASSRLS (spec SEC/ARC RLS rules).
set -euo pipefail
PGHOST="${PGHOST:-/tmp}"; PGPORT="${PGPORT:-5432}"
OWNER_PW="${SUPPLYLENS_OWNER_PASSWORD:-supplylens_owner_dev}"
APP_PW="${SUPPLYLENS_APP_PASSWORD:-supplylens_app_dev}"
psql -h "$PGHOST" -p "$PGPORT" -d postgres -v ON_ERROR_STOP=1 <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='supplylens_owner') THEN
    CREATE ROLE supplylens_owner LOGIN PASSWORD '${OWNER_PW}';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='supplylens_app') THEN
    CREATE ROLE supplylens_app LOGIN PASSWORD '${APP_PW}' NOBYPASSRLS;
  END IF;
END \$\$;
SQL
for db in supplylens supplylens_test; do
  if ! psql -h "$PGHOST" -p "$PGPORT" -d postgres -Atc "select 1 from pg_database where datname='$db'" | grep -q 1; then
    psql -h "$PGHOST" -p "$PGPORT" -d postgres -c "CREATE DATABASE $db OWNER supplylens_owner"
  fi
  psql -h "$PGHOST" -p "$PGPORT" -d "$db" -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS vector" \
    -c "GRANT CONNECT ON DATABASE $db TO supplylens_app"
done
echo "databases ready"
