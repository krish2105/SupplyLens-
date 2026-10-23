"""Phase 4B: API wording and figures that the screen audit found misleading."""
import uuid
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from supplylens.api.app import app
from supplylens.db import tenant_session
from supplylens.seed import dev_email

H = {"X-Requested-With": "supplylens"}
AS_OF = date(2011, 5, 20)


def viewer():
    c = TestClient(app)
    c.post("/api/v1/auth/dev-login", json={"email": dev_email("viewer")}, headers=H)
    return c


@pytest.fixture()
def priced_and_unpriced(clean_db, tenant_a):
    """Two products short of cover and two in excess; one of each has a recorded selling price, the other none."""
    did = uuid.uuid4()
    with tenant_session(tenant_a) as s:
        s.execute(text("INSERT INTO datasets (id, tenant_id, name, source_kind, license, file_name, sha256, bytes, "
                       "schema_version, status) VALUES (:i,:t,'synthetic','generated','n/a','f','h',1,'v','READY')"),
                  {"i": did, "t": tenant_a})
        s.execute(text("INSERT INTO locations VALUES (:t,'WH','WH','warehouse',true,'synthetic')"), {"t": tenant_a})
        for sku, on_hand in (("SHORT-PRICED", 4), ("SHORT-UNPRICED", 4), ("EXCESS-PRICED", 500), ("EXCESS-UNPRICED", 500)):
            s.execute(text("INSERT INTO products (tenant_id, sku_id, source_kind) VALUES (:t,:k,'generated')"), {"t": tenant_a, "k": sku})
            s.execute(text("INSERT INTO inventory_positions VALUES (:t,'WH','Z',:k,:d,:o,0,0,NULL,'simulated',NULL)"),
                      {"t": tenant_a, "k": sku, "d": AS_OF, "o": on_hand})
            for i in range(28):
                s.execute(text("INSERT INTO sales_daily VALUES (:t,:d,:k,'WH',:day,2)"),
                          {"t": tenant_a, "d": did, "k": sku, "day": AS_OF - timedelta(days=i)})
        for row, sku in enumerate(("SHORT-PRICED", "EXCESS-PRICED")):
            s.execute(text("INSERT INTO sales_lines VALUES (:t,:d,'s',:r,'INV1',:k,2,250,'GBP',:at,NULL,NULL)"),
                      {"t": tenant_a, "d": did, "r": row, "k": sku, "at": datetime(2011, 5, 10, 12)})
        s.execute(text("INSERT INTO tenant_settings VALUES (:t,'2011-05-20T12:00:00Z','GBP',:d,NULL,'{}'::jsonb)"),
                  {"t": tenant_a, "d": did})
    return tenant_a


def test_exceptions_without_a_selling_price_state_no_money_figure_instead_of_zero(priced_and_unpriced):
    r = viewer().get("/api/v1/exceptions", headers={**H, "X-SupplyLens-Tenant": "uci-research"})
    assert r.status_code == 200, r.text
    by = {i["sku_id"]: i for i in r.json()["items"] if i.get("sku_id")}
    assert by["SHORT-PRICED"]["materiality_minor"] == int((2 * 7 - 4) * 250)          # 7-day shortfall x median price
    assert by["EXCESS-PRICED"]["materiality_minor"] == int((500 - 2 * 90) * 250 * 0.55)
    for sku in ("SHORT-UNPRICED", "EXCESS-UNPRICED"):
        # before: 0, shown as "£0.00 at risk" next to a high-severity shortage
        assert by[sku]["materiality_minor"] is None, by[sku]
        assert "no selling price recorded" in by[sku]["materiality_basis"]
    # ranking still works with a missing figure: the priced shortage outranks the unpriced one at the same severity
    order = [i["sku_id"] for i in r.json()["items"] if i["kind"] == "shortage_risk"]
    assert order.index("SHORT-PRICED") < order.index("SHORT-UNPRICED")


def test_market_summary_says_what_is_true_for_the_workspace_being_read(clean_db):
    c = viewer()
    own = c.get("/api/v1/market/summary", headers={**H, "X-SupplyLens-Tenant": "contract-research"}).json()
    other = c.get("/api/v1/market/summary", headers={**H, "X-SupplyLens-Tenant": "uci-research"}).json()
    assert own["available"] is False and other["available"] is False
    # before: both said "Switch to Contract research", including to a reader already in it
    assert "imported into this workspace" in own["message"] and "Switch" not in own["message"]
    assert "lives in the Contract research workspace" in other["message"]
