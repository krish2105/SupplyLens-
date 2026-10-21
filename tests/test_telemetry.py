"""OpenTelemetry: spans for requests/SQL/business operations, trace context carried to the worker, no secrets in
spans, and a real OTLP/HTTP export decoded from the wire."""
import subprocess
import sys
import textwrap
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from supplylens import telemetry
from supplylens.api.app import app
from supplylens_worker.main import tick

DEMO = {"X-Requested-With": "supplylens", "X-SupplyLens-Tenant": "demo"}
RUN = {"mode": "draft", "sku_ids": ["DEMO-REF-SKU"], "knowledge_cutoff": "2026-10-20T09:00:00Z",
       "effective_date": "2026-10-20", "budget_minor": 18000, "currency": "USD", "allow_shortfall": False}


@pytest.fixture(scope="module")
def spans():
    exporter = InMemorySpanExporter()
    assert telemetry.setup(app, exporter=exporter) is not None
    return exporter


def drain(c, run_id):
    """tick() runs one job per tenant; older queued jobs from earlier tests may go first."""
    for _ in range(20):
        tick()
        if c.get(f"/api/v1/agent-runs/{run_id}", headers=DEMO).json()["status"] not in ("QUEUED", "RUNNING"):
            return
    raise AssertionError("run did not finish")


def login(c, role):
    c.post("/api/v1/auth/dev-login", json={"email": f"{role}@dev.supplylens.local"}, headers={"X-Requested-With": "supplylens"})


def test_request_produces_http_and_sql_spans_and_trace_header(spans):
    spans.clear()
    c = TestClient(app)
    login(c, "viewer")
    spans.clear()
    r = c.get("/api/v1/overview", headers=DEMO)
    finished = spans.get_finished_spans()
    server = [s for s in finished if s.name.startswith("GET /api/v1/overview") and s.parent is None]
    assert len(server) == 1
    tid = format(server[0].context.trace_id, "032x")
    assert r.headers["x-trace-id"] == tid
    sql = [s for s in finished if s.attributes.get("db.system") == "postgresql"]
    assert sql and all(s.context.trace_id == server[0].context.trace_id for s in sql)


def test_worker_spans_join_the_requests_trace(spans):
    c = TestClient(app)
    login(c, "planner")
    spans.clear()
    r = c.post("/api/v1/agent-runs", json=RUN, headers={**DEMO, "Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 202
    request_trace = next(s for s in spans.get_finished_spans() if s.name.startswith("POST /api/v1/agent-runs")).context.trace_id
    drain(c, r.json()["run_id"])
    names = {s.name: s for s in spans.get_finished_spans() if s.context.trace_id == request_trace}
    assert "job.agent_run" in names
    for node in ("accept", "plan", "gather_evidence", "compute", "check", "prepare_action"):
        assert f"agent.{node}" in names, sorted(names)
    assert "retrieval.search" in names
    assert names["agent.compute"].attributes["tenant.id"]
    assert names["job.agent_run"].attributes["job.attempt"] >= 1


def test_spans_do_not_carry_secrets_or_bodies(spans):
    c = TestClient(app)
    login(c, "planner")
    spans.clear()
    secret_key = "tel-secret-" + uuid.uuid4().hex
    r = c.post("/api/v1/agent-runs", json={**RUN, "currency": "USD"}, headers={**DEMO, "Idempotency-Key": secret_key})
    drain(c, r.json()["run_id"])
    blob = " ".join(str(dict(s.attributes)) for s in spans.get_finished_spans())
    assert secret_key not in blob and "sl_session" not in blob and "dev-only-change-me" not in blob
    assert "planner@dev.supplylens.local" not in blob


class _Collector(BaseHTTPRequestHandler):
    bodies: list = []

    def do_POST(self):
        _Collector.bodies.append((self.path, self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


def test_otlp_http_export_reaches_a_collector():
    srv = HTTPServer(("127.0.0.1", 0), _Collector)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _Collector.bodies.clear()
    code = textwrap.dedent("""
        from fastapi.testclient import TestClient
        from supplylens import telemetry
        from supplylens.api.app import app
        c = TestClient(app)
        c.get("/api/v1/auth/dev-users")
        telemetry.shutdown()
    """)
    env = {**__import__("os").environ, "SUPPLYLENS_OTEL_ENDPOINT": f"http://127.0.0.1:{srv.server_port}",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-800:]
    srv.shutdown()
    assert _Collector.bodies and _Collector.bodies[0][0] == "/v1/traces"
    req = ExportTraceServiceRequest()
    req.ParseFromString(_Collector.bodies[0][1])
    res_attrs = {a.key: a.value.string_value for rs in req.resource_spans for a in rs.resource.attributes}
    assert res_attrs["service.name"] == "supplylens"
    names = [sp.name for rs in req.resource_spans for ss in rs.scope_spans for sp in ss.spans]
    assert any(n.startswith("GET /api/v1/auth/dev-users") for n in names), names


def test_tracing_is_off_without_an_endpoint():
    out = subprocess.run([sys.executable, "-c", "from supplylens import telemetry; "
                          "print(telemetry.setup() is None, telemetry.current_trace_id())"],
                         capture_output=True, text=True, timeout=60, env={k: v for k, v in __import__('os').environ.items()
                                                                          if not k.startswith("SUPPLYLENS_OTEL")})
    assert out.stdout.strip() == "True None", out.stderr[-400:]
