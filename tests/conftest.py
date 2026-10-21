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

import pytest
from sqlalchemy import text

from supplylens.db import admin_engine
from supplylens.seed import seed, tenant_id

TENANT_TABLES_CLEAR_ORDER = [
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
