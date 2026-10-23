"""Phase 4: API behaviour the web screens rely on (inventory per SKU@location, P1-FE-02)."""
import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from supplylens.api.app import app
from supplylens.db import tenant_session
from supplylens.seed import dev_email

H = {"X-Requested-With": "supplylens"}
UCI = {**H, "X-SupplyLens-Tenant": "uci-research"}
AS_OF = date(2011, 5, 20)


@pytest.fixture()
def two_sites(clean_db, tenant_a):
    """S1 stocked at WH and WH2 with sales recorded at each; S2 stocked only at WH but sold under another code (SHOP)."""
    did = uuid.uuid4()
    with tenant_session(tenant_a) as s:
        s.execute(text("INSERT INTO datasets (id, tenant_id, name, source_kind, license, file_name, sha256, bytes, "
                       "schema_version, status) VALUES (:i,:t,'synthetic','generated','n/a','f','h',1,'v','READY')"),
                  {"i": did, "t": tenant_a})
        for sku in ("S1", "S2"):
            s.execute(text("INSERT INTO products (tenant_id, sku_id, source_kind) VALUES (:t,:k,'generated')"), {"t": tenant_a, "k": sku})
        for loc in ("WH", "WH2", "SHOP"):
            s.execute(text("INSERT INTO locations VALUES (:t,:l,:l,'warehouse',true,'synthetic')"), {"t": tenant_a, "l": loc})
        for loc, sku, on_hand in (("WH", "S1", 50), ("WH2", "S1", 5), ("WH", "S2", 30)):
            s.execute(text("INSERT INTO inventory_positions VALUES (:t,:l,'Z',:k,:d,:o,0,0,NULL,'simulated',NULL)"),
                      {"t": tenant_a, "l": loc, "k": sku, "d": AS_OF, "o": on_hand})
        # an older snapshot must not shadow the latest one at the same location
        s.execute(text("INSERT INTO inventory_positions VALUES (:t,'WH2','Z','S1',:d,999,0,0,NULL,'simulated',NULL)"),
                  {"t": tenant_a, "d": AS_OF - timedelta(days=10)})
        for i in range(28):
            day = AS_OF - timedelta(days=i)
            for loc, sku, units in (("WH", "S1", 2), ("WH2", "S1", 1), ("SHOP", "S2", 3)):
                s.execute(text("INSERT INTO sales_daily VALUES (:t,:d,:k,:l,:day,:u)"),
                          {"t": tenant_a, "d": did, "k": sku, "l": loc, "day": day, "u": units})
        s.execute(text("INSERT INTO tenant_settings VALUES (:t,'2011-05-20T12:00:00Z','GBP',:d,NULL,'{}'::jsonb)"),
                  {"t": tenant_a, "d": did})
    return tenant_a


def test_inventory_has_a_row_per_sku_and_location_with_that_locations_sales(two_sites):
    c = TestClient(app)
    c.post("/api/v1/auth/dev-login", json={"email": dev_email("viewer")}, headers=H)
    r = c.get("/api/v1/inventory", headers=UCI)
    assert r.status_code == 200
    rows = {(i["sku_id"], i["location_id"]): i for i in r.json()["items"]}
    assert set(rows) == {("S1", "WH"), ("S1", "WH2"), ("S2", "WH")}            # before: one S1 row, the other site's stock lost
    assert (rows[("S1", "WH")]["on_hand"], rows[("S1", "WH2")]["on_hand"]) == (50, 5)   # latest snapshot per location
    assert rows[("S1", "WH")]["avg_daily"] == pytest.approx(2.0)                # each location's own sales
    assert rows[("S1", "WH2")]["avg_daily"] == pytest.approx(1.0)
    # S2 is stocked at one location and sold under another code: it keeps all of its sales, as before
    assert rows[("S2", "WH")]["avg_daily"] == pytest.approx(3.0)
    assert r.json()["total"] == 3


def test_exceptions_assess_each_location_separately(two_sites):
    c = TestClient(app)
    c.post("/api/v1/auth/dev-login", json={"email": dev_email("viewer")}, headers=H)
    r = c.get("/api/v1/exceptions", headers=UCI)
    assert r.status_code == 200
    # 5 units at 1/day is under a week of cover at WH2 even though WH holds 50 at 2/day (25 days)
    short = [i for i in r.json()["items"] if i["kind"] == "shortage_risk" and i.get("sku_id") == "S1"]
    assert len(short) == 1 and "at WH2" in short[0]["detail"], r.json()["items"]


