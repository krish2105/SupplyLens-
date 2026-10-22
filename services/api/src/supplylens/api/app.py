"""FastAPI application factory. Run: uv run uvicorn supplylens.api.app:app --port 8000"""
from __future__ import annotations

import logging
import os
import re
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .. import telemetry
from ..actions.service import ActionError
from ..authz import Forbidden
from ..config import settings
from ..db import app_engine
from ..forecasting.service import ForecastError
from ..lifecycle import LifecycleError
from . import (
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

app = FastAPI(title="SupplyLens API", version="0.1.0",
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


COSTLY = ("/api/v1/evidence/search", "/api/v1/scenarios", "/api/v1/forecasts", "/api/v1/agent-runs")
EXEMPT = ("/health", "/api/v1/auth", "/api/v1/me")
_inflight = {"all": 0, "costly": 0}


@app.middleware("http")
async def backpressure(request: Request, call_next):
    """Shed load instead of queueing it (DEF-10). The load test showed requests past capacity waiting in the thread pool
    for minutes and the service taking minutes to recover; refusing early keeps accepted requests fast and recovery
    immediate. Event streams and health checks are never counted or refused."""
    path = request.url.path
    if path.startswith(EXEMPT) or path.endswith("/stream"):
        return await call_next(request)
    costly = path.startswith(COSTLY) and (request.method == "POST" or path.startswith("/api/v1/evidence/search"))
    if _inflight["all"] >= settings.max_inflight or (costly and _inflight["costly"] >= settings.max_inflight_costly):
        return JSONResponse({"code": "overloaded", "message": "The service is at capacity; retry in a few seconds."},
                            status_code=503, headers={"Retry-After": "2"})
    _inflight["all"] += 1
    _inflight["costly"] += costly
    try:
        return await call_next(request)
    finally:
        _inflight["all"] -= 1
        _inflight["costly"] -= costly


@app.middleware("http")
async def trace(request: Request, call_next):
    supplied = request.headers.get("x-trace-id", "")
    # A caller-supplied id is echoed in the response and written to logs: accept only a plain hex/dash token.
    trace_id = telemetry.current_trace_id() or (supplied if re.fullmatch(r"[0-9A-Fa-f-]{8,64}", supplied) else uuid.uuid4().hex)
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["x-trace-id"] = trace_id
    # API responses carry tenant data: never cache them, never let a browser sniff their type.
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    log.info("%s %s %s %.1fms trace=%s", request.method, request.url.path, response.status_code,
             (time.perf_counter() - start) * 1000, trace_id)
    return response


@app.exception_handler(Exception)
async def unexpected(request: Request, e: Exception):
    # Always JSON with a reference the user can quote (audit S22); the detail stays in the server log.
    ref = telemetry.current_trace_id() or uuid.uuid4().hex
    log.exception("unhandled error on %s %s ref=%s", request.method, request.url.path, ref)
    return JSONResponse({"code": "server_error", "message": "The server hit an unexpected error. Your input was not lost.",
                         "reference": ref}, status_code=500, headers={"x-trace-id": ref})


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


@app.get("/health", response_model=Health)
def health():
    with app_engine().connect() as c:
        c.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


# Added last, so they run first: refuse oversized bodies and sign-in bursts before back-pressure accounting, routing,
# authentication or body parsing (guards.py).
app.add_middleware(SignInThrottle)
app.add_middleware(BodyLimit)
