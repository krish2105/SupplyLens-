"""Live smoke test: investigation -> approval -> sandbox order reconciled, against a running API and worker.

Run with the API on :8000 and the worker running: uv run python scripts/smoke_investigation.py
"""
import time
import uuid

import httpx

B = "http://localhost:8000/api/v1"
def client(role, ws):
    c = httpx.Client(base_url=B, timeout=60, headers={"X-Requested-With": "supplylens", "X-SupplyLens-Tenant": ws})
    assert c.post("/auth/dev-login", json={"email": f"{role}@dev.supplylens.local"}).status_code == 200
    return c
p = client("planner", "uci-research")
r = p.post("/agent-runs", json={"mode": "draft"}, headers={"Idempotency-Key": str(uuid.uuid4())}); print("start", r.status_code, r.json().get("status"))
rid = r.json()["run_id"]; t0 = time.time()
while time.time() - t0 < 90:
    d = p.get(f"/agent-runs/{rid}").json()
    if d["status"] not in ("QUEUED", "RUNNING"):
        break
    time.sleep(1)
print(f"status {d['status']} after {time.time()-t0:.0f}s, tool_calls {d.get('tool_calls')}")
for e in p.get(f"/agent-runs/{rid}/events").json():
    print("  ", e["node"], "|", e["summary"][:140])
print("plan", d["plan"]["status"], "| drafts:", [(a["supplier_id"], a["total_minor"], a["status"]) for a in d["actions"]])
needs = d.get("needs") or {}
print("basis used:", {v.get("basis") for v in needs.values()})
act = d["actions"][0]["id"]
a = client("approver", "uci-research")
full = a.get(f"/actions/{act}").json()
ap = a.post(f"/actions/{act}/approve", json={"payload_hash": full["payload_hash"], "expected_row_version": full["row_version"]}, headers={"Idempotency-Key": str(uuid.uuid4())})
print("approve", ap.status_code, ap.json())
t0 = time.time()
while time.time() - t0 < 30:
    s = a.get(f"/actions/{act}").json()
    if s["status"] in ("RECONCILED", "UNKNOWN_OUTCOME", "FAILED", "STALE"):
        break
    time.sleep(1)
print("final:", s["status"], s.get("external_ref"), "|", s.get("status_reason"))
