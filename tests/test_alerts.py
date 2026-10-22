"""BUS-018: alerts for stale data, failed reconciliation, exhausted budgets and unavailable models reach the
operational queue (the alerts table / API) and the signed webhook route."""
import hashlib
import hmac
import json
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from supplylens import alerts
from supplylens.api.app import app
from supplylens.config import settings
from supplylens.db import admin_engine, tenant_session
from supplylens.seed import tenant_id
from supplylens.simulation import demo
from supplylens_worker.main import tick

DEMO = {"X-Requested-With": "supplylens", "X-SupplyLens-Tenant": "demo"}
RUN = {"mode": "draft", "sku_ids": ["DEMO-REF-SKU"], "knowledge_cutoff": "2026-10-20T09:00:00Z",
       "effective_date": "2026-10-20", "budget_minor": 18000, "currency": "USD", "allow_shortfall": False}


def login(c, role):
    c.post("/api/v1/auth/dev-login", json={"email": f"{role}@dev.supplylens.local"}, headers={"X-Requested-With": "supplylens"})


@pytest.fixture()
def world(clean_db):
    from supplylens.seed import seed
    seed()
    demo.load(tenant_id("demo"))
    with admin_engine().begin() as c:
        c.execute(text("TRUNCATE alerts, rate_limit_buckets, idempotency_keys"))
    return TestClient(app)


def open_alerts(kind=None):
    with tenant_session(tenant_id("demo")) as s:
        rows = s.execute(text("SELECT kind, dedupe_key, status, occurrences, severity, detail, delivery_status FROM alerts "
                              "WHERE status <> 'RESOLVED' ORDER BY dedupe_key")).mappings().all()
    return [dict(r) for r in rows if kind is None or r["kind"] == kind]


def prepare_and_approve(c, *, fault=None):
    login(c, "planner")
    run_id = c.post("/api/v1/agent-runs", json=RUN, headers={**DEMO, "Idempotency-Key": f"al-run-{fault}"}).json()["run_id"]
    tick()
    detail = c.get(f"/api/v1/agent-runs/{run_id}", headers=DEMO).json()
    action = c.get(f"/api/v1/actions/{detail['actions'][0]['id']}", headers=DEMO).json()
    if fault:
        login(c, "tenant_admin")
        assert c.post("/api/v1/sandbox/faults", json={"action_id": action["id"], "mode": fault},
                      headers={**DEMO, "Idempotency-Key": f"al-fault-{fault}"}).status_code == 200
    login(c, "approver")
    r = c.post(f"/api/v1/actions/{action['id']}/approve", headers={**DEMO, "Idempotency-Key": f"al-ap-{fault}"},
               json={"payload_hash": action["payload_hash"], "expected_row_version": action["row_version"]})
    assert r.status_code == 200
    tick()
    return action["id"]


# -------------------------------------------------------------------------- failed reconciliation
def test_unknown_outcome_raises_a_high_alert_and_reconcile_resolves_it(world):
    c = world
    aid = prepare_and_approve(c, fault="timeout_after_commit")
    live = open_alerts("failed_reconciliation")
    assert len(live) == 1 and live[0]["dedupe_key"] == f"failed_reconciliation:{aid}" and live[0]["severity"] == "high"
    assert live[0]["detail"]["status"] == "UNKNOWN_OUTCOME"
    # visible in the operational queue API for every role that can read
    login(c, "viewer")
    q = c.get("/api/v1/alerts", headers=DEMO).json()
    assert q["open"] == 1 and q["alerts"][0]["kind"] == "failed_reconciliation"
    login(c, "approver")
    assert c.post(f"/api/v1/actions/{aid}/reconcile", headers={**DEMO, "Idempotency-Key": "al-rec"}, json={}).status_code == 200
    assert open_alerts("failed_reconciliation") == []     # resolved when the order reconciled


