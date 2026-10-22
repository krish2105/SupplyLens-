"""FastAPI application factory. Run: uv run uvicorn supplylens.api.app:app --port 8000"""
from __future__ import annotations

import hmac
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager

import anyio.to_thread
import psycopg
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from .. import metrics, telemetry
from ..actions.service import ActionError
from ..authz import Forbidden
from ..config import settings
from ..db import app_engine
from ..forecasting.service import ForecastError
from ..lifecycle import LifecycleError
from . import (
    admission,
    oidc,
    routes_core,
    routes_decisions,
    routes_lifecycle,
    routes_market,
    routes_onboarding,
    routes_ops,
    routes_research,
    routes_setup,
)
from .guards import BodyLimit, SignInThrottle
from .schemas import Health

log = logging.getLogger("supplylens.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Synchronous routes run on worker threads (default 40). Size the pool to the admission cap so admission control, not
    # a hidden queue in front of the threads, decides what waits (Phase 3).
    anyio.to_thread.current_default_thread_limiter().total_tokens = max(settings.max_inflight, 8)
    yield


app = FastAPI(title="SupplyLens API", version="0.1.0", lifespan=lifespan,
              description="Evidence-grounded inventory and procurement decisions. /api/v1 is the versioned contract.")
app.include_router(routes_core.router)
app.include_router(oidc.router)
app.include_router(routes_decisions.router)
app.include_router(routes_research.router)
app.include_router(routes_market.router)
app.include_router(routes_ops.router)
app.include_router(routes_lifecycle.router)
app.include_router(routes_onboarding.router)
if os.environ.get("SUPPLYLENS_SETUP_TOKEN"):        # hosted one-time setup only (hosting/setup.py)
    app.include_router(routes_setup.router)
telemetry.setup(app)


@app.middleware("http")
async def backpressure(request: Request, call_next):
    """Shed load instead of queueing it without bound (DEF-10; admission.py). The 2026-10-21 load test showed requests past
    capacity waiting in the thread pool for minutes and the service taking minutes to recover; a bounded wait and an early
    refusal keep accepted requests fast and recovery immediate. Event streams and health checks are never counted."""
    cls = admission.classify(request.method, request.url.path)
    if cls is None:
        return await call_next(request)
    tenant = admission.tenant_of(request.scope)
    taken: list[admission.Gate] = []
    for name in ("all", cls) if cls != "all" else ("all",):
        gate = admission.gates()[name]
        reason = await gate.acquire(tenant)
        if reason:
            for g in taken:
                g.release(tenant)
            status, body, headers = admission.refusal(reason, name)
            return JSONResponse(body, status_code=status, headers=headers)
        taken.append(gate)
    request.state.admission_class = cls
    try:
        return await call_next(request)
    finally:
        for g in taken:
            g.release(tenant)


@app.middleware("http")
async def trace(request: Request, call_next):
    supplied = request.headers.get("x-trace-id", "")
    # A caller-supplied id is echoed in the response and written to logs: accept only a plain hex/dash token.
    trace_id = telemetry.current_trace_id() or (supplied if re.fullmatch(r"[0-9A-Fa-f-]{8,64}", supplied) else uuid.uuid4().hex)
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    route = request.scope.get("route")
    metrics.observe(request.method, getattr(route, "path", "unmatched"), response.status_code, elapsed,
                    getattr(request.state, "workspace", None), getattr(request.state, "admission_class", None))
    response.headers["x-trace-id"] = trace_id
    # API responses carry tenant data: never cache them, never let a browser sniff their type.
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    log.info("%s %s %s %.1fms trace=%s", request.method, request.url.path, response.status_code, elapsed * 1000, trace_id)
    return response


@app.exception_handler(Exception)
async def unexpected(request: Request, e: Exception):
    # Always JSON with a reference the user can quote (audit S22); the detail stays in the server log.
    ref = telemetry.current_trace_id() or uuid.uuid4().hex
    log.exception("unhandled error on %s %s ref=%s", request.method, request.url.path, ref)
    return JSONResponse({"code": "server_error", "message": "The server hit an unexpected error. Your input was not lost.",
                         "reference": ref}, status_code=500, headers={"x-trace-id": ref})


@app.exception_handler(PoolTimeout)
async def pool_exhausted(request: Request, e: PoolTimeout):
    # Every pooled connection stayed busy for db_pool_timeout_s: the database is the bottleneck. Say so and when to retry,
    # rather than a 500 (Phase 3).
    metrics.count("db_pool_timeouts_total")
    log.warning("connection pool exhausted on %s %s", request.method, request.url.path)
    return JSONResponse({"code": "overloaded", "message": "The service is at capacity; retry in a few seconds.",
                         "retry_after_s": 3}, status_code=503, headers={"Retry-After": "3"})


@app.exception_handler(OperationalError)
async def database_operational(request: Request, e: OperationalError):
    if isinstance(e.orig, psycopg.errors.QueryCanceled):
        # statement_timeout fired (db.py, retrieval): the work was cancelled to protect the requests still in time.
        metrics.count("db_statement_timeouts_total")
        log.warning("statement timeout on %s %s", request.method, request.url.path)
        return JSONResponse({"code": "query_timeout", "message": "The request took too long and was stopped; retry in a "
                             "few seconds.", "retry_after_s": 3}, status_code=503, headers={"Retry-After": "3"})
    return await unexpected(request, e)


@app.exception_handler(Forbidden)
async def forbidden(_: Request, e: Forbidden):
    return JSONResponse({"code": "forbidden", "message": str(e)}, status_code=403)


@app.exception_handler(ActionError)
async def action_error(_: Request, e: ActionError):
    return JSONResponse({"code": e.code, "message": str(e)}, status_code=e.http)


@app.exception_handler(LifecycleError)
async def lifecycle_error(_: Request, e: LifecycleError):
    return JSONResponse({"code": e.code, "message": str(e)}, status_code=e.http)


@app.exception_handler(ForecastError)
async def forecast_error(_: Request, e: ForecastError):
    return JSONResponse({"code": e.code, "message": str(e)}, status_code=422)


@app.exception_handler(HTTPException)
async def http_error(_: Request, e: HTTPException):
    body = e.detail if isinstance(e.detail, dict) else {"code": "error", "message": str(e.detail)}
    return JSONResponse(body, status_code=e.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, e: RequestValidationError):
    return JSONResponse({"code": "invalid_request", "message": "request failed validation",
                         "errors": [{"loc": list(x["loc"]), "msg": x["msg"]} for x in e.errors()]}, status_code=422)


@app.get("/metrics", include_in_schema=False)
def metrics_endpoint(authorization: str | None = Header(None)):
    """Prometheus text format (metrics.py). Exists only when SUPPLYLENS_METRICS_TOKEN is set; the token is compared in
    constant time. Workspace ids appear in labels, so this is operator-only."""
    token = settings.metrics_token
    if not token:
        raise HTTPException(404, {"code": "not_found", "message": "Not Found"})
    if not hmac.compare_digest((authorization or "").encode(), f"Bearer {token}".encode()):
        raise HTTPException(401, {"code": "unauthenticated", "message": "metrics token required"})
    return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")


@app.get("/health", response_model=Health)
def health():
    with app_engine().connect() as c:
        c.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


# Added last, so they run first: refuse oversized bodies and sign-in bursts before back-pressure accounting, routing,
# authentication or body parsing (guards.py).
app.add_middleware(SignInThrottle)
app.add_middleware(BodyLimit)
