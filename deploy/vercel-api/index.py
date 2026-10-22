"""Vercel entrypoint for the SupplyLens API (service `api` in vercel.json).

This file, pyproject.toml and hosted_storage/ are committed. The code trees, published study results and migrations are
staged next to it by `scripts/vercel/build_api.py`, which Vercel runs as the service's buildCommand on every Git push
(and which can be run locally before a CLI deploy). Staged paths are git-ignored.
"""
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Variables the Postgres integration injects with the database owner's credentials (Neon on Vercel).
OWNER_VARIABLE_PREFIXES = ("DATABASE_URL", "POSTGRES_", "PGPASSWORD", "PGUSER", "PGHOST", "PGDATABASE", "NEON_")
for p in ("services/api/src", "services/worker/src", "ml", "optimisation"):
    sys.path.insert(0, str(HERE / p))
# Document bytes ship read-only with the function; the app's storage directory must be writable, so copy once per instance.
STORAGE = Path("/tmp/supplylens-storage")
if not STORAGE.exists() and (HERE / "hosted_storage").exists():
    shutil.copytree(HERE / "hosted_storage", STORAGE)
os.environ.setdefault("SUPPLYLENS_STORAGE_DIR", str(STORAGE))
# Database URLs from the platform's Postgres integration (Neon on Vercel). Every request runs as the restricted
# supplylens_app role (row-level security, no owner rights). The integration's owner credentials are kept only while the
# one-time setup endpoint is enabled (SUPPLYLENS_SETUP_TOKEN); otherwise they are removed from this process before the
# application loads, and the application refuses to start if an owner URL is still configured (audit P1-SEC-02).
if os.environ.get("DATABASE_URL_UNPOOLED") and os.environ.get("SUPPLYLENS_APP_DB_PASSWORD"):
    from urllib.parse import quote, urlsplit, urlunsplit
    _o = urlsplit(os.environ["DATABASE_URL_UNPOOLED"].replace("postgres://", "postgresql://", 1))
    _host = _o.hostname + (f":{_o.port}" if _o.port else "")
    if os.environ.get("SUPPLYLENS_SETUP_TOKEN"):
        os.environ["SUPPLYLENS_ADMIN_DATABASE_URL"] = urlunsplit(_o._replace(scheme="postgresql+psycopg"))
    os.environ["SUPPLYLENS_DATABASE_URL"] = urlunsplit(_o._replace(
        scheme="postgresql+psycopg", netloc=f"supplylens_app:{quote(os.environ['SUPPLYLENS_APP_DB_PASSWORD'], safe='')}@{_host}"))
    del _o, _host
if not os.environ.get("SUPPLYLENS_SETUP_TOKEN"):
    for _k in [k for k in os.environ if k.startswith(OWNER_VARIABLE_PREFIXES)]:
        del os.environ[_k]
os.environ.setdefault("SUPPLYLENS_INLINE_JOBS", "true")
os.environ.setdefault("SUPPLYLENS_TRUST_FORWARDED_FOR", "true")     # Vercel's edge sets X-Forwarded-For
os.environ.setdefault("SUPPLYLENS_DB_POOL_SIZE", "2")

from supplylens.api.app import app  # noqa: E402,F401
