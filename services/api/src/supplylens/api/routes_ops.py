"""Exceptions inbox, administration, clause labels and the (simulated) value report."""
from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from ..authz import MATRIX, Actor
from ..config import REPO_ROOT
from ..db import control_session, tenant_session
from .deps import actor, csrf_guard, idempotent
from .routes_core import INVENTORY_SQL
from .schemas import ClauseLabel, Exceptions, Jobs, Members, ModelStatusChanged, Value

router = APIRouter(prefix="/api/v1", dependencies=[Depends(csrf_guard)])


@router.get("/exceptions", response_model=Exceptions)
def exceptions(effective_date: date | None = None, a: Actor = Depends(actor)):
    """Observed vs predicted exceptions with materiality, basis and a decision deadline."""
    a.require("read")
    items = []
    with tenant_session(a.tenant_id) as s:
        st = s.execute(text("SELECT operational_as_of, currency FROM tenant_settings")).first()
        if st is None:
            return {"effective_date": None, "items": [], "message": "This workspace has no operational stock or terms."}
        eff = effective_date or st.operational_as_of.date()
        cur = st.currency.strip()
        inv = s.execute(text(INVENTORY_SQL), {"eff": eff}).mappings().all()
        price = dict(s.execute(text("""SELECT sku_id, percentile_disc(0.5) WITHIN GROUP (ORDER BY unit_price_minor)
            FROM sales_lines WHERE invoiced_at::date > CAST(:e AS date) - 90 AND invoiced_at::date <= :e GROUP BY sku_id"""), {"e": eff}).all())
        for r in inv:
            avg, avail = r["avg_daily"], r["on_hand"] - r["allocated"]
            if not avg:
                continue
            cover = avail / avg
            if cover < 7:
                short_units = avg * 7 - avail
                items.append({"kind": "shortage_risk", "basis": "predicted", "sku_id": r["sku_id"], "title": f"{r['sku_id']} covers {cover:.1f} days",
                              "detail": f"{avail} available vs {avg:.1f}/day recent unit sales", "severity": "high" if cover < 2 else "medium",
                              "materiality_minor": int(short_units * price.get(r["sku_id"], 0)), "materiality_basis": "7-day shortfall x median selling price (revenue at risk, not margin)",
                              "deadline": str(eff + timedelta(days=max(int(cover), 0))), "value_kind": "derived"})
            elif cover > 90:
                items.append({"kind": "excess", "basis": "derived", "sku_id": r["sku_id"], "title": f"{r['sku_id']} covers {cover:.0f} days",
                              "detail": "Stock above 90 days of recent sales", "severity": "low",
                              "materiality_minor": int((avail - avg * 90) * price.get(r["sku_id"], 0) * 0.55),
                              "materiality_basis": "excess units x assumed unit cost (55% of selling price)", "deadline": None, "value_kind": "derived"})
        upcoming = s.execute(text("""SELECT st.term_id, st.supplier_id, st.sku_id, st.moq, st.lead_time_days, st.valid_from, st.known_at,
            prev.moq AS prev_moq, prev.lead_time_days AS prev_lead FROM supplier_terms st
            LEFT JOIN supplier_terms prev ON prev.term_id = st.supersedes_term_id
            WHERE st.supersedes_term_id IS NOT NULL AND st.known_at <= :cut AND st.valid_from > :e"""),
            {"cut": st.operational_as_of if not effective_date else datetime.combine(eff, datetime.max.time(), UTC), "e": eff}).mappings().all()
        for u in upcoming:
            items.append({"kind": "policy_change", "basis": "observed document", "sku_id": u["sku_id"],
                          "title": f"{u['supplier_id']} changes terms for {u['sku_id']} on {u['valid_from']}",
                          "detail": f"MOQ {u['prev_moq']} → {u['moq']}, lead time {u['prev_lead']} → {u['lead_time_days']} days",
                          "severity": "medium", "materiality_minor": None, "materiality_basis": None, "deadline": str(u["valid_from"]),
                          "value_kind": "simulated"})
        acts = s.execute(text("""SELECT id, status, total_minor, currency, payload->>'supplier_id' supplier, created_at, status_reason
            FROM actions WHERE status IN ('UNKNOWN_OUTCOME','STALE','PENDING_APPROVAL','FAILED')""")).mappings().all()
        for x in acts:
            age_h = (datetime.now(UTC) - x["created_at"]).total_seconds() / 3600
            items.append({"kind": "action_" + x["status"].lower(), "basis": "system state", "sku_id": None, "action_id": str(x["id"]),
                          "title": {"UNKNOWN_OUTCOME": "Order outcome unknown — reconcile", "STALE": "Draft is stale — recompute",
                                    "PENDING_APPROVAL": "Draft awaiting approval", "FAILED": "Dispatch failed"}[x["status"]] + f" ({x['supplier']})",
                          "detail": x["status_reason"] or f"waiting {age_h:.0f} h", "severity": "high" if x["status"] in ("UNKNOWN_OUTCOME", "FAILED") else "medium",
                          "materiality_minor": x["total_minor"], "materiality_basis": "order value", "deadline": None, "value_kind": "observed"})
    order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda i: (order[i["severity"]], -(i["materiality_minor"] or 0)))
    return {"effective_date": eff, "currency": cur, "items": items,
            "counts": {k: sum(i["kind"] == k for i in items) for k in sorted({i["kind"] for i in items})}}


