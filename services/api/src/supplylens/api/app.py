"""FastAPI application factory. Run: uv run uvicorn supplylens.api.app:app --port 8000"""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from ..actions.service import ActionError
from ..authz import Forbidden
from ..db import app_engine
from ..forecasting.service import ForecastError
from . import routes_core, routes_decisions, routes_market, routes_research

log = logging.getLogger("supplylens.api")

app = FastAPI(title="SupplyLens API", version="0.1.0",
              description="Evidence-grounded inventory and procurement decisions. /api/v1 is the versioned contract.")
app.include_router(routes_core.router)
app.include_router(routes_decisions.router)
app.include_router(routes_research.router)
app.include_router(routes_market.router)


@app.middleware("http")
async def trace(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id") or uuid.uuid4().hex
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["x-trace-id"] = trace_id
    log.info("%s %s %s %.1fms trace=%s", request.method, request.url.path, response.status_code,
             (time.perf_counter() - start) * 1000, trace_id)
    return response


@app.exception_handler(Forbidden)
async def forbidden(_: Request, e: Forbidden):
    return JSONResponse({"code": "forbidden", "message": str(e)}, status_code=403)


@app.exception_handler(ActionError)
async def action_error(_: Request, e: ActionError):
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


@app.get("/health")
def health():
    with app_engine().connect() as c:
        c.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}
