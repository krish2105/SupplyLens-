"""Auth, workspace overview, datasets, inventory, warehouse and sales endpoints."""
from __future__ import annotations

import logging
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from itsdangerous import BadSignature
from pydantic import BaseModel
from sqlalchemy import text

from .. import demo
from ..authz import Actor
from ..config import settings
from ..db import control_session, tenant_session
from ..integrations import sandbox_erp
from .deps import (
    COOKIE,
    SESSION_MAX_AGE,
    actor,
    csrf_guard,
    current_user_id,
    serializer,
    start_dev_session,
)
from .schemas import (
    AuditRow,
    AuthConfig,
    Dataset,
    DevUsers,
    Integration,
    Inventory,
    Me,
    Ok,
    Overview,
    ProductSales,
    Quarantine,
    Warehouse,
)

router = APIRouter(prefix="/api/v1", dependencies=[Depends(csrf_guard)])
log = logging.getLogger("supplylens.api")


class DevLogin(BaseModel):
    email: str


@router.get("/auth/dev-users", response_model=DevUsers)
def dev_users():
    if not settings.dev_login_available:
        raise HTTPException(404, {"code": "disabled", "message": "dev sign-in disabled"})
    with control_session() as s:
        rows = s.execute(text("""SELECT u.email, u.display_name, array_agg(DISTINCT m.role) AS roles
            FROM users u JOIN memberships m ON m.user_id = u.id WHERE u.is_dev_account AND u.active
            GROUP BY u.email, u.display_name ORDER BY u.email""")).mappings().all()
    return {"dev_only": True, "users": [dict(r) for r in rows],
            "notice": "Development accounts. Enterprise sign-in (OIDC) is NOT_CONFIGURED in this build."}


@router.post("/auth/dev-login", response_model=Ok)
def dev_login(body: DevLogin, response: Response):
    if not settings.dev_login_available:
        raise HTTPException(404, {"code": "disabled", "message": "dev sign-in disabled"})
    with control_session() as s:
        uid = s.execute(text("SELECT id FROM users WHERE email=:e AND is_dev_account AND active"),
                        {"e": body.email}).scalar()
    if uid is None:
        raise HTTPException(401, {"code": "unknown_user", "message": "unknown development account"})
    if settings.environment == "demo":
        demo.release_stale_orders()          # P0-SEC-01: the next visitor starts from the reference state
    response.set_cookie(COOKIE, start_dev_session(uid), max_age=SESSION_MAX_AGE, httponly=True,
                        samesite="lax", secure=settings.cookie_secure, path="/")
    return {"ok": True}


@router.post("/auth/logout", response_model=Ok)
def logout(request: Request, response: Response):
    try:
        data = serializer.loads(request.cookies.get(COOKIE, ""), max_age=SESSION_MAX_AGE)
    except BadSignature:
        data = {}
    if data.get("sid"):
        from .oidc import revoke
        revoke(uuid.UUID(data["sid"]), "signed out")
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/config", response_model=AuthConfig)
def auth_config():
    """What the sign-in page may offer. Never reveals secrets."""
    return {"environment": settings.environment, "dev_login": settings.dev_login_available,
            "oidc": settings.oidc_enabled, "oidc_login_url": "/api/v1/auth/oidc/login" if settings.oidc_enabled else None,
            "disposable": settings.e2e_disposable and settings.environment in ("development", "test")}


@router.get("/me", response_model=Me)
def me(request: Request):
    uid = current_user_id(request)
    with control_session() as s:
        u = s.execute(text("SELECT id, email, display_name, is_dev_account FROM users WHERE id=:u AND active"),
                      {"u": uid}).mappings().first()
        if not u:
            raise HTTPException(401, {"code": "unauthenticated", "message": "account inactive"})
        ms = s.execute(text("""SELECT t.slug, t.name, t.kind, t.description, m.role FROM memberships m
            JOIN tenants t ON t.id = m.tenant_id WHERE m.user_id = :u AND t.deleted_at IS NULL ORDER BY t.slug"""), {"u": uid}).mappings().all()
    return {"user": dict(u), "memberships": [dict(m) for m in ms]}