def test_dispatch_failure_after_retries_raises_alert(world):
    c = world
    login(c, "planner")
    run_id = c.post("/api/v1/agent-runs", json=RUN, headers={**DEMO, "Idempotency-Key": "al-fail-run"}).json()["run_id"]
    tick()
    action = c.get(f"/api/v1/actions/{c.get(f'/api/v1/agent-runs/{run_id}', headers=DEMO).json()['actions'][0]['id']}", headers=DEMO).json()
    login(c, "approver")
    c.post(f"/api/v1/actions/{action['id']}/approve", headers={**DEMO, "Idempotency-Key": "al-fail-ap"},
           json={"payload_hash": action["payload_hash"], "expected_row_version": action["row_version"]})
    from supplylens.actions import service as svc
    from supplylens.integrations import sandbox_erp
    for _ in range(5):                       # connector outage: every attempt is rejected before commit
        sandbox_erp.inject_fault(f"po-{action['id']}", "fail_before_commit")
        with tenant_session(tenant_id("demo")) as s:
            s.execute(text("UPDATE outbox SET next_attempt_at = now() WHERE status='PENDING'"))
        svc.dispatch_once(tenant_id("demo"), "t")
    a = c.get(f"/api/v1/actions/{action['id']}", headers=DEMO).json()
    assert a["status"] == "FAILED"
    live = open_alerts("failed_reconciliation")
    assert len(live) == 1 and live[0]["detail"]["status"] == "FAILED"
    with admin_engine().connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM sandbox_erp.purchase_orders")).scalar() == 0   # no phantom order


# -------------------------------------------------------------------------- stale data
def test_stale_data_alert_follows_the_workspace_rule_and_clears_when_fresh(world):
    t = tenant_id("demo")
    assert alerts.evaluate(t, check_models=False)["raised"] == []          # no freshness rule configured: silent
    with tenant_session(t) as s:
        s.execute(text("UPDATE tenant_settings SET planning = planning || '{\"alerts\": {\"stale_data_days\": 2}}'::jsonb"))
    now = datetime(2027, 2, 20, tzinfo=UTC)     # 5 days after the Demo as-of (2027-02-15 18:00)
    out = alerts.evaluate(t, now=now, check_models=False)
    assert out["raised"] == ["stale_data:operational"]
    assert open_alerts("stale_data")[0]["detail"]["age_days"] > 4
    alerts.evaluate(t, now=now, check_models=False)                         # still stale: same alert, bumped
    assert open_alerts("stale_data")[0]["occurrences"] == 2
    fresh = alerts.evaluate(t, now=datetime(2027, 2, 16, tzinfo=UTC), check_models=False)
    assert fresh["resolved"] == 1 and open_alerts("stale_data") == []


# -------------------------------------------------------------------------- budgets
def test_exhausted_run_budget_raises_alert(world):
    c = world
    login(c, "planner")
    run = {**RUN, "budget": {"max_tool_calls": 1, "max_seconds": 120, "max_check_loops": 1}}
    run_id = c.post("/api/v1/agent-runs", json=run, headers={**DEMO, "Idempotency-Key": "al-budget"}).json()["run_id"]
    # the API model has no budget field; set it the way an operator-tuned run would carry it
    with tenant_session(tenant_id("demo")) as s:
        s.execute(text("UPDATE agent_runs SET input = jsonb_set(input, '{budget}', CAST(:b AS jsonb)) WHERE id = :i"),
                  {"i": run_id, "b": json.dumps({"max_tool_calls": 1, "max_seconds": 120, "max_check_loops": 1})})
    tick()
    assert c.get(f"/api/v1/agent-runs/{run_id}", headers=DEMO).json()["status"] == "PARTIAL"
    live = open_alerts("budget_exhausted")
    assert len(live) == 1 and live[0]["dedupe_key"] == f"budget_exhausted:run:{run_id}"


def test_daily_run_allowance_alert(world):
    t = tenant_id("demo")
    with tenant_session(t) as s:
        s.execute(text("UPDATE tenant_settings SET planning = planning || '{\"alerts\": {\"max_runs_per_day\": 0}}'::jsonb"))
    c = world
    login(c, "planner")
    c.post("/api/v1/agent-runs", json=RUN, headers={**DEMO, "Idempotency-Key": "al-daily"})
    out = alerts.evaluate(t, check_models=False)
    assert "budget_exhausted:daily_runs" in out["raised"]


