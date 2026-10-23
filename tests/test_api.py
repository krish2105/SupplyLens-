"""HTTP contract: auth, tenancy, CSRF, idempotency, role checks and validation."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from supplylens.api.app import app
from supplylens.simulation import demo

H = {"X-Requested-With": "supplylens", "X-SupplyLens-Tenant": "demo"}


@pytest.fixture()
def client(clean_db, tenant_b):
    demo.load(tenant_b)
    return TestClient(app)


def login(c, role):
    r = c.post("/api/v1/auth/dev-login", json={"email": f"{role}@dev.supplylens.local"},
               headers={"X-Requested-With": "supplylens"})
    assert r.status_code == 200


def test_unauthenticated_and_csrf(client):
    assert client.get("/api/v1/overview", headers=H).status_code == 401
    login(client, "planner")
    r = client.post("/api/v1/agent-runs", json={}, headers={"X-SupplyLens-Tenant": "demo", "Idempotency-Key": "k"})
    assert r.status_code == 403 and r.json()["code"] == "csrf"


def test_unknown_tenant_is_not_found(client):
    login(client, "viewer")
    assert client.get("/api/v1/overview", headers={**H, "X-SupplyLens-Tenant": "nope"}).status_code == 404


def test_overview_and_capabilities(client):
    login(client, "viewer")
    body = client.get("/api/v1/overview", headers=H).json()
    caps = {c["capability"]: c["status"] for c in body["capabilities"]}
    assert caps["Unit-sales forecasting"] == "unavailable"
    assert caps["Lost sales / unconstrained demand"] == "unavailable"


def test_agent_run_requires_idempotency_and_replays(client):
    login(client, "planner")
    body = {"mode": "draft", "sku_ids": ["DEMO-REF-SKU"], "knowledge_cutoff": "2026-10-20T09:00:00Z",
            "effective_date": "2026-10-20", "budget_minor": 18000, "currency": "USD", "allow_shortfall": False}
    assert client.post("/api/v1/agent-runs", json=body, headers=H).status_code == 428
    r1 = client.post("/api/v1/agent-runs", json=body, headers={**H, "Idempotency-Key": "run-1"})
    r2 = client.post("/api/v1/agent-runs", json=body, headers={**H, "Idempotency-Key": "run-1"})
    assert r1.status_code == r2.status_code == 202
    assert r1.json()["run_id"] == r2.json()["run_id"] and r2.json()["idempotent_replay"]
    r3 = client.post("/api/v1/agent-runs", json={**body, "budget_minor": 1}, headers={**H, "Idempotency-Key": "run-1"})
    assert r3.status_code == 409


def test_viewer_cannot_start_run_and_validation_errors(client):
    login(client, "viewer")
    r = client.post("/api/v1/agent-runs", json={"mode": "draft"}, headers={**H, "Idempotency-Key": "x"})
    assert r.status_code == 403
    login(client, "planner")
    r = client.post("/api/v1/agent-runs", json={"mode": "draft", "budget_minor": -5},
                    headers={**H, "Idempotency-Key": "y"})
    assert r.status_code == 422


def test_full_flow_over_http(client):
    from supplylens_worker.main import tick
    login(client, "planner")
    body = {"mode": "draft", "sku_ids": ["DEMO-REF-SKU"], "knowledge_cutoff": "2026-10-20T09:00:00Z",
            "effective_date": "2026-10-20", "budget_minor": 18000, "currency": "USD", "allow_shortfall": False}
    run_id = client.post("/api/v1/agent-runs", json=body, headers={**H, "Idempotency-Key": "flow"}).json()["run_id"]
    tick()
    detail = client.get(f"/api/v1/agent-runs/{run_id}", headers=H).json()
    assert detail["status"] == "WAITING_FOR_APPROVAL"
    action = client.get(f"/api/v1/actions/{detail['actions'][0]['id']}", headers=H).json()
    login(client, "approver")
    ap = client.post(f"/api/v1/actions/{action['id']}/approve",
                     json={"payload_hash": action["payload_hash"], "expected_row_version": action["row_version"]},
                     headers={**H, "Idempotency-Key": "ap-1"})
    assert ap.status_code == 200 and ap.json()["status"] == "QUEUED"
    again = client.post(f"/api/v1/actions/{action['id']}/approve",
                        json={"payload_hash": action["payload_hash"], "expected_row_version": action["row_version"]},
                        headers={**H, "Idempotency-Key": "ap-1"})
    assert again.status_code == 200 and again.json()["idempotent_replay"]
    tick()
    final = client.get(f"/api/v1/actions/{action['id']}", headers=H).json()
    assert final["status"] == "RECONCILED"
    orders = client.get("/api/v1/sandbox/orders", headers=H).json()
    assert len(orders) == 1 and orders[0]["supplier_id"] == "DEMO-REF-B"
    assert client.get(f"/api/v1/agent-runs/{run_id}", headers=H).json()["status"] == "COMPLETE"
    events = client.get(f"/api/v1/agent-runs/{run_id}/events", headers=H).json()
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)


def test_cross_tenant_action_access_denied(client):
    from supplylens_worker.main import tick
    login(client, "planner")
    body = {"mode": "draft", "sku_ids": ["DEMO-REF-SKU"], "knowledge_cutoff": "2026-10-20T09:00:00Z",
            "effective_date": "2026-10-20", "budget_minor": 18000, "currency": "USD", "allow_shortfall": False}
    run_id = client.post("/api/v1/agent-runs", json=body, headers={**H, "Idempotency-Key": "xt"}).json()["run_id"]
    tick()
    aid = client.get(f"/api/v1/agent-runs/{run_id}", headers=H).json()["actions"][0]["id"]
    other = {**H, "X-SupplyLens-Tenant": "uci-research"}
    assert client.get(f"/api/v1/actions/{aid}", headers=other).status_code == 404
    assert client.get(f"/api/v1/agent-runs/{run_id}/events", headers=other).json() == []
    assert client.get("/api/v1/documents", headers=other).json() == []


def test_document_and_evidence_endpoints(client):
    login(client, "viewer")
    docs = client.get("/api/v1/documents", headers=H).json()
    assert docs
    v = client.get(f"/api/v1/documents/versions/{docs[0]['version_id']}", headers=H).json()
    assert v["text"] and v["untrusted_content"]
    ev = client.get("/api/v1/evidence/search", params={"q": "minimum order quantity DEMO-REF-SKU",
                    "knowledge_cutoff": "2026-10-19T09:00:00Z", "effective_date": "2026-10-19"}, headers=H).json()
    labels = {(r["supplier_id"], r["version_label"]) for r in ev["results"]}
    assert ("DEMO-REF-A", "amendment v2") not in labels   # known but not yet effective
    # two suppliers offer this product on different terms with near-equal scores: no single answer (Phase 5, R3)
    assert ev["answer"]["abstained"] and ev["answer"]["support"]["ambiguous"]
    assert ev["answer"]["support"]["candidate_suppliers"] == ["DEMO-REF-A", "DEMO-REF-B"] and not ev["answer"]["claims"]
    scoped = client.get("/api/v1/evidence/search", params={"q": "minimum order quantity DEMO-REF-SKU", "supplier_id": "DEMO-REF-B",
                        "knowledge_cutoff": "2026-10-19T09:00:00Z", "effective_date": "2026-10-19"}, headers=H).json()
    assert scoped["answer"]["claims"][0]["citation"]["version_id"] and scoped["results"][0]["supplier_id"] == "DEMO-REF-B"


def _clear_buckets():
    from supplylens.db import admin_engine
    with admin_engine().begin() as c:
        c.execute(text("TRUNCATE rate_limit_buckets"))


def test_costly_endpoints_are_rate_limited(client):
    _clear_buckets()
    login(client, "planner")
    codes = [client.post("/api/v1/forecasts", json={"sku_ids": ["X"]}, headers={**H, "Idempotency-Key": f"rl{i}"}).status_code
             for i in range(40)]
    # The limit is checked before the handler: the first 30 reach it (422: no sales in demo), then 429.
    assert codes[:30] == [422] * 30 and set(codes[30:]) == {429}
    _clear_buckets()
