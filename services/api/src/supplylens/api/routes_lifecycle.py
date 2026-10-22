"""Operational alerts, tenant export and deletion, and field Web Vitals."""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from .. import alerts as alert_service
from .. import lifecycle, telemetry
from ..authz import Actor
from ..db import control_session, tenant_session
from .deps import actor, csrf_guard, current_user_id, idempotent
from .ratelimit import limit
from .schemas import (
    AlertAck,
    AlertEvaluation,
    Alerts,
    DeletionCertificate,
    DeletionQueued,
    ExportQueued,
    ExportRow,
    Vitals,
)

router = APIRouter(prefix="/api/v1", dependencies=[Depends(csrf_guard)])


# ------------------------------------------------------------------------------------------ alerts
@router.get("/alerts", response_model=Alerts)
def list_alerts(status: str | None = None, a: Actor = Depends(actor)):
    """The operational queue: open and acknowledged alerts first, newest activity first."""
    a.require("read")
    if status and status not in ("OPEN", "ACKNOWLEDGED", "RESOLVED"):
        raise HTTPException(422, {"code": "invalid_status", "message": "status must be OPEN, ACKNOWLEDGED or RESOLVED"})
    with tenant_session(a.tenant_id) as s:
        rows = s.execute(text("""SELECT id, kind, severity, dedupe_key, title, detail, status, occurrences, first_seen,
            last_seen, resolved_at, delivery_status, delivery_attempts, delivered_at, delivery_error FROM alerts
            WHERE (CAST(:s AS text) IS NULL OR status = :s)
            ORDER BY (status = 'RESOLVED'), last_seen DESC LIMIT 200"""), {"s": status}).mappings().all()
    return {"alerts": [dict(r) for r in rows], "open": sum(r["status"] != "RESOLVED" for r in rows)}


class AckIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertAck)
def acknowledge(alert_id: uuid.UUID, body: AckIn, a: Actor = Depends(actor), idempotency_key: str | None = Header(None)):
    a.require("alert.ack")

    def do():
        with tenant_session(a.tenant_id) as s:
            n = s.execute(text("UPDATE alerts SET status='ACKNOWLEDGED', acknowledged_by=:u WHERE id=:i AND status='OPEN'"),
                          {"u": a.user_id, "i": alert_id}).rowcount
            if not n:
                exists = s.execute(text("SELECT 1 FROM alerts WHERE id=:i"), {"i": alert_id}).first()
                if not exists:      # another workspace's alert looks exactly like a missing one
                    raise HTTPException(404, {"code": "not_found", "message": "alert not found"})
                raise HTTPException(409, {"code": "invalid_state", "message": "only an OPEN alert can be acknowledged"})
            s.execute(text("""INSERT INTO audit_events (tenant_id, actor_id, action, entity, entity_id, detail)
                VALUES (:t,:u,'alert.acknowledged','alert',:e,CAST(:d AS jsonb))"""),
                      {"t": a.tenant_id, "u": a.user_id, "e": str(alert_id), "d": json.dumps({"note": body.note})})
        return 200, {"id": str(alert_id), "status": "ACKNOWLEDGED"}
    return idempotent(a, idempotency_key, f"alert-ack:{alert_id}", body.model_dump(), do)[1]


@router.post("/alerts/evaluate", response_model=AlertEvaluation)
def evaluate_now(a: Actor = Depends(actor)):
    """Re-check stale data, reconciliation, budgets and models now (the worker also does this on a schedule)."""
    a.require("alert.evaluate")
    out = alert_service.evaluate(a.tenant_id)
    return {**out, "delivery": alert_service.deliver_pending(a.tenant_id)}


# ------------------------------------------------------------------------------------------ export
class ExportIn(BaseModel):
    include_vectors: bool = False


def _enqueue(s, a: Actor, kind: str, payload: dict) -> uuid.UUID:
    job_id = uuid.uuid4()
    s.execute(text("INSERT INTO jobs (id, tenant_id, kind, payload, status, created_by) VALUES "
                   "(:i,:t,:k,CAST(:p AS jsonb),'QUEUED',:u)"),
              {"i": job_id, "t": a.tenant_id, "k": kind,
               "p": json.dumps({**payload, "trace": telemetry.inject_context()}), "u": a.user_id})
    return job_id


