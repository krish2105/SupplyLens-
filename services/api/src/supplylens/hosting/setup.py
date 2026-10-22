"""One-time setup of a hosted demo database from inside the hosting platform (used on Vercel).

Why here: the hosted database credentials are marked sensitive by the platform and cannot be read outside it, so the
schema and the bundled demo dataset are installed by the deployed API itself. The endpoint exists only while
SUPPLYLENS_SETUP_TOKEN is set (32+ characters); remove the variable and redeploy afterwards.

Steps (idempotent):
  schema  pgvector, the restricted `supplylens_app` role (the API never runs as the owner), migrations to head
  data    copy hosted_data/*.csv.gz (scripts/vercel/export_hosted_data.py) into an empty database, each workspace's
          rows under its own row-level-security context, then advance id sequences
"""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

import psycopg
from psycopg import sql

from ..config import REPO_ROOT, settings

DATA = REPO_ROOT / "hosted_data"


def _owner_dsn() -> str:
    return settings.admin_database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def schema() -> dict:
    pw = os.environ.get("SUPPLYLENS_APP_DB_PASSWORD", "")
    if len(pw) < 24:
        raise RuntimeError("SUPPLYLENS_APP_DB_PASSWORD must be set (24+ characters)")
    with psycopg.connect(_owner_dsn(), autocommit=True) as c:
        db = c.execute("SELECT current_database()").fetchone()[0]
        c.execute("CREATE EXTENSION IF NOT EXISTS vector")
        verb = "ALTER" if c.execute("SELECT 1 FROM pg_roles WHERE rolname = 'supplylens_app'").fetchone() else "CREATE"
        c.execute(sql.SQL("{} ROLE supplylens_app LOGIN PASSWORD {}").format(sql.SQL(verb), sql.Literal(pw)))
        # only a superuser may set BYPASSRLS (even to false), so it is not stated above; verify the default instead
        flags = c.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'supplylens_app'").fetchone()
        if any(flags):
            raise RuntimeError("supplylens_app can bypass row-level security; refusing to use it")
        c.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO supplylens_app").format(sql.Identifier(db)))
    from alembic import command
    from alembic.config import Config
    os.environ["SUPPLYLENS_MIGRATION_URL"] = settings.admin_database_url
    cfg = Config(str(REPO_ROOT / "services" / "api" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "services" / "api" / "migrations"))
    command.upgrade(cfg, "head")
    with psycopg.connect(_owner_dsn()) as c:
        version = c.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    return {"role": verb.lower() + "d", "migrated_to": version}


def _copy(c, table: str, cols: list[str], path: Path) -> None:
    """COPY is refused on row-level-secured tables, so rows land in a temporary staging table first and are INSERTed
    under the workspace's own context: every row still passes the table's RLS check."""
    col_list = sql.SQL(", ").join(map(sql.Identifier, cols))
    c.execute(sql.SQL("CREATE TEMP TABLE _stage AS SELECT {} FROM {} WITH NO DATA").format(col_list, sql.Identifier(table)))
    with gzip.open(path, "rb") as f, c.cursor().copy(sql.SQL("COPY _stage FROM STDIN WITH (FORMAT csv)")) as cp:
        while chunk := f.read(1 << 20):
            cp.write(chunk)
    c.execute(sql.SQL("INSERT INTO {} ({}) SELECT {} FROM _stage").format(sql.Identifier(table), col_list, col_list))
    c.execute("DROP TABLE _stage")


def data() -> dict:
    manifest = json.loads((DATA / "manifest.json").read_text())
    with psycopg.connect(_owner_dsn()) as c:          # one transaction: all or nothing
        if c.execute("SELECT count(*) FROM tenants").fetchone()[0]:
            return {"status": "already loaded"}
        for m in manifest["control"]:
            if m["rows"]:
                _copy(c, m["table"], m["columns"], DATA / m["file"])
        for m in manifest["tenant"]:
            c.execute("SELECT set_config('app.tenant_id', %s, true)", (m["tenant_id"],))
            _copy(c, m["table"], m["columns"], DATA / m["file"])
        for s in manifest["sequences"]:
            c.execute(sql.SQL("SELECT setval(pg_get_serial_sequence({t}, {col}), "
                              "GREATEST((SELECT COALESCE(max({ci}), 0) FROM {ti}), 1))").format(
                t=sql.Literal(s["table"]), col=sql.Literal(s["column"]), ci=sql.Identifier(s["column"]),
                ti=sql.Identifier(s["table"])))
    return {"status": "loaded", "files": len(manifest["tenant"]) + len(manifest["control"]),
            "rows": sum(m["rows"] for m in manifest["tenant"] + manifest["control"])}
