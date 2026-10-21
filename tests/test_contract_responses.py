"""ARC-02: every endpoint the interface reads is served through its declared response model (a mismatch is a 500),
and every status is exercised with realistic data: the Demo workspace, a small synthetic sales history, synthetic
public awards and the committed experiment artifacts. Also checks the OpenAPI contract names each of them."""
import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from supplylens.api.app import app
from supplylens.db import admin_engine, tenant_session
from supplylens.seed import seed, tenant_id
from supplylens.simulation import demo
from supplylens_worker.main import tick

H = {"X-Requested-With": "supplylens"}
DEMO = {**H, "X-SupplyLens-Tenant": "demo"}
UCI = {**H, "X-SupplyLens-Tenant": "uci-research"}
CR = {**H, "X-SupplyLens-Tenant": "contract-research"}
RUN = {"mode": "draft", "sku_ids": ["DEMO-REF-SKU"], "knowledge_cutoff": "2026-10-20T09:00:00Z",
       "effective_date": "2026-10-20", "budget_minor": 18000, "currency": "USD", "allow_shortfall": False}


def login(c, role):
    assert c.post("/api/v1/auth/dev-login", json={"email": f"{role}@dev.supplylens.local"}, headers=H).status_code == 200


@pytest.fixture(scope="module")
def world():
    seed()
    with admin_engine().begin() as conn:
        tables = conn.execute(text("select string_agg(quote_ident(tablename), ', ') from pg_tables where schemaname='public' "
                                   "and tablename not in ('alembic_version','tenants','users','memberships','tenant_deletions')")).scalar()
        conn.execute(text(f"TRUNCATE {tables}, sandbox_erp.purchase_orders, sandbox_erp.fault_injection CASCADE"))
    demo.load(tenant_id("demo"))
    c = TestClient(app)
    login(c, "planner")
    run_id = c.post("/api/v1/agent-runs", json=RUN, headers={**DEMO, "Idempotency-Key": uuid.uuid4().hex}).json()["run_id"]
    for _ in range(10):
        tick()
        d = c.get(f"/api/v1/agent-runs/{run_id}", headers=DEMO).json()
        if d["status"] not in ("QUEUED", "RUNNING"):
            break
    action_id = d["actions"][0]["id"]
    # a small synthetic sales history in the UCI workspace (forecasts, inventory cover, scenarios)
    t = tenant_id("uci-research")
    did = uuid.uuid4()
    with tenant_session(t) as s:
        s.execute(text("INSERT INTO datasets (id, tenant_id, name, source_kind, license, file_name, sha256, bytes, schema_version, "
                       "status, report) VALUES (:i,:t,'synthetic sales','generated','n/a','f','h',1,'v','READY','{}'::jsonb)"),
                  {"i": did, "t": t})
        s.execute(text("INSERT INTO products (tenant_id, sku_id, description, unit, source_kind) VALUES (:t,'S1','Synthetic','unit','generated')"), {"t": t})
        s.execute(text("INSERT INTO locations VALUES (:t,'WH','Warehouse','warehouse',true,'synthetic')"), {"t": t})
        s.execute(text("INSERT INTO inventory_positions VALUES (:t,'WH','Z1','S1','2011-03-01',50,5,0,500,'simulated',NULL)"), {"t": t})
        s.execute(text("INSERT INTO suppliers VALUES (:t,'SUP','Supplier','generated','synthetic')"), {"t": t})
        s.execute(text("INSERT INTO supplier_terms (term_id, tenant_id, supplier_id, sku_id, unit_cost_minor, currency, moq, order_multiple, "
                       "lead_time_days, valid_from, known_at, value_kind, source_kind) VALUES ('T1',:t,'SUP','S1',100,'GBP',10,5,3,"
                       "'2011-01-01','2011-01-01T00:00:00Z','simulated','generated')"), {"t": t})
        s.execute(text("INSERT INTO tenant_settings VALUES (:t,'2011-03-01T12:00:00Z','GBP',:d,NULL,CAST(:p AS jsonb))"),
                  {"t": t, "d": did, "p": '{"weekly_budget_minor": 100000, "coverage_days": 14, "safety_days": 3}'})
        for i in range(70):
            s.execute(text("INSERT INTO sales_daily VALUES (:t,:d,'S1','WH',:day,:u)"),
                      {"t": t, "d": did, "day": date(2011, 1, 3) + timedelta(days=i), "u": (i % 7) + 2})
    # public awards in the contract-research workspace (market endpoints)
    cr = tenant_id("contract-research")
    wb = uuid.uuid4()
    with tenant_session(cr) as s:
        s.execute(text("INSERT INTO datasets (id, tenant_id, name, source_kind, license, file_name, sha256, bytes, schema_version, "
                       "status, report) VALUES (:i,:t,'World Bank IPF contract awards','public','CC BY 4.0','f','h2',1,'v','READY','{}'::jsonb)"),
                  {"i": wb, "t": cr})
        for n in range(6):
            s.execute(text("""INSERT INTO public_awards (tenant_id, dataset_id, source_row, wb_contract_number, supplier_id, supplier,
                supplier_country, borrower_country, region, procurement_category, procurement_method, project_id, project_name,
                contract_description, signing_date, fiscal_year, amount_usd) VALUES (:t,:d,:n,:c,:sid,:sn,'Kenya','Uganda','AFR',
                'Goods','Open',:p,'Roads','Gravel',:sd,:fy,:amt)"""),
                      {"t": cr, "d": wb, "n": n, "c": f"C{n}", "sid": f"S{n % 2}", "sn": f"Acme {n % 2}", "p": "P1",
                       "sd": date(2020, 1 + n, 1), "fy": 2020, "amt": 1000.5 * (n + 1)})
    return {"c": c, "action_id": action_id, "run_id": run_id, "version_id": c.get("/api/v1/documents", headers=DEMO).json()[0]["version_id"]}