# ----------------------------------------------------------------------------- document upload (journey 4)
DEMO = {**H, "X-SupplyLens-Tenant": "demo"}
CONTRACT = (b"# Supply agreement\nThis agreement covers carton supply.\n\n"
            b"Section 1 Minimum order quantity\nThe minimum order quantity is 40 cartons per order.\n")


@pytest.fixture()
def demo_world(clean_db, tenant_b):
    from supplylens.simulation import demo
    demo.load(tenant_b)
    return tenant_b


def signed(role):
    c = TestClient(app)
    c.post("/api/v1/auth/dev-login", json={"email": dev_email(role)}, headers=H)
    return c


def post_doc(c, data=CONTRACT, name="carton-agreement.txt", **form):
    fields = {"title": "Carton agreement", "doc_type": "contract", "version_label": "v1", "valid_from": "2026-11-01", **form}
    return c.post("/api/v1/documents", headers=DEMO, data=fields, files={"file": (name, data, "text/plain")})


def test_an_administrator_adds_a_contract_and_an_amendment_that_extends_its_history(demo_world):
    from datetime import UTC, datetime
    admin = signed("tenant_admin")
    before = datetime.now(UTC)
    r = post_doc(admin, valid_from="2026-11-01", known_at="2001-01-01")          # a typed known_at is ignored
    assert r.status_code == 201, r.text
    v1 = r.json()
    assert v1["chunks"] >= 2 and datetime.fromisoformat(v1["known_at"]) >= before
    amended = CONTRACT.replace(b"40 cartons", b"60 cartons")
    bad = post_doc(admin, data=amended, name="amendment.txt", version_label="v2", valid_from="2026-10-01",
                   supersedes_version_id=v1["version_id"])
    assert bad.status_code == 422 and bad.json()["code"] == "invalid_dates"     # cannot start before what it replaces
    r2 = post_doc(admin, data=amended, name="amendment.txt", version_label="v2", valid_from="2026-12-01",
                  supersedes_version_id=v1["version_id"], doc_type="amendment")
    assert r2.status_code == 201 and r2.json()["document_id"] == v1["document_id"]
    docs = signed("viewer").get("/api/v1/documents", headers=DEMO).json()
    history = [d for d in docs if d["document_id"] == v1["document_id"]]
    assert [d["version_label"] for d in history] == ["v1", "v2"] and history[1]["supersedes_version_id"] == v1["version_id"]
    hits = signed("viewer").get("/api/v1/evidence/search", headers=DEMO,
                                params={"q": "minimum order quantity cartons", "effective_date": "2026-12-15"}).json()
    assert hits["results"] and hits["results"][0]["version_label"] == "v2"         # the version in force is cited
    audit = admin.get("/api/v1/audit", headers=DEMO).json()
    assert sum(e["action"] == "document.uploaded" for e in audit) == 2


def test_document_upload_is_for_administrators_and_validates_what_it_stores(demo_world):
    for role in ("viewer", "planner", "approver"):
        assert post_doc(signed(role)).status_code == 403
    admin = signed("tenant_admin")
    cases = [(dict(name="contract.pdf"), 422, "unsupported_type"), (dict(data=b""), 422, "empty_file"),
             (dict(data=b"\xff\xfe\x00bad"), 422, "not_utf8"), (dict(data=b"text\x00more"), 422, "binary_content"),
             (dict(data=b"x" * 1_000_001), 413, "file_too_large"),
             (dict(valid_from="2026-11-01", valid_to="2026-10-01"), 422, "invalid_dates"),
             (dict(supplier_id="NO-SUCH-SUPPLIER"), 422, "unknown_supplier"),
             (dict(supersedes_version_id=str(uuid.uuid4())), 404, "unknown_version")]
    for kw, status, code in cases:
        r = post_doc(admin, **kw)
        assert (r.status_code, r.json()["code"]) == (status, code), (kw, r.text)
    assert post_doc(admin).status_code == 201
    dup = post_doc(admin)
    assert (dup.status_code, dup.json()["code"]) == (409, "duplicate_document")


def test_a_version_in_another_workspace_cannot_be_superseded(demo_world, tenant_a):
    admin = signed("tenant_admin")
    v = post_doc(admin).json()["version_id"]
    r = admin.post("/api/v1/documents", headers={**H, "X-SupplyLens-Tenant": "uci-research"},
                   data={"title": "x", "version_label": "v2", "valid_from": "2026-12-01", "supersedes_version_id": v},
                   files={"file": ("x.txt", b"other text", "text/plain")})
    assert (r.status_code, r.json()["code"]) == (404, "unknown_version")