@router.post("/admin/exports", response_model=ExportQueued, status_code=202)
def request_export(body: ExportIn, a: Actor = Depends(limit("export", 6)), idempotency_key: str | None = Header(None)):
    a.require("tenant.export")

    def do():
        export_id = uuid.uuid4()
        with tenant_session(a.tenant_id) as s:
            s.execute(text("INSERT INTO tenant_exports (id, tenant_id, status, include_vectors, requested_by) "
                           "VALUES (:i,:t,'QUEUED',:v,:u)"),
                      {"i": export_id, "t": a.tenant_id, "v": body.include_vectors, "u": a.user_id})
            job_id = _enqueue(s, a, "tenant_export", {"export_id": str(export_id)})
            s.execute(text("""INSERT INTO audit_events (tenant_id, actor_id, action, entity, entity_id, detail)
                VALUES (:t,:u,'tenant.export_requested','export',:e,CAST(:d AS jsonb))"""),
                      {"t": a.tenant_id, "u": a.user_id, "e": str(export_id),
                       "d": json.dumps({"include_vectors": body.include_vectors})})
        return 202, {"export_id": str(export_id), "job_id": str(job_id), "status": "QUEUED"}
    code, resp = idempotent(a, idempotency_key, "tenant-export", body.model_dump(), do)
    from fastapi.responses import JSONResponse
    return JSONResponse(resp, status_code=code)


@router.get("/admin/exports", response_model=list[ExportRow])
def list_exports(a: Actor = Depends(actor)):
    a.require("admin.read")
    with tenant_session(a.tenant_id) as s:
        rows = s.execute(text("""SELECT id, status, include_vectors, bytes, sha256, error, created_at, finished_at,
            downloaded_at, manifest FROM tenant_exports ORDER BY created_at DESC LIMIT 50""")).mappings().all()
    return [{**dict(r), "manifest": None if r["manifest"] is None else
             {"tables": {t: v["rows"] for t, v in r["manifest"]["tables"].items()},
              "documents": r["manifest"]["documents"], "vectors": r["manifest"]["vectors"],
              "caches": r["manifest"]["caches"], "verified": r["manifest"].get("verified")}} for r in rows]


@router.get("/admin/exports/{export_id}/download")
def download_export(export_id: uuid.UUID, a: Actor = Depends(actor)):
    a.require("tenant.export")
    with tenant_session(a.tenant_id) as s:
        ex = s.execute(text("SELECT status, file_path, sha256 FROM tenant_exports WHERE id=:i"), {"i": export_id}).first()
        if ex is None:
            raise HTTPException(404, {"code": "not_found", "message": "export not found"})
        if ex.status != "READY":
            raise HTTPException(409, {"code": "not_ready", "message": f"export is {ex.status}"})
        s.execute(text("UPDATE tenant_exports SET downloaded_at = now() WHERE id=:i"), {"i": export_id})
        s.execute(text("""INSERT INTO audit_events (tenant_id, actor_id, action, entity, entity_id, detail)
            VALUES (:t,:u,'tenant.export_downloaded','export',:e,CAST(:d AS jsonb))"""),
                  {"t": a.tenant_id, "u": a.user_id, "e": str(export_id), "d": json.dumps({"sha256": ex.sha256})})
    path = lifecycle._storage_file(ex.file_path)
    return FileResponse(path, media_type="application/zip", filename=f"supplylens-export-{export_id}.zip",
                        headers={"X-Export-SHA256": ex.sha256})


# ------------------------------------------------------------------------------------------ deletion
class DeletionIn(BaseModel):
    confirm_slug: str
    export_id: uuid.UUID
    reason: str = Field(min_length=5, max_length=500)


