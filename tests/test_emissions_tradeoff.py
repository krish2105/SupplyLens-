"""Cost, service and CO2 trade-off (F2): the CO2 cap in the planner and the epsilon-constraint sweep."""
import hashlib
import json
import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from supplylens.api.app import app
from supplylens.db import tenant_session
from supplylens.seed import dev_email
from supplylens_opt.emissions import grams_per_unit
from supplylens_opt.planner import Need, Offer, PlanRequest, PlanResult, input_hash, plan
from supplylens_opt.validator import validate

D = date(2026, 1, 5)


def offers(co2=True):
    near = dict(term_id="NEAR", supplier_id="UK", sku_id="S", unit_cost_minor=120, currency="GBP", moq=1, order_multiple=1,
                lead_time_days=3)
    far = dict(term_id="FAR", supplier_id="ASIA", sku_id="S", unit_cost_minor=100, currency="GBP", moq=1, order_multiple=1,
               lead_time_days=10)
    if co2:
        near["co2_grams_per_unit"], far["co2_grams_per_unit"] = 15, 159
    return [Offer(**near), Offer(**far)]


def request(cap=None, shortfall=False, co2=True):
    return PlanRequest(decision_date=D, need_by=D + timedelta(days=21), currency="GBP", budget_minor=10**6,
                       needs=[Need(sku_id="S", required_units=100)], offers=offers(co2), allow_shortfall=shortfall,
                       co2_cap_grams=cap)


def test_lane_factors_follow_the_quoted_lead_time():
    # 0.5 kg x 300 km x 0.10 kg/tkm = 15 g; x 1,500 km = 75 g; 18,000 km sea x 0.016 + 300 km road x 0.10 -> 159 g
    assert [grams_per_unit(d) for d in (1, 3, 4, 7, 8, 21)] == [15, 15, 75, 75, 159, 159]


def test_a_co2_cap_moves_the_order_to_the_cleaner_dearer_supplier_and_then_costs_service():
    free = plan(request())
    assert free.lines[0].supplier_id == "ASIA" and free.objective["co2_grams"] == 15_900     # cheapest wins uncapped
    capped = plan(request(cap=10_000))
    assert capped.lines[0].supplier_id == "UK" and capped.total_minor == 12_000                # cleaner, dearer
    assert capped.objective["co2_grams"] == 1_500 and not capped.violations
    tight = plan(request(cap=500, shortfall=True))
    assert tight.lines[0].quantity == 33 and tight.shortfall == {"S": 67}                      # 33 x 15 g <= 500 g
    blocked = plan(request(cap=500))
    assert blocked.status == "INFEASIBLE" and any("CO2 cap" in r for r in blocked.explanation)


def test_requests_without_co2_or_weights_keep_their_hash():
    req = request(co2=False)
    d = req.model_dump(mode="json")
    d.pop("co2_cap_grams")
    for o in d["offers"]:
        o.pop("co2_grams_per_unit")
    for n in d["needs"]:
        n.pop("shortage_weight")                                       # the fairness weight (F3) joins the same way
    before = hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert input_hash(req) == before                                   # approvals bound to old hashes still match
    assert input_hash(request(cap=10_000)) != input_hash(request())


def test_the_validator_rejects_a_plan_over_the_cap():
    req = request(cap=1_000)
    over = plan(request())                                             # the uncapped plan emits 15,900 g
    assert any("exceeds the cap" in e for e in validate(req, PlanResult(**over.model_dump())))


@pytest.fixture()
def two_lane_world(clean_db, tenant_a):
    """One SKU, sold daily, with a cheap far supplier (10 days, 60p) and a dearer near one (3 days, 120p)."""
    did = uuid.uuid4()
    with tenant_session(tenant_a) as s:
        s.execute(text("INSERT INTO datasets (id, tenant_id, name, source_kind, license, file_name, sha256, bytes, "
                       "schema_version, status) VALUES (:i,:t,'synthetic','generated','n/a','f','h',1,'v','READY')"),
                  {"i": did, "t": tenant_a})
        s.execute(text("INSERT INTO products (tenant_id, sku_id, source_kind) VALUES (:t,'S','generated')"), {"t": tenant_a})
        s.execute(text("INSERT INTO locations VALUES (:t,'WH','WH','warehouse',true,'synthetic')"), {"t": tenant_a})
        s.execute(text("INSERT INTO inventory_positions VALUES (:t,'WH','Z','S','2011-05-20',0,0,0,NULL,'simulated',NULL)"),
                  {"t": tenant_a})
        for sup, cost, lead in (("UK", 120, 3), ("ASIA", 60, 10)):   # far must cover a longer window, so it is much cheaper
            s.execute(text("INSERT INTO suppliers VALUES (:t,:s,:s,'generated','synthetic')"), {"t": tenant_a, "s": sup})
            s.execute(text("""INSERT INTO supplier_terms (term_id, tenant_id, supplier_id, sku_id, unit_cost_minor, currency,
                moq, order_multiple, lead_time_days, valid_from, known_at, value_kind, source_kind) VALUES (:id,:t,:s,'S',:c,
                'GBP',1,1,:l,'2011-01-01','2011-01-01T00:00:00Z','simulated','generated')"""),
                      {"id": f"T-{sup}", "t": tenant_a, "s": sup, "c": cost, "l": lead})
        s.execute(text("INSERT INTO tenant_settings VALUES (:t,'2011-05-20T12:00:00Z','GBP',:d,NULL,CAST(:p AS jsonb))"),
                  {"t": tenant_a, "d": did, "p": '{"weekly_budget_minor": 1000000, "coverage_days": 21}'})
        for i in range(140):
            s.execute(text("INSERT INTO sales_daily VALUES (:t,:d,'S','WH',:day,:u)"),
                      {"t": tenant_a, "d": did, "day": date(2011, 1, 1) + timedelta(days=i), "u": (i % 7) + 5})
    return tenant_a


def test_the_frontier_trades_cost_service_and_co2_and_is_for_planners(two_lane_world):
    H = {"X-Requested-With": "supplylens", "X-SupplyLens-Tenant": "uci-research"}
    c = TestClient(app)
    c.post("/api/v1/auth/dev-login", json={"email": dev_email("planner")}, headers=H)
    r = c.post("/api/v1/scenarios/emissions-frontier", headers=H, json={})
    assert r.status_code == 200, r.text
    pts = r.json()["points"]
    assert pts[0]["cap_share"] is None and pts[0]["service"] == 1.0
    co2 = [p["co2_grams"] for p in pts]
    assert all(b <= a for a, b in zip(co2, co2[1:], strict=False))          # a tighter cap never emits more
    assert all(p["co2_grams"] <= p["cap_grams"] for p in pts[1:])
    # first the cap shifts the order to the near supplier (spend rises, service kept), then it costs service
    assert max(p["spend_minor"] for p in pts if p["service"] == 1.0) > pts[0]["spend_minor"]
    assert pts[-1]["service"] < 1.0
    assert r.json()["value_kinds"]["co2"] == "assumed"
    viewer = TestClient(app)
    viewer.post("/api/v1/auth/dev-login", json={"email": dev_email("viewer")}, headers=H)
    assert viewer.post("/api/v1/scenarios/emissions-frontier", headers=H, json={}).status_code == 403
