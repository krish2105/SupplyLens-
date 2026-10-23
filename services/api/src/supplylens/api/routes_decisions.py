"""Forecasts, models, terms, documents, evidence search, scenarios, agent runs and actions."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, date, datetime

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from ..actions import service as actions
from ..agent.graph import create_run
from ..authz import Actor, resolve_actor
from ..config import settings
from ..db import tenant_session
from ..forecasting.service import run_forecast
from ..inline_jobs import drain
from ..integrations import sandbox_erp
from ..knowledge import acl
from ..knowledge import upload as doc_upload
from ..knowledge.ingest import read_version_text
from ..knowledge.retrieve import search
from ..planning.scenario import ScenarioInput, run_scenario
from ..planning.terms_service import applicable_terms
from .deps import actor, csrf_guard, idempotent
from .ratelimit import limit
from .schemas import (
    ActionDetail,
    ActionResult,
    ActionRow,
    CancelOpenResult,
    DocumentRow,
    DocumentUploaded,
    DocumentVersion,
    EvidenceSearch,
    FaultInjected,
    ForecastRun,
    ModelVersion,
    OpenOrderLine,
    ReceiptResult,
    RunCreated,
    RunDetail,
    RunEvent,
    RunRow,
    SandboxOrder,
    ScenarioResult,
    ScenarioRow,
    Terms,
)

router = APIRouter(prefix="/api/v1", dependencies=[Depends(csrf_guard)])


def _settings(s):
    return s.execute(text("SELECT operational_as_of, currency, dataset_id, planning FROM tenant_settings")).first()


def _cutoff(st, override: datetime | None) -> datetime:
    """Explicit cutoff, else the workspace as-of, else now (workspaces without operational settings)."""
    if override:
        return override
    return st.operational_as_of if st else datetime.now(UTC)


class ForecastIn(BaseModel):
    sku_ids: list[str] = Field(min_length=1, max_length=200)
    origin: date | None = None
    horizon: int = Field(default=28, ge=1, le=90)
    model_family: str | None = Field(default=None, pattern="^(seasonal_naive|lightgbm_quantile|tcn_quantile)$")


@router.post("/forecasts", response_model=ForecastRun)
def create_forecast(body: ForecastIn, a: Actor = Depends(limit("forecast", 30))):
    a.require("forecast.run")
    with tenant_session(a.tenant_id) as s:
        st = _settings(s)
    if not st or not st.dataset_id:
        raise HTTPException(422, {"code": "no_sales_history", "message": "this workspace has no sales dataset"})
    run = run_forecast(a.tenant_id, st.dataset_id, body.sku_ids, body.origin or st.operational_as_of.date(),
                       body.horizon, created_by=a.user_id, model_family=body.model_family)
    return get_forecast(str(run.run_id), a)


@router.get("/forecasts/{run_id}", response_model=ForecastRun)
def get_forecast(run_id: uuid.UUID, a: Actor = Depends(actor)):
    a.require("read")
    with tenant_session(a.tenant_id) as s:
        r = s.execute(text("""SELECT fr.*, mv.family, mv.version FROM forecast_runs fr
            JOIN model_versions mv ON mv.id = fr.model_version_id WHERE fr.id = :i"""), {"i": run_id}).mappings().first()
        if not r:
            raise HTTPException(404, {"code": "not_found", "message": "forecast run not found"})
        pts = s.execute(text("SELECT sku_id, day, q10, q50, q90 FROM forecast_points WHERE run_id=:i "
                             "ORDER BY sku_id, day"), {"i": run_id}).mappings().all()
    return {**dict(r), "label": "unit-sales forecast (not unconstrained demand)",
            "interval": "10-90% from training-period seasonal errors", "points": [dict(p) for p in pts]}


@router.get("/models", response_model=list[ModelVersion])
def models(a: Actor = Depends(actor)):
    a.require("read")
    with tenant_session(a.tenant_id) as s:
        rows = s.execute(text("""SELECT id, family, version, status, training_cutoff, config, metrics,
            artifact_sha256, code_version, created_at FROM model_versions ORDER BY created_at""")).mappings().all()
    return [dict(r) for r in rows]


@router.get("/terms", response_model=Terms)
def terms(sku_id: str, knowledge_cutoff: datetime | None = None, effective_date: date | None = None,
          a: Actor = Depends(actor)):
    a.require("read")
    with tenant_session(a.tenant_id) as s:
        st = _settings(s)
    cutoff = _cutoff(st, knowledge_cutoff)
    eff = effective_date or cutoff.date()
    res = applicable_terms(a.tenant_id, [sku_id], cutoff, eff)
    with tenant_session(a.tenant_id) as s:
        all_terms = s.execute(text("""SELECT st.*, dv.version_label, d.title FROM supplier_terms st
            LEFT JOIN document_versions dv ON dv.id = st.document_version_id
            LEFT JOIN documents d ON d.id = dv.document_id WHERE st.sku_id = :k ORDER BY st.supplier_id, st.valid_from"""),
            {"k": sku_id}).mappings().all()
        out = {"knowledge_cutoff": cutoff, "effective_date": eff,
               "applicable": [t.model_dump(mode="json") for t in res.applicable],
               "ignored": [i.model_dump() for i in res.ignored], "conflicts": res.conflicts,
               "history": [{**dict(t), "document_version_id": str(t["document_version_id"]) if t["document_version_id"]
                            else None} for t in all_terms]}
        return acl.redact(s, a.role, out)


@router.get("/documents", response_model=list[DocumentRow])
def documents(response: Response, limit: int | None = Query(None, ge=1), offset: int = Query(0, ge=0),
              a: Actor = Depends(actor)):
    """Bounded at settings.list_max_rows rows (Phase 3). X-Total-Count gives the full count; pass limit/offset to page.
    Chunk counts come from one grouped scan instead of a sub-query per version."""
    a.require("read")
    lim = min(limit or settings.list_max_rows, settings.list_max_rows)
    with tenant_session(a.tenant_id) as s:
        rows = s.execute(text("""SELECT d.id AS document_id, d.title, d.doc_type, d.supplier_id, d.source_kind,
            dv.id AS version_id, dv.version_label, dv.file_name, dv.sha256, dv.known_at, dv.valid_from, dv.valid_to,
            dv.supersedes_version_id, dv.embed_model, COALESCE(cc.n, 0) AS chunks, count(*) OVER () AS _total
            FROM documents d JOIN document_versions dv ON dv.document_id = d.id
            LEFT JOIN (SELECT version_id, count(*) AS n FROM chunks GROUP BY version_id) cc ON cc.version_id = dv.id
            WHERE :role = ANY(d.allowed_roles) ORDER BY d.supplier_id NULLS LAST, dv.valid_from, dv.id
            LIMIT :lim OFFSET :off"""), {"role": a.role, "lim": lim, "off": offset}).mappings().all()
        total = rows[0]["_total"] if rows else (0 if offset == 0 else s.execute(text(
            "SELECT count(*) FROM documents d JOIN document_versions dv ON dv.document_id = d.id "
            "WHERE :role = ANY(d.allowed_roles)"), {"role": a.role}).scalar())
    response.headers["X-Total-Count"] = str(total)
    return [{k: v for k, v in r.items() if k != "_total"} for r in rows]


@router.post("/documents", response_model=DocumentUploaded, status_code=201)
async def upload_document(file: UploadFile = File(...), title: str = Form(...), doc_type: str = Form("contract"),
                          version_label: str = Form(...), valid_from: date = Form(...), valid_to: date | None = Form(None),
                          supplier_id: str | None = Form(None), supersedes_version_id: uuid.UUID | None = Form(None),
                          a: Actor = Depends(limit("document_upload", 20))):
    """Add a supplier document or a new version of one (plain text). Known from now; in force from valid_from."""
    data = await file.read(doc_upload.MAX_BYTES + 1)
    try:
        return doc_upload.upload_document(a, file_name=file.filename or "document.txt", data=data, title=title,
                                          doc_type=doc_type, version_label=version_label, valid_from=valid_from,
                                          valid_to=valid_to, supplier_id=supplier_id,
                                          supersedes_version_id=supersedes_version_id)
    except doc_upload.UploadError as e:
        raise HTTPException(e.http, {"code": e.code, "message": str(e)}) from e


@router.get("/documents/versions/{version_id}", response_model=DocumentVersion)
def document_version(version_id: uuid.UUID, a: Actor = Depends(actor)):
    a.require("read")
    with tenant_session(a.tenant_id) as s:
        v = acl.require_version(s, a.role, version_id)
        if v is None:
            raise HTTPException(404, {"code": "not_found", "message": "document not found"})
        chunks = s.execute(text("SELECT id, ordinal, section, char_start, char_end FROM chunks WHERE version_id=:i "
                                "ORDER BY ordinal"), {"i": version_id}).mappings().all()
    return {**{k: v[k] for k in v.keys() if k not in ("storage_key", "allowed_roles")},
            "text": read_version_text(v["storage_key"]), "chunks": [dict(c) for c in chunks],
            "untrusted_content": True}


@router.get("/evidence/search", response_model=EvidenceSearch)
def evidence(q: str, knowledge_cutoff: datetime | None = None, effective_date: date | None = None,
             mode: str = "effective", supplier_id: str | None = None, k: int = 8, a: Actor = Depends(limit("search", 120))):
    a.require("read")
    if mode not in ("effective", "known") or not q.strip() or len(q) > 500:
        raise HTTPException(422, {"code": "invalid_query", "message": "query 1-500 chars; mode effective|known"})
    with tenant_session(a.tenant_id) as s:
        st = _settings(s)
    cutoff = _cutoff(st, knowledge_cutoff)
    ents = [w for w in q.replace(",", " ").split() if any(ch.isdigit() for ch in w)]
    res = search(a.tenant_id, q, as_of=cutoff, role=a.role, effective_date=effective_date, mode=mode,
                 supplier_id=supplier_id, entities=ents, k=max(1, min(k, 20)))
    results = [e.__dict__ for e in res["results"]]
    support = res["support"]
    answer = {"type": "extractive", "claims": [], "support": support,
              "abstained": not results or res["abstain"] or not support["supported"] or support["ambiguous"]}
    if res["abstain"]:
        answer["message"] = ("No permitted document known at this cutoff mentions " + ", ".join(ents) +
                             ". Related passages are listed but not used as an answer.")
    elif results and not support["supported"]:
        answer["message"] = (f"No passage known at this cutoff answers this: {support['reason']}. "
                             "Related passages are listed but not used as an answer.")
    elif results and support["ambiguous"]:
        answer["message"] = ("Several suppliers' terms match equally (" + ", ".join(support["candidate_suppliers"]) +
                             "). Name the supplier or the product code to get one answer.")
    elif results:
        top = results[0]
        answer["claims"].append({"text": top["excerpt"], "citation": {
            "document_id": top["document_id"], "version_id": top["version_id"], "version_label": top["version_label"],
            "section": top["section"], "char_start": top["char_start"], "char_end": top["char_end"]}})
    else:
        answer["message"] = "No permitted document known at this cutoff matches the question."
    return {**res, "results": results, "answer": answer}


@router.post("/scenarios", response_model=ScenarioResult)
def scenarios(body: ScenarioInput, a: Actor = Depends(limit("scenario", 20))):
    try:
        return run_scenario(a, body)
    except ValueError as e:
        raise HTTPException(422, {"code": "scenario_invalid", "message": str(e)}) from e


@router.get("/scenarios", response_model=list[ScenarioRow])
def list_scenarios(a: Actor = Depends(actor)):
    a.require("read")
    with tenant_session(a.tenant_id) as s:
        rows = s.execute(text("""SELECT id, as_of, status, request, created_at, result->'metrics' AS metrics,
            result->>'name' AS name FROM plan_runs ORDER BY created_at DESC LIMIT 50""")).mappings().all()
    return [dict(r) for r in rows]


class AgentRunIn(BaseModel):
    mode: str = "draft"
    sku_ids: list[str] | None = None
    knowledge_cutoff: datetime | None = None
    effective_date: date | None = None
    budget_minor: int | None = Field(default=None, ge=0)
    currency: str | None = None
    allow_shortfall: bool = True


@router.post("/agent-runs", response_model=RunCreated, status_code=202)
def start_run(body: AgentRunIn, a: Actor = Depends(limit("agent_run", 30)), idempotency_key: str | None = Header(None)):
    def do():
        run_id = create_run(a, mode=body.mode, inp=body.model_dump(mode="json", exclude_none=True))
        return 202, {"run_id": str(run_id), "status": "QUEUED", "status_url": f"/api/v1/agent-runs/{run_id}",
                     "events_url": f"/api/v1/agent-runs/{run_id}/stream"}
    try:
        code, resp = idempotent(a, idempotency_key, "agent-runs", body.model_dump(mode="json"), do)
    except ValueError as e:
        raise HTTPException(422, {"code": "invalid_run", "message": str(e)}) from e
    drain(a.tenant_id)           # serverless hosting only (settings.inline_jobs); the worker does this otherwise
    return JSONResponse(resp, status_code=code)


@router.get("/agent-runs", response_model=list[RunRow])
def runs(a: Actor = Depends(actor)):
    a.require("read")
    with tenant_session(a.tenant_id) as s:
        rows = s.execute(text("""SELECT r.id, r.status, r.mode, r.input, r.created_at, r.updated_at, u.email AS created_by,
            (SELECT count(*) FROM actions x WHERE x.agent_run_id = r.id) AS actions
            FROM agent_runs r JOIN users u ON u.id = r.created_by ORDER BY r.created_at DESC LIMIT 50""")).mappings().all()
    return [dict(r) for r in rows]


@router.get("/agent-runs/{run_id}", response_model=RunDetail)
def run_detail(run_id: uuid.UUID, a: Actor = Depends(actor)):
    a.require("read")
    with tenant_session(a.tenant_id) as s:
        r = s.execute(text("SELECT * FROM agent_runs WHERE id=:i"), {"i": run_id}).mappings().first()
        if not r:
            raise HTTPException(404, {"code": "not_found", "message": "run not found"})
        acts = s.execute(text("SELECT id, status, total_minor, currency, payload->>'supplier_id' AS supplier_id "
                              "FROM actions WHERE agent_run_id=:i ORDER BY created_at"), {"i": run_id}).mappings().all()
    state = r["state"] or {}
    forecast = {k: v for k, v in (state.get("forecast") or {}).items() if k != "points"}
    out = {"id": r["id"], "status": r["status"], "mode": r["mode"], "input": r["input"], "budget": r["budget"],
            "created_at": r["created_at"], "updated_at": r["updated_at"], "settings": state.get("settings"),
            "forecast": forecast or None, "plan": state.get("plan"), "checks": state.get("checks"),
            "terms": state.get("terms"), "upcoming_changes": state.get("upcoming_changes"),
            "needs": (state.get("needs") or {}).get("assessments"), "tool_calls": state.get("tool_calls"),
            "scope": {**(state.get("scope") or {}), "not_assessed": (state.get("needs") or {}).get("not_assessed")},
            "actions": [dict(x) for x in acts]}
    with tenant_session(a.tenant_id) as s:
        return acl.redact(s, a.role, out)


def _events(tenant_id, run_id, after: int, role: str):
    with tenant_session(tenant_id) as s:
        rows = [dict(r) for r in s.execute(text("""SELECT seq, node, kind, summary, data, created_at FROM agent_events
            WHERE run_id=:r AND seq > :a ORDER BY seq"""), {"r": run_id, "a": after}).mappings()]
        return acl.redact(s, role, rows)


@router.get("/agent-runs/{run_id}/events", response_model=list[RunEvent])
def run_events(run_id: uuid.UUID, after: int = 0, a: Actor = Depends(actor)):
    a.require("read")
    return _events(a.tenant_id, run_id, after, a.role)


TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED", "REVIEW_REQUIRED", "WAITING_FOR_APPROVAL", "COMPLETE",
            "CLOSED_WITHOUT_ORDER", "PARTIAL"}


@router.get("/agent-runs/{run_id}/stream")
async def run_stream(run_id: uuid.UUID, request: Request, a: Actor = Depends(actor),
                     last_event_id: str | None = Header(None)):
    """Server-sent events of persisted run events; reconnect with Last-Event-ID (monotonic seq)."""
    a.require("read")
    tenant = a.tenant_id
    with tenant_session(tenant) as s:
        if not s.execute(text("SELECT 1 FROM agent_runs WHERE id=:i"), {"i": run_id}).first():
            raise HTTPException(404, {"code": "not_found", "message": "run not found"})

    async def gen():
        cursor = int(last_event_id or 0)
        idle = 0
        while not await request.is_disconnected():
            # Re-check membership each poll so revocation takes effect on the open stream.
            if resolve_actor(a.user_id, tenant) is None:
                break
            evs = await asyncio.to_thread(_events, tenant, run_id, cursor, a.role)
            for e in evs:
                cursor = e["seq"]
                yield f"id: {cursor}\nevent: run_event\ndata: {json.dumps(e, default=str)}\n\n"
            with tenant_session(tenant) as s:
                status = s.execute(text("SELECT status FROM agent_runs WHERE id=:i"), {"i": run_id}).scalar()
            if status in TERMINAL and not evs:
                yield f"event: status\ndata: {json.dumps({'status': status})}\n\n"
                break
            idle = idle + 1 if not evs else 0
            if idle > 600 or status is None:
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/actions", response_model=list[ActionRow])
def list_actions(status: str | None = None, a: Actor = Depends(actor)):
    a.require("read")
    with tenant_session(a.tenant_id) as s:
        rows = s.execute(text("""SELECT x.id, x.status, x.total_minor, x.currency, x.payload, x.payload_hash, x.row_version,
            x.external_ref, x.status_reason, x.created_at, x.updated_at, x.agent_run_id, u.email AS prepared_by
            FROM actions x JOIN users u ON u.id = x.prepared_by WHERE (CAST(:s AS text) IS NULL OR x.status = :s)
            ORDER BY x.created_at DESC LIMIT 100"""), {"s": status}).mappings().all()
    return [dict(r) for r in rows]


@router.get("/actions/{action_id}", response_model=ActionDetail)
def action_detail(action_id: uuid.UUID, a: Actor = Depends(actor)):
    detail = actions.get(a, action_id)
    with tenant_session(a.tenant_id) as s:
        return acl.redact(s, a.role, json.loads(json.dumps(detail, default=str)))


class ApproveIn(BaseModel):
    payload_hash: str
    expected_row_version: int
    max_spend_minor: int | None = None


class RejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    expected_row_version: int


class EditIn(BaseModel):
    quantities: dict[str, int]
    expected_row_version: int


def _guard(fn):
    try:
        return fn()
    except actions.ActionError as e:
        raise HTTPException(e.http, {"code": e.code, "message": str(e)}) from e


@router.post("/actions/{action_id}/approve", response_model=ActionResult)
def approve(action_id: uuid.UUID, body: ApproveIn, a: Actor = Depends(actor),
            idempotency_key: str | None = Header(None)):
    code, resp = idempotent(a, idempotency_key, f"approve:{action_id}", body.model_dump(),
                            lambda: (200, _guard(lambda: actions.approve(
                                a, action_id, payload_hash=body.payload_hash,
                                expected_row_version=body.expected_row_version,
                                max_spend_minor=body.max_spend_minor))))
    drain(a.tenant_id)
    return JSONResponse(json.loads(json.dumps(resp, default=str)), status_code=code)


@router.post("/actions/{action_id}/reject", response_model=ActionResult)
def reject(action_id: uuid.UUID, body: RejectIn, a: Actor = Depends(actor),
           idempotency_key: str | None = Header(None)):
    code, resp = idempotent(a, idempotency_key, f"reject:{action_id}", body.model_dump(),
                            lambda: (200, _guard(lambda: actions.reject(
                                a, action_id, reason=body.reason, expected_row_version=body.expected_row_version))))
    return JSONResponse(resp, status_code=code)


@router.post("/actions/{action_id}/edit", response_model=ActionDetail)
def edit(action_id: uuid.UUID, body: EditIn, a: Actor = Depends(actor), idempotency_key: str | None = Header(None)):
    with tenant_session(a.tenant_id) as s:
        st = _settings(s)
    # fallback only for drafts whose decision predates the stored budget (edit_quantities prefers the decision's own)
    planning = (st.planning or {}) if st else {}
    budget = int(planning["weekly_budget_minor"]) if planning.get("weekly_budget_minor") is not None else None
    code, resp = idempotent(a, idempotency_key, f"edit:{action_id}", body.model_dump(),
                            lambda: (200, _guard(lambda: actions.edit_quantities(
                                a, action_id, quantities=body.quantities,
                                expected_row_version=body.expected_row_version, budget_minor=budget))))
    return JSONResponse(json.loads(json.dumps(resp, default=str)), status_code=code)


@router.post("/actions/{action_id}/reconcile", response_model=ActionResult)
def reconcile(action_id: uuid.UUID, a: Actor = Depends(actor)):
    out = _guard(lambda: actions.reconcile(a, action_id))
    drain(a.tenant_id)
    return out


@router.post("/actions/{action_id}/retry", response_model=ActionResult)
def retry(action_id: uuid.UUID, a: Actor = Depends(actor)):
    """Re-queue a FAILED dispatch (e.g. after a connector outage) under the same idempotency key."""
    out = _guard(lambda: actions.retry_failed(a, action_id))
    drain(a.tenant_id)
    return out


class ReceiptIn(BaseModel):
    sku_id: str = Field(min_length=1, max_length=64)
    location_id: str | None = Field(default=None, max_length=64)
    quantity: int = Field(gt=0, le=1_000_000)
    received_on: date


class CancelOpenIn(BaseModel):
    sku_id: str = Field(min_length=1, max_length=64)
    location_id: str | None = Field(default=None, max_length=64)
    reason: str = Field(min_length=1, max_length=500)


@router.post("/actions/{action_id}/receipts", response_model=ReceiptResult)
def receipt(action_id: uuid.UUID, body: ReceiptIn, a: Actor = Depends(actor), idempotency_key: str | None = Header(None)):
    """Book units received on a reconciled order line (moves them from on-order to on-hand in the next plan)."""
    if not idempotency_key:
        raise HTTPException(428, {"code": "idempotency_key_required", "message": "Idempotency-Key header required"})
    return _guard(lambda: actions.record_receipt(a, action_id, sku_id=body.sku_id, quantity=body.quantity,
                                                 received_on=body.received_on, key=idempotency_key,
                                                 location_id=body.location_id))


@router.post("/actions/{action_id}/cancel-open", response_model=CancelOpenResult)
def cancel_open(action_id: uuid.UUID, body: CancelOpenIn, a: Actor = Depends(actor)):
    return _guard(lambda: actions.cancel_open_units(a, action_id, sku_id=body.sku_id, reason=body.reason,
                                                    location_id=body.location_id))


class AcceptRemoteIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


@router.post("/actions/{action_id}/accept-remote", response_model=ActionDetail)
def accept_remote(action_id: uuid.UUID, body: AcceptRemoteIn, a: Actor = Depends(actor)):
    """Resolve a read-back mismatch by recording the order as the target holds it (approver, not the preparer)."""
    detail = _guard(lambda: actions.accept_remote_order(a, action_id, reason=body.reason))
    with tenant_session(a.tenant_id) as s:
        return acl.redact(s, a.role, json.loads(json.dumps(detail, default=str)))


@router.get("/open-orders", response_model=list[OpenOrderLine])
def list_open_orders(a: Actor = Depends(actor)):
    return actions.open_orders(a)


@router.get("/sandbox/orders", response_model=list[SandboxOrder])
def sandbox_orders(a: Actor = Depends(actor)):
    """The sandbox ERP's own view (simulated external system), filtered to this tenant's actions."""
    a.require("read")
    with tenant_session(a.tenant_id) as s:
        refs = [str(r.id) for r in s.execute(text("SELECT id FROM actions"))]
    from ..db import app_engine
    with app_engine().connect() as c:
        rows = c.execute(text("""SELECT po_number, idempotency_key, caller_ref, supplier_id, lines, total_minor, currency,
            status, created_at FROM sandbox_erp.purchase_orders WHERE caller_ref = ANY(:r) ORDER BY created_at DESC"""),
            {"r": refs}).mappings().all()
    return [dict(r) for r in rows]


class FaultIn(BaseModel):
    action_id: uuid.UUID
    mode: str


@router.post("/sandbox/faults", response_model=FaultInjected)
def sandbox_fault(body: FaultIn, a: Actor = Depends(actor)):
    """Development-only fault injection to demonstrate unknown-outcome reconciliation."""
    if not settings.dev_login_available:
        raise HTTPException(404, {"code": "disabled", "message": "fault injection disabled"})
    a.require("action.reconcile")
    if body.mode not in ("timeout_after_commit", "fail_before_commit", "alter_line_price", "duplicate_line",
                         "change_unit", "change_need_by", "cancel_after_commit"):
        raise HTTPException(422, {"code": "invalid_mode", "message": "unknown fault mode"})
    actions.get(a, body.action_id)  # tenant check
    sandbox_erp.inject_fault(f"po-{body.action_id}", body.mode)
    return {"ok": True, "operation_id": f"po-{body.action_id}", "mode": body.mode}