@router.get("/overview", response_model=Overview)
def overview(a: Actor = Depends(actor)):
    a.require("read")
    with tenant_session(a.tenant_id) as s:
        st = s.execute(text("SELECT operational_as_of, currency, dataset_id, planning, assumption_set_id "
                            "FROM tenant_settings")).mappings().first()
        ds = s.execute(text("SELECT id, name, license, source_url, sha256, report, created_at FROM datasets "
                            "ORDER BY created_at DESC LIMIT 1")).mappings().first()
        counts = s.execute(text("""SELECT
            (SELECT count(*) FROM products) AS products,
            (SELECT count(DISTINCT sku_id) FROM inventory_positions) AS stocked_skus,
            (SELECT count(*) FROM suppliers) AS suppliers,
            (SELECT count(*) FROM document_versions) AS document_versions,
            (SELECT count(*) FROM supplier_terms) AS supplier_terms,
            (SELECT count(*) FROM agent_runs) AS agent_runs""")).mappings().first()
        actions = {r.status: r.n for r in s.execute(text("SELECT status, count(*) n FROM actions GROUP BY status"))}
        assumption = s.execute(text("SELECT name, version, rationale FROM assumption_sets LIMIT 1")).mappings().first()
    caps = capability_matrix(bool(ds), bool(assumption), counts)
    return {
        "settings": dict(st) if st else None,
        "dataset": ({k: ds[k] for k in ("id", "name", "license", "source_url", "sha256", "created_at")}
                    | {"totals": ds["report"].get("totals"), "date_span": ds["report"].get("date_span")}) if ds else None,
        "counts": dict(counts), "actions_by_status": actions,
        "assumption_set": dict(assumption) if assumption else None,
        "capabilities": caps,
    }


def capability_matrix(has_sales: bool, has_sim: bool, counts) -> list[dict]:
    """BUS-003: which operational questions the admitted data can answer, and on what basis."""
    return [
        {"capability": "Unit-sales forecasting", "status": "available" if has_sales else "unavailable",
         "basis": "observed" if has_sales else None,
         "note": "Real transactions" if has_sales else "No sales history in this workspace"},
        {"capability": "Stock positions", "status": "available" if counts["stocked_skus"] else "unavailable",
         "basis": "simulated" if has_sim else ("synthetic" if counts["stocked_skus"] else None),
         "note": "Not present in source data" if has_sim else "Fictional fixture"},
        {"capability": "Supplier terms & policies", "status": "available" if counts["supplier_terms"] else "unavailable",
         "basis": "simulated" if has_sim else "synthetic",
         "note": "Generated agreements, labelled SIMULATED" if has_sim else "Fictional contracts"},
        {"capability": "Purchase cost", "status": "assumed" if has_sim else "synthetic",
         "basis": "assumed", "note": "Selling price is not purchase cost; cost ratio is an assumption"},
        {"capability": "Actual lead times / receipts", "status": "unavailable", "basis": None,
         "note": "Requires customer ERP/WMS access"},
        {"capability": "Lost sales / unconstrained demand", "status": "unavailable", "basis": None,
         "note": "Stockouts are not observed; forecasts are unit-sales forecasts"},
        {"capability": "ERP purchase orders", "status": "sandbox only", "basis": "simulated",
         "note": "Local sandbox adapter; no real ERP connected"},
    ]


@router.get("/datasets", response_model=list[Dataset])
def datasets(a: Actor = Depends(actor)):
    a.require("read")
    with tenant_session(a.tenant_id) as s:
        rows = s.execute(text("""SELECT id, name, source_kind, license, source_url, file_name, sha256, bytes,
            schema_version, status, report, created_at FROM datasets ORDER BY created_at DESC""")).mappings().all()
    return [dict(r) for r in rows]


@router.get("/datasets/{dataset_id}/quarantine", response_model=Quarantine)
def quarantine(dataset_id: uuid.UUID, reason: str | None = None, after: int = 0, limit: int = 50,
               a: Actor = Depends(actor)):
    a.require("read")
    limit = max(1, min(limit, 200))
    with tenant_session(a.tenant_id) as s:
        summary = s.execute(text("SELECT reason, count(*) n FROM quarantine WHERE dataset_id=:d GROUP BY reason "
                                 "ORDER BY n DESC"), {"d": dataset_id}).mappings().all()
        rows = s.execute(text("""SELECT id, source_sheet, source_row, reason, raw FROM quarantine
            WHERE dataset_id=:d AND id > :after AND (CAST(:r AS text) IS NULL OR reason = :r)
            ORDER BY id LIMIT :l"""), {"d": dataset_id, "after": after, "r": reason, "l": limit}).mappings().all()
    return {"summary": [dict(r) for r in summary], "rows": [dict(r) for r in rows],
            "next_cursor": rows[-1]["id"] if len(rows) == limit else None}