@router.get("/admin/members", response_model=Members)
def members(a: Actor = Depends(actor)):
    a.require("admin.read")
    with control_session() as s:
        rows = s.execute(text("""SELECT u.email, u.display_name, u.active, u.is_dev_account, m.role, m.created_at FROM memberships m
            JOIN users u ON u.id = m.user_id WHERE m.tenant_id = :t ORDER BY m.role, u.email"""), {"t": a.tenant_id}).mappings().all()
    return {"members": [dict(r) for r in rows], "role_matrix": {k: sorted(v) for k, v in MATRIX.items()},
            "note": "Membership changes are made by the identity integration (not configured) or owner tooling; read-only here."}


@router.get("/admin/jobs", response_model=Jobs)
def jobs(a: Actor = Depends(actor)):
    a.require("admin.read")
    with tenant_session(a.tenant_id) as s:
        j = s.execute(text("""SELECT id, kind, status, attempts, max_attempts, lease_owner, lease_expires_at, error, created_at, updated_at,
            result->>'status' AS result_status FROM jobs ORDER BY created_at DESC LIMIT 100""")).mappings().all()
        o = s.execute(text("""SELECT operation_id, status, attempts, last_error, external_ref, next_attempt_at, updated_at FROM outbox
            ORDER BY updated_at DESC LIMIT 100""")).mappings().all()
        usage = s.execute(text("""SELECT count(*) runs, coalesce(sum((state->>'tool_calls')::int),0) tool_calls,
            count(*) FILTER (WHERE created_at > now() - interval '24 hours') runs_24h FROM agent_runs""")).mappings().first()
    return {"jobs": [dict(r) for r in j], "outbox": [dict(r) for r in o],
            "usage": {**dict(usage), "llm_tokens": 0, "budget": {"max_runs_per_day": 200, "max_tool_calls_per_run": 400},
                      "budget_note": "Configured limits; no paid model provider is used."}}


class PromoteIn(BaseModel):
    status: str = Field(pattern="^(CHAMPION|CANDIDATE|RETIRED)$")
    reason: str = Field(min_length=5, max_length=500)


@router.post("/models/{model_id}/status", response_model=ModelStatusChanged)
def set_model_status(model_id: uuid.UUID, body: PromoteIn, a: Actor = Depends(actor), idempotency_key: str | None = Header(None)):
    """Promotion is an audited administrative decision; one CHAMPION per tenant."""
    a.require("admin.write")

    def do():
        with tenant_session(a.tenant_id) as s:
            m = s.execute(text("SELECT family, status, metrics FROM model_versions WHERE id=:i FOR UPDATE"), {"i": model_id}).mappings().first()
            if not m:
                raise HTTPException(404, {"code": "not_found", "message": "model not found"})
            if body.status == "CHAMPION":
                if not (m["metrics"] or {}).get("experiment_id") and m["family"] != "seasonal_naive":
                    raise HTTPException(422, {"code": "not_evaluated", "message": "only models with a recorded evaluation can be champion"})
                s.execute(text("UPDATE model_versions SET status='CANDIDATE' WHERE status='CHAMPION' AND id <> :i"), {"i": model_id})
            s.execute(text("UPDATE model_versions SET status=:st WHERE id=:i"), {"st": body.status, "i": model_id})
            s.execute(text("""INSERT INTO audit_events (tenant_id, actor_id, action, entity, entity_id, detail) VALUES
                (:t,:u,'model.status_changed','model',:e,CAST(:d AS jsonb))"""),
                {"t": a.tenant_id, "u": a.user_id, "e": str(model_id),
                 "d": json.dumps({"from": m["status"], "to": body.status, "family": m["family"], "reason": body.reason})})
        return 200, {"model_id": str(model_id), "status": body.status}
    code, resp = idempotent(a, idempotency_key, f"model-status:{model_id}", body.model_dump(), do)
    return resp


