"""Derive SupplyLens database URLs from Render's single DATABASE_URL (the instance owner) and a generated app password.

The API and worker must not run as the owner (S09): they connect as `supplylens_app`, a non-owner role subject to
row-level security and to the grants the migrations set. Prints `export` lines for a POSIX shell.
"""
import os
import shlex
from urllib.parse import quote, urlsplit, urlunsplit

owner = urlsplit(os.environ["DATABASE_URL"].replace("postgres://", "postgresql://", 1))
password = os.environ["SUPPLYLENS_APP_DB_PASSWORD"]
host = owner.hostname + (f":{owner.port}" if owner.port else "")
owner_url = urlunsplit(owner._replace(scheme="postgresql+psycopg"))
app_url = urlunsplit(owner._replace(scheme="postgresql+psycopg", netloc=f"supplylens_app:{quote(password, safe='')}@{host}"))
for k, v in {"SUPPLYLENS_ADMIN_DATABASE_URL": owner_url, "SUPPLYLENS_MIGRATION_URL": owner_url,
             "SUPPLYLENS_DATABASE_URL": app_url}.items():
    print(f"export {k}={shlex.quote(v)}")