@router.post("/admin/tenant-deletion", response_model=DeletionQueued, status_code=202)
def request_deletion(body: DeletionIn, a: Actor = Depends(limit("deletion", 3)), idempotency_key: str | None = Header(None)):
    """Irreversible. Needs the typed workspace slug, a verified export that has been downloaded, and a reason."""
    a.require("tenant.delete")
    with control_session() as s:
        slug = s.execute(text("SELECT slug FROM tenants WHERE id=:t"), {"t": a.tenant_id}).scalar()
    if body.confirm_slug != slug:
        raise HTTPException(422, {"code": "confirmation_mismatch", "message": "type the workspace slug to confirm"})
    try:
        lifecycle.check_deletable(a.tenant_id, body.export_id)
    except lifecycle.LifecycleError as e:
        raise HTTPException(e.http, {"code": e.code, "message": str(e)}) from e

    def do():
        deletion_id = uuid.uuid4()
        with tenant_session(a.tenant_id) as s:
            job_id = _enqueue(s, a, "tenant_deletion", {"deletion_id": str(deletion_id), "export_id": str(body.export_id),
                                                         "requested_by": str(a.user_id)})
            s.execute(text("""INSERT INTO audit_events (tenant_id, actor_id, action, entity, entity_id, detail)
                VALUES (:t,:u,'tenant.deletion_requested','tenant',:e,CAST(:d AS jsonb))"""),
                      {"t": a.tenant_id, "u": a.user_id, "e": str(a.tenant_id),
                       "d": json.dumps({"deletion_id": str(deletion_id), "export_id": str(body.export_id),
                                        "reason": body.reason})})
        return 202, {"deletion_id": str(deletion_id), "job_id": str(job_id), "status": "QUEUED",
                     "certificate_url": f"/api/v1/deletions/{deletion_id}"}
    code, resp = idempotent(a, idempotency_key, "tenant-deletion", body.model_dump(mode="json"), do)
    from fastapi.responses import JSONResponse
    return JSONResponse(resp, status_code=code)


@router.get("/deletions/{deletion_id}", response_model=DeletionCertificate)
def deletion_certificate(deletion_id: uuid.UUID, request: Request):
    """Readable by whoever requested it, after the workspace itself is gone (no tenant header needed)."""
    uid = current_user_id(request)
    with control_session() as s:
        row = s.execute(text("SELECT tenant_slug, completed_at, certificate FROM tenant_deletions "
                             "WHERE id=:i AND requested_by=:u"), {"i": deletion_id, "u": uid}).mappings().first()
    if row is None:
        raise HTTPException(404, {"code": "not_found", "message": "no such certificate (yet)"})
    return dict(row)


# ------------------------------------------------------------------------------------------ web vitals
class VitalIn(BaseModel):
    metric: str = Field(pattern="^(LCP|INP|CLS|FCP|TTFB)$")
    value: float = Field(ge=0, le=600_000)
    rating: str = Field(pattern="^(good|needs-improvement|poor)$")
    route: str = Field(max_length=120)
    nav_type: str | None = Field(default=None, max_length=40)


@router.post("/telemetry/vitals", status_code=204)
def report_vital(body: VitalIn, a: Actor = Depends(limit("vitals", 240, 60))):
    a.require("read")
    with tenant_session(a.tenant_id) as s:
        s.execute(text("INSERT INTO web_vitals (tenant_id, user_id, metric, value, rating, route, nav_type) "
                       "VALUES (:t,:u,:m,:v,:r,:ro,:n)"),
                  {"t": a.tenant_id, "u": a.user_id, "m": body.metric, "v": body.value, "r": body.rating,
                   "ro": body.route, "n": body.nav_type})


TARGETS = {"LCP": 2500.0, "INP": 200.0, "CLS": 0.1}


@router.get("/admin/vitals", response_model=Vitals)
def vitals(days: int = 7, a: Actor = Depends(actor)):
    """Field p75 per metric and route against the UX-011 targets (LCP 2.5 s, INP 200 ms, CLS 0.1)."""
    a.require("admin.read")
    with tenant_session(a.tenant_id) as s:
        rows = s.execute(text("""SELECT metric, route, count(*) n, percentile_cont(0.75) WITHIN GROUP (ORDER BY value) p75
            FROM web_vitals WHERE at > now() - make_interval(days => :d) GROUP BY metric, route ORDER BY metric, route"""),
                         {"d": max(1, min(days, 90))}).mappings().all()
    out = [{**dict(r), "p75": float(r["p75"]), "target": TARGETS.get(r["metric"]),
            "meets_target": (float(r["p75"]) <= TARGETS[r["metric"]]) if r["metric"] in TARGETS else None} for r in rows]
    return {"window_days": days, "targets": TARGETS, "metrics": out,
            "note": "Field data from real browsers; empty until users load the app. Lab results are in docs/operations."}