INVENTORY_SQL = """
WITH pos AS (
  SELECT DISTINCT ON (sku_id) * FROM inventory_positions WHERE as_of <= :eff ORDER BY sku_id, as_of DESC
), recent AS (
  SELECT sku_id, sum(units)::float / 28 AS avg_daily FROM sales_daily
  WHERE day > CAST(:eff AS date) - 28 AND day <= :eff GROUP BY sku_id
)
SELECT p.sku_id, pr.description, pr.unit, p.location_id, p.zone_id, p.as_of, p.on_hand, p.allocated, p.on_order,
       p.capacity, p.value_kind, (p.on_hand - p.allocated) AS available, r.avg_daily, ws.slot_id, ws.aisle, ws.rack,
       ws.x, ws.z, ws.is_schematic, COALESCE(tc.term_count, 0) AS term_count
FROM pos p JOIN products pr ON pr.sku_id = p.sku_id
LEFT JOIN recent r ON r.sku_id = p.sku_id
LEFT JOIN (SELECT sku_id, count(*) AS term_count FROM supplier_terms GROUP BY sku_id) tc ON tc.sku_id = p.sku_id
LEFT JOIN warehouse_slots ws ON ws.sku_id = p.sku_id
ORDER BY ws.slot_id NULLS LAST, p.sku_id
"""
# Static compositions of the constant above (no user input): one page with the full count, and the count alone.
INVENTORY_PAGE_SQL = "SELECT q.*, count(*) OVER () AS _total FROM (" + INVENTORY_SQL + ") q LIMIT :lim OFFSET :off"  # noqa: S608
INVENTORY_COUNT_SQL = "SELECT count(*) FROM (" + INVENTORY_SQL + ") q"  # noqa: S608


@router.get("/inventory", response_model=Inventory)
def inventory(effective_date: date | None = None, limit: int | None = Query(None, ge=1), offset: int = Query(0, ge=0),
              a: Actor = Depends(actor)):
    """Bounded: at most settings.list_max_rows items per response (Phase 3); `total` and `next_offset` say whether more
    exist. Without `limit` the response holds the whole list up to that bound, as before."""
    a.require("read")
    lim = min(limit or settings.list_max_rows, settings.list_max_rows)
    with tenant_session(a.tenant_id) as s:
        eff = effective_date or s.execute(text("SELECT operational_as_of::date FROM tenant_settings")).scalar()
        if eff is None:
            return {"effective_date": None, "items": [], "total": 0, "offset": offset, "next_offset": None}
        rows = s.execute(text(INVENTORY_PAGE_SQL), {"eff": eff, "lim": lim, "off": offset}).mappings().all()
        total = rows[0]["_total"] if rows else (0 if offset == 0 else s.execute(
            text(INVENTORY_COUNT_SQL), {"eff": eff}).scalar())
    items = []
    for r in rows:
        d = {k: v for k, v in r.items() if k != "_total"}
        avg = d["avg_daily"]
        d["days_of_cover"] = round(d["available"] / avg, 1) if avg else None
        if avg is None:
            d["health"] = "no_sales_data"
        elif d["days_of_cover"] is not None and d["days_of_cover"] < 7:
            d["health"] = "shortage_risk"
        elif d["days_of_cover"] is not None and d["days_of_cover"] > 90:
            d["health"] = "excess"
        else:
            d["health"] = "healthy"
        d["health_basis"] = "derived: available / mean daily unit sales (last 28 days)" if avg else None
        items.append(d)
    return {"effective_date": eff, "items": items, "total": total, "offset": offset,
            "next_offset": offset + len(items) if offset + len(items) < total else None}