# -------------------------------------------------------------------------- models
def test_tampered_model_artifact_and_embedding_outage_raise_model_alerts(world, tmp_path, monkeypatch):
    t = tenant_id("demo")
    art = tmp_path / "m.txt"
    art.write_text("weights")
    from supplylens import config
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    monkeypatch.setattr("supplylens.alerts.REPO_ROOT", tmp_path, raising=False)
    with tenant_session(t) as s:
        s.execute(text("""INSERT INTO model_versions (id, tenant_id, family, version, status, config, code_version,
            artifact_path, artifact_sha256) VALUES (gen_random_uuid(), :t, 'lightgbm_quantile', 'test', 'CHAMPION',
            '{}'::jsonb, 'x', '.', CAST(:a AS jsonb))"""),
                  {"t": t, "a": json.dumps([{"file": "m.txt", "sha256": hashlib.sha256(b"weights").hexdigest()}])})
    assert [k for k in alerts.evaluate(t)["raised"] if k.startswith("model_unavailable:artifact")] == []
    art.write_text("tampered")
    out = alerts.evaluate(t)
    assert any(k.startswith("model_unavailable:artifact") for k in out["raised"])
    art.write_text("weights")
    assert alerts.evaluate(t)["resolved"] >= 1
    # embeddings: chunks with vectors exist but the service does not answer
    with tenant_session(t) as s:
        s.execute(text("UPDATE chunks SET embedding = (SELECT array_agg(0.001)::vector(1024) FROM generate_series(1,1024)) "
                       "WHERE id IN (SELECT id FROM chunks LIMIT 1)"))
    monkeypatch.setattr("supplylens.knowledge.embed.embed", lambda *a, **k: None)
    assert "model_unavailable:embeddings" in alerts.evaluate(t)["raised"]


# -------------------------------------------------------------------------- queue behaviour + webhook
def test_acknowledge_dedupe_and_permissions(world):
    t = tenant_id("demo")
    first = alerts.raise_alert(t, "stale_data", "stale_data:x", "stale", {"n": 1})
    again = alerts.raise_alert(t, "stale_data", "stale_data:x", "stale", {"n": 2})
    assert first["opened"] is True and again["opened"] is False and again["occurrences"] == 2
    c = world
    login(c, "viewer")
    assert c.post(f"/api/v1/alerts/{first['id']}/acknowledge", json={}, headers={**DEMO, "Idempotency-Key": "ack-v"}).status_code == 403
    login(c, "planner")
    assert c.post(f"/api/v1/alerts/{first['id']}/acknowledge", json={"note": "looking"}, headers={**DEMO, "Idempotency-Key": "ack-p"}).status_code == 200
    assert open_alerts()[0]["status"] == "ACKNOWLEDGED"
    login(c, "tenant_admin")
    assert c.post("/api/v1/alerts/evaluate", headers=DEMO).status_code == 200


class _Sink(BaseHTTPRequestHandler):
    received: list = []
    fail_first = 0

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if _Sink.fail_first > 0:
            _Sink.fail_first -= 1
            self.send_response(503)
            self.end_headers()
            return
        _Sink.received.append((dict(self.headers), body))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *a):
        pass


def test_webhook_delivery_is_signed_retried_and_recorded(world, monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _Sink)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _Sink.received.clear()
    _Sink.fail_first = 1
    monkeypatch.setattr(settings, "alert_webhook_url", f"http://127.0.0.1:{srv.server_port}/hook")
    t = tenant_id("demo")
    a = alerts.raise_alert(t, "failed_reconciliation", "failed_reconciliation:wh", "Order outcome unknown", {"x": 1}, "high")
    assert open_alerts()[0]["delivery_status"] == "PENDING"
    assert alerts.deliver_pending(t) == {"delivered": 0, "failed": 0, "retry": 1}      # 503 first: scheduled for retry
    with tenant_session(t) as s:
        s.execute(text("UPDATE alerts SET next_delivery_at = now()"))
    assert alerts.deliver_pending(t)["delivered"] == 1
    headers, body = _Sink.received[0]
    ts = headers["X-SupplyLens-Timestamp"]
    expected = "sha256=" + hmac.new(settings.alert_webhook_secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert headers["X-SupplyLens-Signature"] == expected and headers["Idempotency-Key"] == f"alert-{a['id']}"
    assert abs(int(ts) - time.time()) < 60                                              # the signed timestamp is current
    assert headers["X-SupplyLens-Signature"] != "sha256=" + hmac.new(settings.alert_webhook_secret.encode(), body,
                                                                       hashlib.sha256).hexdigest()   # body alone no longer verifies
    assert json.loads(body)["kind"] == "failed_reconciliation"
    assert alerts.deliver_pending(t)["delivered"] == 0                                  # delivered once only
    srv.shutdown()