def csv_safe(value) -> str:
    """Neutralise spreadsheet formula injection: a cell that starts with = + - @ tab or CR is prefixed with a quote."""
    s = str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


@router.get("/admin/audit.csv")
def audit_csv(a: Actor = Depends(actor)):
    a.require("admin.read")
    with tenant_session(a.tenant_id) as s:
        rows = s.execute(text("""SELECT ae.id, ae.at, u.email AS actor, ae.action, ae.entity, ae.entity_id, ae.detail FROM audit_events ae
            LEFT JOIN users u ON u.id = ae.actor_id ORDER BY ae.id""")).mappings().all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "at_utc", "actor", "action", "entity", "entity_id", "detail_json"])
    for r in rows:
        w.writerow([r["id"], r["at"].isoformat(), csv_safe(r["actor"] or "system"), csv_safe(r["action"]), csv_safe(r["entity"]),
                    csv_safe(r["entity_id"]), csv_safe(json.dumps(r["detail"]))])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="supplylens-audit-{date.today()}.csv"'})


@router.get("/documents/versions/{version_id}/labels", response_model=list[ClauseLabel])
def labels(version_id: uuid.UUID, a: Actor = Depends(actor)):
    a.require("read")
    with tenant_session(a.tenant_id) as s:
        rows = s.execute(text("""SELECT category, char_start, char_end, text, source FROM clause_labels WHERE version_id=:v
            ORDER BY category, char_start"""), {"v": version_id}).mappings().all()
    return [dict(r) for r in rows]


def _latest_metrics(prefix: str):
    d = REPO_ROOT / "artifacts" / "experiments"
    runs = sorted(p for p in d.glob(prefix + "-2*") if (p / "metrics.json").exists()) if d.exists() else []
    return json.loads((runs[-1] / "metrics.json").read_text()) if runs else None


@router.get("/value", response_model=Value)
def value(a: Actor = Depends(actor)):
    """Value ledger built only from simulated study outputs; every line names its evidence class."""
    a.require("read")
    s1, ib = _latest_metrics("S1"), _latest_metrics("IB")
    ledger = []
    if s1:
        base = s1["results"][s1["base_case"]]
        ledger.append({"item": "Policy change: median+safety → q90 order-up-to (seasonal naive forecasts)",
                       "evidence_class": "simulated estimate", "period": f"{s1['window'][0]} to {s1['window'][1]} (28 days)",
                       "baseline_minor": round(base["seasonal_naive"]["total_cost"] * 100),
                       "intervention_minor": round(base["seasonal_naive__sum_q90"]["total_cost"] * 100),
                       "unit": "GBP lost margin + holding cost", "source": s1["experiment_id"],
                       "assumptions": s1["assumptions"]})
        ledger.append({"item": "Forecaster change: seasonal naive → TCN (q90 policy)",
                       "evidence_class": "simulated estimate", "period": f"{s1['window'][0]} to {s1['window'][1]} (28 days)",
                       "baseline_minor": round(base["seasonal_naive__sum_q90"]["total_cost"] * 100),
                       "intervention_minor": round(base["tcn__sum_q90"]["total_cost"] * 100),
                       "unit": "GBP lost margin + holding cost", "source": s1["experiment_id"], "assumptions": s1["assumptions"]})
    return {"ledger": ledger, "sensitivity": s1["results"] if s1 else None, "inventorybench": ib["policies"] if ib else None,
            "formulas": ["Period net benefit = attributable operating benefit - incremental operating cost",
                         "ROI = (attributable benefit - total incremental cost) / total incremental cost",
                         "Carrying-cost benefit = reduction in average inventory value x carrying rate x period fraction"],
            "disclaimer": "All values are simulated on a demand proxy with assumed costs. None is a realised saving, and no "
                          "incremental product cost has been measured, so ROI is not computed."}
