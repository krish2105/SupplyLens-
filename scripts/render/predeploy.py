"""Render pre-deploy: app role + pgvector, migrations, then seed the demo (idempotent; runs before every deploy).

Fails closed: if the owner cannot create the restricted app role, the deploy stops instead of running the API as owner.
Demo content only: the fictional Demo workspace and the public UCI Online Retail II research data (CC BY 4.0).
"""
import hashlib
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import psycopg
from psycopg import sql

UCI_URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
UCI_SHA256 = "572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb"


def main() -> None:
    owner = os.environ["DATABASE_URL"].replace("postgres://", "postgresql://", 1)
    pw = os.environ["SUPPLYLENS_APP_DB_PASSWORD"]
    with psycopg.connect(owner, autocommit=True) as c:
        db = c.execute("SELECT current_database()").fetchone()[0]
        c.execute("CREATE EXTENSION IF NOT EXISTS vector")
        exists = c.execute("SELECT 1 FROM pg_roles WHERE rolname = 'supplylens_app'").fetchone()
        if not (exists and _app_login_works(owner, pw)):        # redeploys keep the role and its generated password
            verb = "ALTER" if exists else "CREATE"
            try:
                c.execute(sql.SQL("{} ROLE supplylens_app LOGIN NOBYPASSRLS PASSWORD {}").format(sql.SQL(verb), sql.Literal(pw)))
            except psycopg.Error as e:
                sys.exit(f"cannot {verb.lower()} role supplylens_app as the database owner ({e}); "
                         "refusing to run the API as owner")
        c.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO supplylens_app").format(sql.Identifier(db)))
    run(["alembic", "-c", "services/api/alembic.ini", "upgrade", "head"])
    if os.environ.get("SUPPLYLENS_DEMO_LOAD_UCI", "true") == "true":
        os.environ["SUPPLYLENS_UCI_ZIP"] = fetch_uci()
    run([sys.executable, "-m", "supplylens.bootstrap"])


def _app_login_works(owner_url: str, pw: str) -> bool:
    try:
        with psycopg.connect(psycopg.conninfo.make_conninfo(owner_url, user="supplylens_app", password=pw), connect_timeout=5):
            return True
    except psycopg.Error:
        return False


def fetch_uci() -> str:
    path = Path(os.environ.get("TMPDIR", "/tmp")) / "online_retail_ii.zip"
    if not path.exists():
        print("downloading UCI Online Retail II (CC BY 4.0)", flush=True)
        urllib.request.urlretrieve(UCI_URL, path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != UCI_SHA256:
        path.unlink(missing_ok=True)
        sys.exit(f"UCI file hash {digest} differs from the recorded {UCI_SHA256}; not loading it")
    return str(path)


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
