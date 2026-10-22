"""Export the hosted-demo dataset (built locally by `supplylens.bootstrap` into a fresh database) for the Vercel API bundle.

Output: build/vercel-api/hosted_data/*.csv.gz plus manifest.json, loaded into the hosted database by the token-guarded
setup step (supplylens/hosting/setup.py). Files are written per table and per workspace, because tenant tables use forced
row-level security: rows are copied in under their own workspace context, never with RLS switched off.

Size trims for the free Postgres tier, documented in docs/operations/hosted-demo.md: invoice lines (sales_lines) are
kept from 2011-06-01 (the exceptions screen reads the last 90 days of prices); daily sales and everything else are whole.

uv run python scripts/vercel/export_hosted_data.py --db postgresql://supplylens_owner:...@localhost:5432/sl_hosted
"""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "build" / "vercel-api" / "hosted_data"
CONTROL = ["tenants", "users", "memberships"]
SKIP = {"alembic_version", "idempotency_keys", "rate_limit_buckets", "web_vitals", "jobs", "auth_sessions"}
TRIM = {"sales_lines": sql.SQL(" AND invoiced_at >= '2011-06-01'")}


def tenant_tables(c) -> list[str]:
    """Row-level-secured tables with tenant_id, parents first (same rule as lifecycle.tenant_tables)."""
    names = [r[0] for r in c.execute("""SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id' AND NOT a.attisdropped
        WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relrowsecurity ORDER BY c.relname""")]
    edges = c.execute("""SELECT conrelid::regclass::text, confrelid::regclass::text FROM pg_constraint
        WHERE contype = 'f' AND connamespace = 'public'::regnamespace""").fetchall()
    parents = {n: {p for ch, p in edges if ch == n and p in names and p != n} for n in names}
    ordered: list[str] = []
    while len(ordered) < len(names):
        ready = sorted(n for n in names if n not in ordered and parents[n] <= set(ordered))
        if not ready:
            raise SystemExit("foreign-key cycle among tenant tables")
        ordered += ready
    return [n for n in ordered if n not in SKIP]


def columns(c, table: str) -> list[str]:
    return [r[0] for r in c.execute("""SELECT column_name FROM information_schema.columns WHERE table_schema = 'public'
        AND table_name = %s AND is_generated = 'NEVER' ORDER BY ordinal_position""", (table,))]


def dump(c, table: str, cols: list[str], where: sql.Composable, name: str) -> int:
    q = sql.SQL("COPY (SELECT {} FROM {} WHERE TRUE{}) TO STDOUT WITH (FORMAT csv)").format(
        sql.SQL(", ").join(map(sql.Identifier, cols)), sql.Identifier(table), where)
    rows = 0
    path = OUT / name
    with gzip.open(path, "wb", compresslevel=6) as f, c.cursor().copy(q) as cp:
        for chunk in cp:
            f.write(chunk)
            rows += bytes(chunk).count(b"\n")
    if rows == 0:
        path.unlink()
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*"):
        f.unlink()
    manifest = {"control": [], "tenant": [], "sequences": []}
    with psycopg.connect(a.db, autocommit=True) as c:
        for t in CONTROL:
            cols = columns(c, t)
            n = dump(c, t, cols, sql.SQL(""), f"{t}.csv.gz")
            manifest["control"].append({"table": t, "columns": cols, "file": f"{t}.csv.gz", "rows": n})
        tenants = c.execute("SELECT id, slug FROM tenants WHERE deleted_at IS NULL ORDER BY slug").fetchall()
        tables = tenant_tables(c)
        for tid, slug in tenants:
            c.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tid),))
            for t in tables:
                cols = columns(c, t)
                n = dump(c, t, cols, TRIM.get(t, sql.SQL("")), f"{t}__{slug}.csv.gz")
                if n:
                    manifest["tenant"].append({"table": t, "tenant_id": str(tid), "tenant": slug, "columns": cols,
                                               "file": f"{t}__{slug}.csv.gz", "rows": n})
        manifest["sequences"] = [{"table": r[0], "column": r[1]} for r in c.execute("""
            SELECT table_name, column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND column_default LIKE 'nextval(%'""")]
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    size = sum(f.stat().st_size for f in OUT.glob("*.gz"))
    print(f"exported {sum(x['rows'] for x in manifest['tenant'])} tenant rows in {len(manifest['tenant'])} files, "
          f"{size / 1e6:.1f} MB compressed")


if __name__ == "__main__":
    main()
