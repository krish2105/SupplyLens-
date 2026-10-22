"""S18: an authorised administrator onboards a new workspace from CSV without editing code.

Create workspace -> upload sales, stock and terms -> map -> validate (bad rows quarantined, never altered) -> publish an
immutable snapshot -> grant a planner -> the planner runs a scenario on the published data. Nothing operational exists
before it is published.
"""
import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from supplylens.api.app import app
from supplylens.db import tenant_session
from supplylens.seed import dev_email

H = {"X-Requested-With": "supplylens"}


def login(c, role):
    assert c.post("/api/v1/auth/dev-login", json={"email": dev_email(role)}, headers=H).status_code == 200


def sales_csv() -> bytes:
    lines = ["Date,SKU,Store,Qty"]
    for i in range(120):
        lines.append(f"{date(2026, 5, 1) + timedelta(days=i)},SKU-1,WH-01,{(i % 7) + 3}")
    lines += ["2026-13-01,SKU-1,WH-01,4",               # impossible date
              "2026-09-01,SKU-1,WH-01,-2",              # negative units
              "2026-09-02,ann@example.com,WH-01,3",     # personal data in a code column
              "2026-05-01,SKU-1,WH-01,9"]               # duplicate of the first row
    return "\n".join(lines).encode()


STOCK = b"as_of,location_id,sku_id,on_hand,allocated,on_order,capacity\n2026-08-28,WH-01,SKU-1,20,0,0,500\n2026-08-28,WH-01,SKU-2,abc,0,0,\n"
TERMS = (b"term_id,supplier_id,supplier_name,sku_id,unit_cost_minor,currency,moq,order_multiple,lead_time_days,valid_from,valid_to,known_at\n"
         b"T-1,SUP-A,Acme,SKU-1,450,GBP,20,10,5,2026-01-01,,2025-12-01T00:00:00Z\n"
         b"T-2,SUP-B,Bolt,SKU-1,0,GBP,20,10,5,2026-01-01,,2025-12-01T00:00:00Z\n")


@pytest.fixture()
def admin(clean_db):
    c = TestClient(app)
    login(c, "tenant_admin")
    return c


def test_admin_onboards_a_workspace_from_csv_and_a_planner_uses_it(admin):
    slug = f"pilot-{uuid.uuid4().hex[:8]}"
    r = admin.post("/api/v1/onboarding/workspaces", headers={**H, "X-SupplyLens-Tenant": "uci-research"},
                   json={"slug": slug, "name": "Pilot", "currency": "GBP", "weekly_budget_minor": 500000, "coverage_days": 14})
    assert r.status_code == 201, r.text
    W = {**H, "X-SupplyLens-Tenant": slug}
    tid = uuid.UUID(r.json()["tenant_id"])
    assert admin.get("/api/v1/inventory", headers=W).json()["items"] == []        # no invented stock

    ids = {}
    for kind, name, data in (("sales", "sales.csv", sales_csv()), ("stock", "stock.csv", STOCK), ("terms", "terms.csv", TERMS)):
        up = admin.post("/api/v1/onboarding/batches", headers=W, data={"kind": kind, "rights": "our own ERP export"},
                        files={"file": (name, data, "text/csv")})
        assert up.status_code == 201, up.text
        ids[kind] = up.json()["id"]
    sales = admin.get(f"/api/v1/onboarding/batches/{ids['sales']}", headers=W).json()
    assert sales["mapping"] == {"day": "Date", "sku_id": "SKU", "location_id": "Store", "units": "Qty"}   # suggested

    v = admin.post(f"/api/v1/onboarding/batches/{ids['sales']}/validate", headers=W, json={"mapping": sales["mapping"]}).json()
    assert (v["rows_valid"], v["rows_quarantined"]) == (120, 4)
    reasons = " | ".join(" ".join(x["errors"]) for x in v["quarantined_sample"])
    assert "day:" in reasons and "units: must be at least 0" in reasons and "personal data" in reasons and "duplicate" in reasons
    for kind in ("stock", "terms"):
        b = admin.get(f"/api/v1/onboarding/batches/{ids[kind]}", headers=W).json()
        assert admin.post(f"/api/v1/onboarding/batches/{ids[kind]}/validate", headers=W,
                          json={"mapping": b["mapping"]}).json()["rows_quarantined"] == 1
    # publishing before validation is refused; after validation it freezes the batch
    for kind in ("sales", "stock", "terms"):
        p = admin.post(f"/api/v1/onboarding/batches/{ids[kind]}/publish", headers=W)
        assert p.status_code == 200 and p.json()["status"] == "PUBLISHED" and p.json()["snapshot_sha256"]
    with pytest.raises(Exception, match="immutable"), tenant_session(tid) as s:
        s.execute(text("UPDATE import_batches SET file_name='x' WHERE id=:i"), {"i": ids["sales"]})
    with tenant_session(tid) as s:
        assert s.execute(text("SELECT count(*) FROM sales_daily")).scalar() == 120
        assert s.execute(text("SELECT count(*) FROM quarantine")).scalar() == 4
        assert s.execute(text("SELECT count(*) FROM supplier_terms")).scalar() == 1
    assert admin.post(f"/api/v1/onboarding/batches/{ids['sales']}/validate", headers=W,
                      json={"mapping": sales["mapping"]}).status_code == 409
    again = admin.post("/api/v1/onboarding/batches", headers=W, data={"kind": "sales", "rights": "our own ERP export"},
                       files={"file": ("sales.csv", sales_csv(), "text/csv")})
    assert again.status_code == 409 and again.json()["code"] == "duplicate_file"

    # grant a planner, who plans on the published snapshot
    assert admin.post("/api/v1/admin/members", headers=W, json={"email": dev_email("planner"), "role": "planner"}).status_code == 200
    planner = TestClient(app)
    login(planner, "planner")
    sc = planner.post("/api/v1/scenarios", headers={**W, "Idempotency-Key": uuid.uuid4().hex}, json={"name": "First plan"})
    assert sc.status_code == 200, sc.text
    out = sc.json()
    assert "SKU-1" in out["needs"] and out["plan"]["status"] in ("OPTIMAL", "FEASIBLE", "NO_ACTION")
    assert admin.post("/api/v1/admin/members", headers=W, json={"email": dev_email("planner"), "role": None}).json()["result"] == "removed"
    assert planner.get("/api/v1/overview", headers=W).status_code == 404       # revocation is immediate


def test_only_administrators_import_and_admins_cannot_demote_themselves(admin):
    viewer = TestClient(app)
    login(viewer, "viewer")
    U = {**H, "X-SupplyLens-Tenant": "uci-research"}
    r = viewer.post("/api/v1/onboarding/batches", headers=U, data={"kind": "stock", "rights": "our export"},
                    files={"file": ("s.csv", STOCK, "text/csv")})
    assert r.status_code == 403
    me = admin.post("/api/v1/admin/members", headers=U, json={"email": dev_email("tenant_admin"), "role": "viewer"})
    assert me.status_code == 409 and "themselves" in me.json()["message"]
    bad = admin.post("/api/v1/onboarding/batches", headers=U, data={"kind": "stock", "rights": "x"},
                     files={"file": ("s.csv", STOCK, "text/csv")})
    assert bad.status_code == 422 and bad.json()["code"] == "rights_required"
    junk = admin.post("/api/v1/onboarding/batches", headers=U, data={"kind": "stock", "rights": "our own export"},
                      files={"file": ("s.csv", b"\xff\xfe\x00bad", "text/csv")})
    assert junk.status_code == 422 and junk.json()["code"] == "not_utf8"
