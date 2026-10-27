"""ABC/XYZ classes, statistical safety stock and the cost of service (F4)."""
import math
import uuid
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from supplylens.api.app import app
from supplylens.db import tenant_session
from supplylens.planning.classes import abc_of, safety_stock, xyz_of, z_for
from supplylens.seed import dev_email

H = {"X-Requested-With": "supplylens", "X-SupplyLens-Tenant": "uci-research"}
AS_OF = date(2011, 5, 20)


def test_class_boundaries_and_the_safety_stock_formula():
    assert [abc_of(x) for x in (0.0, 0.79, 0.80, 0.949, 0.95, 0.99)] == ["A", "A", "B", "B", "C", "C"]
    assert [xyz_of(x) for x in (0.1, 0.5, 0.99, 1.0, None)] == ["X", "Y", "Y", "Z", None]
    assert z_for(0.95) == pytest.approx(1.6449, abs=1e-4)
    assert safety_stock(z_for(0.95), 10.0, 4) == pytest.approx(1.6449 * 10 * 2, abs=1e-3)   # z * sigma * sqrt(L)
    assert safety_stock(z_for(0.40), 10.0, 4) == 0.0                                         # never negative stock


@pytest.fixture()
def three_products(clean_db, tenant_a):
    """BIG: about 82 % of value, steady demand. MID: about 15 %, a week on and a week off. SMALL: the rest, one sale a week."""
    did = uuid.uuid4()
    with tenant_session(tenant_a) as s:
        s.execute(text("INSERT INTO datasets (id, tenant_id, name, source_kind, license, file_name, sha256, bytes, "
                       "schema_version, status) VALUES (:i,:t,'synthetic','generated','n/a','f','h',1,'v','READY')"),
                  {"i": did, "t": tenant_a})
        s.execute(text("INSERT INTO locations VALUES (:t,'WH','WH','warehouse',true,'synthetic')"), {"t": tenant_a})
        s.execute(text("INSERT INTO suppliers (tenant_id, supplier_id, name, source_kind, value_kind) VALUES (:t,'SUP','Supplier','synthetic','assumed')"),
                  {"t": tenant_a})
        for sku, cost in (("BIG", 100), ("MID", 200), ("SMALL", 300)):
            s.execute(text("INSERT INTO products (tenant_id, sku_id, source_kind) VALUES (:t,:k,'generated')"), {"t": tenant_a, "k": sku})
            s.execute(text("INSERT INTO inventory_positions VALUES (:t,'WH','Z',:k,:d,100,0,0,NULL,'simulated',NULL)"),
                      {"t": tenant_a, "k": sku, "d": AS_OF})
            s.execute(text("""INSERT INTO supplier_terms (tenant_id, term_id, supplier_id, sku_id, unit_cost_minor, currency, moq,
                order_multiple, lead_time_days, valid_from, known_at, value_kind, source_kind) VALUES
                (:t,:id,'SUP',:k,:c,'GBP',1,1,4,'2010-01-01','2010-01-01T00:00:00Z','assumed','synthetic')"""),
                      {"t": tenant_a, "id": f"T-{sku}", "k": sku, "c": cost})
        row = 0
        for i in range(364):
            day = AS_OF - timedelta(days=i)
            for sku, units, price in (("BIG", 16, 50), ("MID", 6 if i % 14 < 7 else 0, 50), ("SMALL", 7 if i % 7 == 0 else 0, 25)):
                if units:
                    s.execute(text("INSERT INTO sales_daily VALUES (:t,:d,:k,'WH',:day,:u)"),
                              {"t": tenant_a, "d": did, "k": sku, "day": day, "u": units})
                    s.execute(text("INSERT INTO sales_lines VALUES (:t,:d,'s',:r,'I',:k,:u,:p,'GBP',:at,NULL,NULL)"),
                              {"t": tenant_a, "d": did, "r": row, "k": sku, "u": units, "p": price,
                               "at": datetime.combine(day, datetime.min.time()) + timedelta(hours=12)})
                    row += 1
        s.execute(text("INSERT INTO tenant_settings VALUES (:t,'2011-05-20T12:00:00Z','GBP',:d,NULL,'{}'::jsonb)"),
                  {"t": tenant_a, "d": did})
    return tenant_a


def get(c, **params):
    r = c.get("/api/v1/inventory/classes", headers=H, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_classes_rank_value_and_variability_and_price_safety_stock(three_products):
    c = TestClient(app)
    c.post("/api/v1/auth/dev-login", json={"email": dev_email("viewer")}, headers=H)
    r = get(c)
    assert r["basis"] == "revenue" and r["products_classified"] == 3
    by = {x["sku_id"]: x for x in r["stocked"]}
    assert (by["BIG"]["abc"], by["MID"]["abc"], by["SMALL"]["abc"]) == ("A", "B", "C")
    # BIG and SMALL sell the same every week (X); MID sells one week and not the next, so its weekly CV is about 1 (Z)
    assert (by["BIG"]["xyz"], by["MID"]["xyz"], by["SMALL"]["xyz"]) == ("X", "Z", "X")
    # BIG sells 16 every day: no daily variability, so no safety stock is needed whatever the service level
    assert by["BIG"]["sd_daily"] == 0 and by["BIG"]["safety_stock_units"] == 0
    # MID: 6 a day for a week, then none; sigma over 91 days; lead time 4 days; class B -> 95 %
    sigma = by["MID"]["sd_daily"]
    assert by["MID"]["service_level"] == 0.95
    assert by["MID"]["safety_stock_units"] == math.ceil(z_for(0.95) * sigma * 2)
    assert by["MID"]["holding_cost_minor_per_year"] == round(by["MID"]["safety_stock_units"] * 200 * 0.25)
    # the curve rises with the service level, and a higher policy costs more
    costs = [p["holding_cost_minor_per_year"] for p in r["curve"]]
    assert costs == sorted(costs) and costs[-1] > costs[0]
    assert get(c, service_b=0.99)["policy_point"]["holding_cost_minor_per_year"] > r["policy_point"]["holding_cost_minor_per_year"]


def test_classes_fall_back_to_units_without_prices_and_say_so(three_products):
    with tenant_session(three_products) as s:
        s.execute(text("DELETE FROM sales_lines"))
    c = TestClient(app)
    c.post("/api/v1/auth/dev-login", json={"email": dev_email("viewer")}, headers=H)
    r = get(c)
    assert r["basis"] == "units" and r["currency"] is None


def test_a_workspace_without_settings_returns_nothing_rather_than_failing(clean_db, tenant_a):
    c = TestClient(app)
    c.post("/api/v1/auth/dev-login", json={"email": dev_email("viewer")}, headers=H)
    assert get(c)["effective_date"] is None


def test_service_levels_are_validated(three_products):
    c = TestClient(app)
    c.post("/api/v1/auth/dev-login", json={"email": dev_email("viewer")}, headers=H)
    assert c.get("/api/v1/inventory/classes", headers=H, params={"service_a": 1.0}).status_code == 422
    assert c.get("/api/v1/inventory/classes", headers=H, params={"service_c": 0.3}).status_code == 422
