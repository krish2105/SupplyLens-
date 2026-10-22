"""Create real operational data in whatever database SUPPLYLENS_*_DATABASE_URL points at (used by rehearsals).

Seeds the control plane, loads the Demo workspace, runs the reference investigation, approves the draft, dispatches
it, and prints the resulting counts as JSON. Run as a subprocess so the target database is chosen by environment."""
import json
import sys
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from supplylens.api.app import app
from supplylens.db import admin_engine, tenant_session
from supplylens.seed import seed, tenant_id
from supplylens.simulation import demo
from supplylens_worker.main import tick

H = {"X-Requested-With": "supplylens", "X-SupplyLens-Tenant": "demo"}
RUN = {"mode": "draft", "sku_ids": ["DEMO-REF-SKU"], "knowledge_cutoff": "2026-10-20T09:00:00Z",
       "effective_date": "2026-10-20", "budget_minor": 18000, "currency": "USD", "allow_shortfall": False}


def login(c, role):
    c.post("/api/v1/auth/dev-login", json={"email": f"{role}@dev.supplylens.local"}, headers={"X-Requested-With": "supplylens"})


def counts():
    t = tenant_id("demo")
    with tenant_session(t) as s:
        out = {n: s.execute(text(f"SELECT count(*) FROM {n}")).scalar()
               for n in ("actions", "approvals", "outbox", "audit_events", "agent_runs", "agent_events",
                         "purchase_order_lines")}
    out["open_order_lines"] = out.pop("purchase_order_lines")
    with admin_engine().connect() as conn:
        out["sandbox_orders"] = conn.execute(text("SELECT count(*) FROM sandbox_erp.purchase_orders")).scalar()
    return out


def main() -> dict:
    seed()
    demo.load(tenant_id("demo"))
    c = TestClient(app)
    login(c, "planner")
    run_id = c.post("/api/v1/agent-runs", json=RUN, headers={**H, "Idempotency-Key": uuid.uuid4().hex}).json()["run_id"]
    for _ in range(10):
        tick()
        d = c.get(f"/api/v1/agent-runs/{run_id}", headers=H).json()
        if d["status"] not in ("QUEUED", "RUNNING"):
            break
    action = c.get(f"/api/v1/actions/{d['actions'][0]['id']}", headers=H).json()
    login(c, "approver")
    r = c.post(f"/api/v1/actions/{action['id']}/approve", headers={**H, "Idempotency-Key": uuid.uuid4().hex},
               json={"payload_hash": action["payload_hash"], "expected_row_version": action["row_version"]})
    assert r.status_code == 200, r.text
    tick()
    final = c.get(f"/api/v1/actions/{action['id']}", headers=H).json()
    return {"action_id": action["id"], "status": final["status"], "counts": counts()}


if __name__ == "__main__":
    json.dump(counts() if sys.argv[1:] == ["--counts"] else main(), sys.stdout)