def get(world, path, headers=DEMO, role="viewer", **params):
    login(world["c"], role)
    r = world["c"].get(path, headers=headers, params=params)
    assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:400]}"
    return r.json()


def test_session_and_overview(world):
    c = world["c"]
    login(c, "viewer")
    assert c.get("/api/v1/auth/dev-users").json()["users"][0]["roles"]
    me = c.get("/api/v1/me").json()
    assert {m["slug"] for m in me["memberships"]} >= {"demo", "uci-research", "contract-research"}
    ov = get(world, "/api/v1/overview")
    assert ov["settings"]["currency"] == "GBP" and ov["capabilities"] and ov["counts"]["suppliers"] > 0
    assert get(world, "/api/v1/overview", UCI)["dataset"]["name"] == "synthetic sales"
    assert get(world, "/api/v1/datasets", UCI)[0]["report"]["totals"] == {}
    q = get(world, f"/api/v1/datasets/{get(world, '/api/v1/datasets', UCI)[0]['id']}/quarantine", UCI)
    assert q["summary"] == [] and q["next_cursor"] is None
    assert get(world, "/health", {})["database"] == "ok"


def test_inventory_products_and_warehouse(world):
    inv = get(world, "/api/v1/inventory", UCI)
    s1 = next(i for i in inv["items"] if i["sku_id"] == "S1")
    assert s1["health"] in ("healthy", "shortage_risk", "excess") and s1["days_of_cover"] is not None
    d = get(world, "/api/v1/inventory")
    assert d["items"] and all(i["health"] == "no_sales_data" for i in d["items"])
    sales = get(world, "/api/v1/products/S1/sales", UCI)
    assert len(sales["daily"]) == 70 and sales["product"]["sku_id"] == "S1"
    wh = get(world, "/api/v1/warehouse")
    assert wh["schematic"] and wh["slots"]
    ex = get(world, "/api/v1/exceptions", DEMO)
    assert "items" in ex
    assert get(world, "/api/v1/exceptions", UCI, effective_date="2011-03-01")["currency"] == "GBP"


