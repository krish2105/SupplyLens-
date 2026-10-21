"""Hardening found by the BUS-021 review: default secrets, response headers, CSV formula injection, path traversal."""
import os
import subprocess
import sys
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from supplylens.api.app import app
from supplylens.api.routes_ops import csv_safe
from supplylens.db import tenant_session
from supplylens.seed import tenant_id

DEMO = {"X-Requested-With": "supplylens", "X-SupplyLens-Tenant": "demo"}


def login(c, role):
    c.post("/api/v1/auth/dev-login", json={"email": f"{role}@dev.supplylens.local"}, headers={"X-Requested-With": "supplylens"})


def test_refuses_to_start_without_dev_auth_and_with_default_secrets():
    env = {**os.environ, "SUPPLYLENS_DEV_AUTH": "false"}
    env.pop("SUPPLYLENS_SESSION_SECRET", None)
    out = subprocess.run([sys.executable, "-c", "import supplylens.config"], env=env, capture_output=True, text=True)
    assert out.returncode != 0 and "non-default values" in out.stderr
    ok = subprocess.run([sys.executable, "-c", "import supplylens.config"], capture_output=True, text=True,
                        env={**env, "SUPPLYLENS_SESSION_SECRET": "x" * 40, "SUPPLYLENS_ALERT_WEBHOOK_SECRET": "y" * 40})
    assert ok.returncode == 0, ok.stderr[-300:]


def test_api_responses_are_not_cacheable_or_sniffable():
    c = TestClient(app)
    login(c, "viewer")
    for path in ("/api/v1/overview", "/api/v1/me", "/health"):
        r = c.get(path, headers=DEMO)
        assert r.headers["cache-control"] == "no-store", path
        assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize("cell, expected", [("=SUM(A1)", "'=SUM(A1)"), ("+1+1", "'+1+1"), ("-2", "'-2"), ("@x", "'@x"),
                                            ("\tcmd", "'\tcmd"), ("plain", "plain"), ("", ""), ("a=b", "a=b")])
def test_csv_cells_cannot_start_a_formula(cell, expected):
    assert csv_safe(cell) == expected


def test_audit_export_neutralises_formula_in_user_controlled_fields():
    c = TestClient(app)
    login(c, "tenant_admin")
    with tenant_session(tenant_id("demo")) as s:
        s.execute(text("INSERT INTO audit_events (tenant_id, action, entity, entity_id, detail) "
                       "VALUES (:t, '=HYPERLINK(\"http://evil\")', 'x', '+cmd', '{}')"), {"t": tenant_id("demo")})
    body = c.get("/api/v1/admin/audit.csv", headers=DEMO).text
    assert "'=HYPERLINK" in body and ",=HYPERLINK" not in body and ",+cmd" not in body


def test_export_download_cannot_escape_the_storage_root():
    from supplylens import lifecycle
    with pytest.raises(lifecycle.LifecycleError) as e:
        lifecycle._storage_file("../../etc/passwd")
    assert e.value.code == "bad_storage_key"
    assert uuid.UUID(str(tenant_id("demo")))