@router.get("/products/{sku_id}/sales", response_model=ProductSales)
def product_sales(sku_id: str, start: date | None = None, end: date | None = None, a: Actor = Depends(actor)):
    a.require("read")
    with tenant_session(a.tenant_id) as s:
        p = s.execute(text("SELECT sku_id, description, unit, first_sale, last_sale, source_kind FROM products "
                           "WHERE sku_id=:k"), {"k": sku_id}).mappings().first()
        if not p:
            raise HTTPException(404, {"code": "not_found", "message": "unknown product"})
        rows = s.execute(text("""SELECT day, sum(units)::int AS units FROM sales_daily WHERE sku_id=:k
            AND (CAST(:s AS date) IS NULL OR day >= :s) AND (CAST(:e AS date) IS NULL OR day <= :e)
            GROUP BY day ORDER BY day"""),            # all locations of the SKU, one point per day
            {"k": sku_id, "s": start, "e": end}).all()
        returns = s.execute(text("""SELECT invoiced_at::date AS day, sum(quantity) AS units FROM return_lines
            WHERE sku_id=:k GROUP BY 1 ORDER BY 1"""), {"k": sku_id}).all()
    return {"product": dict(p), "value_kind": "observed",
            "semantics": "Days absent from the series had no recorded sales (not observed zero demand).",
            "daily": [{"day": r.day, "units": r.units} for r in rows],
            "returns": [{"day": r.day, "units": int(r.units)} for r in returns]}


@router.get("/warehouse", response_model=Warehouse)
def warehouse(a: Actor = Depends(actor)):
    a.require("read")
    with tenant_session(a.tenant_id) as s:
        loc = s.execute(text("SELECT location_id, name, kind, is_schematic FROM locations LIMIT 1")).mappings().first()
        slots = s.execute(text("SELECT slot_id, zone_id, aisle, rack, x, z, sku_id FROM warehouse_slots "
                               "ORDER BY slot_id")).mappings().all()
    return {"location": dict(loc) if loc else None, "schematic": True,
            "note": "Schematic layout generated for visualisation; not measured warehouse geometry.",
            "slots": [dict(r) for r in slots]}


@router.get("/integrations", response_model=list[Integration])
def integrations(a: Actor = Depends(actor)):
    a.require("read")
    try:
        sbx = sandbox_erp.health()
    except Exception:
        log.exception("sandbox ERP health check failed")
        sbx = {"status": "DEGRADED", "error": "the sandbox ERP is not reachable (details in the server log)"}
    from ..knowledge.embed import embed
    emb = embed(["health check"], timeout=5)
    return [
        {"name": "Sandbox ERP", **sbx},
        {"name": "File import (UCI adapter)", "status": "VERIFIED_LOCALLY", "note": "tests/test_uci_ingest.py"},
        {"name": "Local embeddings (Ollama bge-m3)", "status": "VERIFIED_LOCALLY" if emb else "DEGRADED",
         "note": "Lexical-only retrieval while unavailable" if not emb else "1024-d vectors"},
        {"name": "CSV onboarding (sales, stock, terms)", "status": "VERIFIED_LOCALLY",
         "note": "upload, map, validate, quarantine, publish an immutable snapshot (tests/test_onboarding.py)"},
        {"name": "Enterprise sign-in (OIDC)", "status": "CONFIGURED" if settings.oidc_enabled else "NOT_CONFIGURED",
         "note": ("code flow + PKCE; verified locally against Keycloak 26 (tests/test_oidc_keycloak.py); "
                  "not qualified against a corporate identity provider") if settings.oidc_enabled
         else "not configured in this environment; see infra/keycloak/README.md for the local provider"},
        {"name": "Microsoft Business Central", "status": "NOT_IMPLEMENTED", "note": "No credentials or sandbox supplied"},
        {"name": "SAP S/4HANA", "status": "NOT_IMPLEMENTED", "note": "No credentials or sandbox supplied"},
        {"name": "Generative LLM", "status": "DISABLED", "note": "Owner decision: deterministic answers only"},
    ]


@router.get("/audit", response_model=list[AuditRow])
def audit(limit: int = 100, a: Actor = Depends(actor)):
    a.require("read")
    with tenant_session(a.tenant_id) as s:
        rows = s.execute(text("""SELECT ae.id, ae.action, ae.entity, ae.entity_id, ae.detail, ae.at, u.email AS actor
            FROM audit_events ae LEFT JOIN users u ON u.id = ae.actor_id ORDER BY ae.id DESC LIMIT :l"""),
            {"l": max(1, min(limit, 500))}).mappings().all()
    return [dict(r) for r in rows]