def test_forecasts_and_models(world):
    c = world["c"]
    login(c, "planner")
    r = c.post("/api/v1/forecasts", json={"sku_ids": ["S1"], "origin": "2011-03-01", "horizon": 14}, headers={**UCI, "Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 200, r.text
    f = r.json()
    assert f["family"] == "seasonal_naive" and len(f["points"]) == 14 and f["points"][0]["q10"] <= f["points"][0]["q90"]
    again = get(world, f"/api/v1/forecasts/{f['id']}", UCI)
    assert again["id"] == f["id"] and again["quality_flags"] == {}
    models = get(world, "/api/v1/models", UCI)
    assert models[0]["family"] == "seasonal_naive" and models[0]["status"] == "CHAMPION"


def test_scenarios(world):
    c = world["c"]
    login(c, "planner")
    r = c.post("/api/v1/scenarios", json={"name": "Base", "budget_minor": 100000}, headers={**UCI, "Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 200, r.text
    sc = r.json()
    assert sc["metrics"]["skus_assessed"] == 1 and "plan" in sc and sc["terms"]["applicable"] >= 0
    rows = get(world, "/api/v1/scenarios", UCI)
    assert rows[0]["name"] == "Base" and rows[0]["metrics"]["skus_assessed"] == 1


def test_terms_documents_and_evidence(world):
    t = get(world, "/api/v1/terms", DEMO, sku_id="DEMO-REF-SKU", knowledge_cutoff="2026-10-20T09:00:00Z", effective_date="2026-10-20")
    assert t["applicable"] and t["ignored"] and isinstance(t["conflicts"], list)
    docs = get(world, "/api/v1/documents")
    assert docs and docs[0]["chunks"] > 0
    v = get(world, f"/api/v1/documents/versions/{world['version_id']}")
    assert v["text"] and v["chunks"] and v["untrusted_content"] is True and v["id"] == world["version_id"]
    assert get(world, f"/api/v1/documents/versions/{world['version_id']}/labels") == []
    ev = get(world, "/api/v1/evidence/search", DEMO, q="minimum order quantity DEMO-REF-SKU")
    assert ev["results"] and ev["answer"]["claims"] and ev["filters"]["role"] == "viewer"
    miss = get(world, "/api/v1/evidence/search", DEMO, q="ZZZ-UNKNOWN-9 quantity")
    assert miss["answer"]["abstained"] is True


def test_runs_actions_and_sandbox(world):
    runs = get(world, "/api/v1/agent-runs")
    assert runs[0]["created_by"].endswith("@dev.supplylens.local") and runs[0]["actions"] == 1
    d = get(world, f"/api/v1/agent-runs/{world['run_id']}")
    assert d["status"] == "WAITING_FOR_APPROVAL" and d["plan"]["status"] == "OPTIMAL" and d["actions"][0]["supplier_id"]
    ev = get(world, f"/api/v1/agent-runs/{world['run_id']}/events")
    assert [e["node"] for e in ev][:2] == ["ACCEPT", "ACCEPT"] and ev[-1]["kind"] == "run_finished"
    acts = get(world, "/api/v1/actions")
    assert acts[0]["prepared_by"].endswith("@dev.supplylens.local")
    a = get(world, f"/api/v1/actions/{world['action_id']}")
    assert a["status"] == "PENDING_APPROVAL" and a["evidence"]["checks"] and a["approvals"] == [] and a["outbox"] is None
    # approve through the API and read back every result shape
    c = world["c"]
    login(c, "approver")
    ok = c.post(f"/api/v1/actions/{a['id']}/approve", headers={**DEMO, "Idempotency-Key": uuid.uuid4().hex},
                json={"payload_hash": a["payload_hash"], "expected_row_version": a["row_version"]})
    assert ok.status_code == 200 and ok.json()["status"] == "QUEUED"
    tick()
    done = get(world, f"/api/v1/actions/{a['id']}", role="approver")
    assert done["status"] == "RECONCILED" and done["approvals"][0]["decision"] == "APPROVED" and done["outbox"]["status"] == "DELIVERED"
    orders = get(world, "/api/v1/sandbox/orders")
    assert orders[0]["po_number"].startswith("SBX-PO-") and orders[0]["lines"]


def test_a_run_can_be_read_in_every_state_from_queued_to_finished(world):
    """Regression: a freshly queued run has no state yet (the UI polls it immediately)."""
    c = world["c"]
    login(c, "planner")
    run_id = c.post("/api/v1/agent-runs", json=RUN, headers={**DEMO, "Idempotency-Key": uuid.uuid4().hex}).json()["run_id"]
    queued = c.get(f"/api/v1/agent-runs/{run_id}", headers=DEMO)
    assert queued.status_code == 200, queued.text
    assert queued.json()["status"] == "QUEUED" and queued.json()["forecast"] is None and queued.json()["plan"] is None
    from supplylens.agent import graph
    seen = []
    orig = graph._checkpoint

    def spy(state):                       # read the run through the API after every checkpoint
        orig(state)
        r = c.get(f"/api/v1/agent-runs/{run_id}", headers=DEMO)
        assert r.status_code == 200, (state.get("next_node"), r.text[:300])
        seen.append(r.json()["status"])
    graph._checkpoint = spy
    try:
        for _ in range(10):
            tick()
            if c.get(f"/api/v1/agent-runs/{run_id}", headers=DEMO).json()["status"] not in ("QUEUED", "RUNNING"):
                break
    finally:
        graph._checkpoint = orig
    assert len(seen) >= 6


def test_admin_alerts_lifecycle_and_vitals(world):
    login(world["c"], "tenant_admin")
    m = get(world, "/api/v1/admin/members", role="tenant_admin")
    assert m["members"] and "tenant_admin" in m["role_matrix"]
    j = get(world, "/api/v1/admin/jobs", role="tenant_admin")
    assert j["jobs"] and j["outbox"] and "runs" in j["usage"]
    assert get(world, "/api/v1/admin/exports", role="tenant_admin") == []
    assert get(world, "/api/v1/admin/vitals", role="tenant_admin")["metrics"] == []
    assert get(world, "/api/v1/alerts")["open"] == 0
    assert get(world, "/api/v1/audit")[0]["id"] > 0
    ints = get(world, "/api/v1/integrations")
    assert {i["name"] for i in ints} >= {"Sandbox ERP", "Enterprise sign-in (OIDC)"}
    c = world["c"]
    r = c.post("/api/v1/telemetry/vitals", json={"metric": "LCP", "value": 900, "rating": "good", "route": "/"}, headers=DEMO)
    assert r.status_code == 204
    v = get(world, "/api/v1/admin/vitals", role="tenant_admin")["metrics"]
    assert v[0]["metric"] == "LCP" and v[0]["meets_target"] is True


def test_value_and_research_from_committed_artifacts(world):
    v = get(world, "/api/v1/value")
    assert v["ledger"] and v["disclaimer"]
    f1 = get(world, "/api/v1/research/forecast-study")
    assert f1["available"] and f1["cohort_size"] == 506 and f1["comparisons"] and f1["pinball_by_horizon"]
    for study in ("s1", "r1", "r2", "c1", "ib", "agt"):
        assert get(world, f"/api/v1/research/{study}")["available"] in (True, False)
    assert get(world, "/api/v1/research/zzz")["available"] is False


def test_market_endpoints_with_awards(world):
    s = get(world, "/api/v1/market/summary", CR)
    assert s["available"] and s["by_year"][0]["n"] == 6 and s["concentration_hhi"] and s["top_suppliers"]
    assert get(world, "/api/v1/market/summary", DEMO)["available"] is False
    hits = get(world, "/api/v1/market/suppliers", CR, q="Acme")
    assert hits and hits[0]["categories"] == ["Goods"]
    d = get(world, "/api/v1/market/suppliers/S0", CR)
    assert d["awards"] and d["awards"][0]["amount_usd"] > 0


def test_openapi_names_a_response_for_every_ui_endpoint():
    spec = app.openapi()
    must = ["/api/v1/me", "/api/v1/overview", "/api/v1/inventory", "/api/v1/actions/{action_id}", "/api/v1/agent-runs/{run_id}",
            "/api/v1/alerts", "/api/v1/admin/exports", "/api/v1/market/summary", "/api/v1/research/forecast-study"]
    for p in must:
        op = spec["paths"][p]["get"]
        schema = op["responses"]["200"]["content"]["application/json"]["schema"]
        refs = [schema.get("$ref"), schema.get("items", {}).get("$ref"), *[x.get("$ref") for x in schema.get("anyOf", [])]]
        assert any(refs), (p, schema)
