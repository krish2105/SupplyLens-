"""Shared fixtures. Tests run against the real `supplylens_test` PostgreSQL database
as the non-owner app role, so RLS behaves exactly as in the application."""
import os

os.environ.setdefault(
    "SUPPLYLENS_DATABASE_URL",
    "postgresql+psycopg://supplylens_app:supplylens_app_dev@localhost:5432/supplylens_test",
)
os.environ.setdefault(
    "SUPPLYLENS_ADMIN_DATABASE_URL",
    "postgresql+psycopg://supplylens_owner:supplylens_owner_dev@localhost:5432/supplylens_test",
)
os.environ.setdefault("SUPPLYLENS_STORAGE_DIR", "storage_test")
os.environ.setdefault("SUPPLYLENS_SIGN_IN_PER_MINUTE", "100000")   # the suites sign in hundreds of times; guards.py tests set their own

from urllib.parse import urlsplit

import pytest


def _refuse_unless_disposable_test_database() -> None:
    """The fixtures TRUNCATE every tenant table. Positive proof is required that the configured databases are disposable
    test databases before anything runs (Phase 2, SEC-P2-01): a local host (or SUPPLYLENS_TEST_DB_HOST) and a database
    name ending in `_test`. A mistyped URL pointing at a real database stops the run instead of emptying it."""
    hosts = {"localhost", "127.0.0.1", "::1", os.environ.get("SUPPLYLENS_TEST_DB_HOST", "localhost")}
    for var in ("SUPPLYLENS_DATABASE_URL", "SUPPLYLENS_ADMIN_DATABASE_URL"):
        u = urlsplit(os.environ[var].replace("postgresql+psycopg://", "postgresql://", 1))
        name = u.path.lstrip("/")
        if not name.endswith("_test") or u.hostname not in hosts:
            raise pytest.UsageError(f"refusing to run: {var} names database {name!r} on {u.hostname!r}; the test fixtures "
                                    "empty tables and need a local database whose name ends in _test")


_refuse_unless_disposable_test_database()

from sqlalchemy import text

from supplylens.config import settings
from supplylens.db import admin_engine
from supplylens.seed import seed, tenant_id

if settings.environment not in ("development", "test"):
    raise pytest.UsageError(f"refusing to run tests with SUPPLYLENS_ENVIRONMENT={settings.environment}")

TENANT_TABLES_CLEAR_ORDER = [
    "receipts", "purchase_order_lines", "import_rows", "import_batches",
    "web_vitals", "tenant_exports", "alerts", "rate_limit_buckets", "clause_labels", "public_awards", "tenant_settings", "warehouse_slots",
    "audit_events", "approvals", "outbox", "actions", "agent_events", "agent_runs",
    "idempotency_keys", "jobs", "plan_runs", "forecast_points", "forecast_runs",
    "model_versions", "supplier_terms", "chunks", "document_versions", "documents",
    "inventory_positions", "suppliers", "assumption_sets", "sales_daily", "return_lines",
    "sales_lines", "quarantine", "products", "locations", "datasets",
]


@pytest.fixture(scope="session", autouse=True)
def seeded():
    seed()
    yield


@pytest.fixture()
def clean_db():
    with admin_engine().begin() as conn:
        # TRUNCATE is not subject to RLS (FORCE RLS also binds the owner for DELETE).
        tables = ", ".join(TENANT_TABLES_CLEAR_ORDER)
        conn.execute(text(f"TRUNCATE {tables}, sandbox_erp.purchase_orders, sandbox_erp.fault_injection"))
    yield


@pytest.fixture()
def tenant_a():
    return tenant_id("uci-research")


@pytest.fixture()
def tenant_b():
    return tenant_id("demo")
