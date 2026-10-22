"""Purchase-order draft lifecycle with approval binding, outbox, dispatch and reconciliation.

States: PENDING_APPROVAL -> APPROVED -> QUEUED -> SUBMITTED -> CONFIRMED -> RECONCILED,
with REJECTED, STALE, UNKNOWN_OUTCOME and FAILED. An approval binds the exact payload
hash, the source versions, the maximum spend, the approver and an expiry. Any edit or
change in the underlying terms makes the old approval unusable.

Dispatch rules (audits F07, S11). A retry of an attempt that may have reached the target looks the operation up FIRST,
before any approval check: an order the target already holds is verified and reconciled, never re-sent and never marked
stale because the approval has since expired. Only a demonstrably fresh send needs current authority, and it rechecks
everything the approval relied on: the bound payload hash, expiry, the approver still active with approval rights, the
action still queued, the spend within the approved maximum and the supplier terms still applicable. A changed fact
routes the action back to review (STALE) instead of sending.

Read-back (audit F06) compares the returned order with the approved payload line by line as multisets (SKU, quantity,
unit, unit price, line value), plus supplier, currency, total, need-by date and order status. Equal totals never stand
in for equal orders. A reconciled order enters the open-order ledger (purchase_order_lines) that planning reads (S12).
"""
from __future__ import annotations

import hashlib
import json
import socket
import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text

from supplylens_opt.planner import Need, PlanLine, PlanRequest, PlanResult
from supplylens_opt.validator import validate

from .. import alerts, telemetry
from ..authz import MATRIX, Actor, resolve_actor
from ..config import settings
from ..db import tenant_session
from ..idempotency import record_outcome
from ..integrations import sandbox_erp
from ..planning.terms_service import applicable_terms

LEASE_SECONDS = 45


class ActionError(Exception):
    def __init__(self, code: str, message: str, http: int = 409):
        super().__init__(message)
        self.code, self.http = code, http


def canonical_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _audit(s, tenant_id, actor_id, action, entity_id, detail):
    s.execute(text("INSERT INTO audit_events (tenant_id, actor_id, action, entity, entity_id, detail) "
                   "VALUES (:t,:a,:ac,'action',:e,CAST(:d AS jsonb))"),
              {"t": tenant_id, "a": actor_id, "ac": action, "e": str(entity_id),
               "d": json.dumps(detail, default=str)})


def _load(s, action_id, lock=False):
    row = s.execute(text("SELECT * FROM actions WHERE id = :i" + (" FOR UPDATE" if lock else "")),
                    {"i": action_id}).mappings().first()
    if not row:
        raise ActionError("not_found", "action not found", 404)
    return dict(row)


def build_payload(supplier_id: str, lines: list[PlanLine], currency: str, need_by: date,
                  decision: dict) -> dict:
    return {
        "environment": "sandbox", "destination": "sandbox_erp", "operation": "create_purchase_order",
        "supplier_id": supplier_id, "currency": currency, "need_by": need_by.isoformat(),
        "lines": [{"sku_id": l.sku_id, "quantity": l.quantity, "unit": "unit", "unit_cost_minor": l.unit_cost_minor,
                   "line_minor": l.line_minor, "term_id": l.term_id} for l in lines],
        "total_minor": sum(l.line_minor for l in lines),
        "decision": decision,
    }


def prepare(actor: Actor, *, supplier_id: str, lines: list[PlanLine], currency: str, need_by: date,
            decision: dict, evidence: dict, versions: dict, agent_run_id=None) -> dict:
    actor.require("action.prepare")
    payload = build_payload(supplier_id, lines, currency, need_by, decision)
    aid = uuid.uuid4()
    with tenant_session(actor.tenant_id) as s:
        s.execute(text("""INSERT INTO actions (id, tenant_id, kind, status, payload, payload_hash, evidence, versions,
            total_minor, currency, prepared_by, agent_run_id) VALUES (:i,:t,'purchase_order_draft','PENDING_APPROVAL',
            CAST(:p AS jsonb),:h,CAST(:e AS jsonb),CAST(:v AS jsonb),:tot,:c,:u,:r)"""),
            {"i": aid, "t": actor.tenant_id, "p": json.dumps(payload), "h": canonical_hash(payload),
             "e": json.dumps(evidence, default=str), "v": json.dumps(versions, default=str),
             "tot": payload["total_minor"], "c": currency, "u": actor.user_id, "r": agent_run_id})
        _audit(s, actor.tenant_id, actor.user_id, "action.prepared", aid,
               {"payload_hash": canonical_hash(payload), "total_minor": payload["total_minor"]})
    return get(actor, aid)


def get(actor: Actor, action_id) -> dict:
    actor.require("read")
    with tenant_session(actor.tenant_id) as s:
        a = _load(s, action_id)
        a["approvals"] = [dict(r) for r in s.execute(text(
            "SELECT id, decision, payload_hash, max_spend_minor, reason, approver_id, expires_at, created_at "
            "FROM approvals WHERE action_id = :i ORDER BY created_at"), {"i": action_id}).mappings()]
        a["outbox"] = s.execute(text("SELECT operation_id, status, attempts, last_error, external_ref, updated_at "
                                     "FROM outbox WHERE action_id = :i"), {"i": action_id}).mappings().first()
        a["outbox"] = dict(a["outbox"]) if a["outbox"] else None
    return a


def _recheck_terms(tenant_id, payload: dict) -> list[str]:
    """Re-resolve terms with current knowledge at the original decision date; report drift."""
    d = payload["decision"]
    res = applicable_terms(tenant_id, [l["sku_id"] for l in payload["lines"]],
                           datetime.now(UTC), date.fromisoformat(d["effective_date"]))
    current = {(t.supplier_id, t.sku_id): t for t in res.applicable}
    problems = []
    for l in payload["lines"]:
        t = current.get((payload["supplier_id"], l["sku_id"]))
        if t is None:
            problems.append(f"{l['sku_id']}: supplier no longer has an applicable term")
        elif t.term_id != l["term_id"] or t.unit_cost_minor != l["unit_cost_minor"]:
            problems.append(f"{l['sku_id']}: applicable term changed to {t.term_id}")
        elif l["quantity"] < t.moq or l["quantity"] % t.order_multiple:
            problems.append(f"{l['sku_id']}: quantity violates current MOQ/multiple")
    if res.conflicts:
        problems.append(f"conflicting active terms: {res.conflicts}")
    return problems


def approve(actor: Actor, action_id, *, payload_hash: str, expected_row_version: int,
            max_spend_minor: int | None = None) -> dict:
    actor.require("action.approve")
    with tenant_session(actor.tenant_id) as s:
        a = _load(s, action_id, lock=True)
        if a["row_version"] != expected_row_version:
            raise ActionError("version_conflict", "action changed since it was displayed; reload and review")
        if a["status"] != "PENDING_APPROVAL":
            raise ActionError("invalid_state", f"cannot approve an action in state {a['status']}")
        if a["prepared_by"] == actor.user_id:
            raise ActionError("separation_of_duties", "the preparer cannot approve their own action", 403)
        if payload_hash != a["payload_hash"] or canonical_hash(a["payload"]) != a["payload_hash"]:
            raise ActionError("payload_mismatch", "approval does not match the current payload")
        limit = max_spend_minor if max_spend_minor is not None else a["total_minor"]
        if a["total_minor"] > limit:
            raise ActionError("over_limit", "total exceeds the approved maximum spend")
        problems = _recheck_terms(actor.tenant_id, a["payload"])
        if problems:
            s.execute(text("UPDATE actions SET status='STALE', status_reason=:r, row_version=row_version+1, "
                           "updated_at=now() WHERE id=:i"), {"i": action_id, "r": "; ".join(problems)})
            _audit(s, actor.tenant_id, actor.user_id, "action.stale", action_id, {"problems": problems})
            out = {"status": "STALE", "problems": problems}
            record_outcome(s, 200, out)
            return out
        expires = datetime.now(UTC) + timedelta(minutes=settings.approval_ttl_minutes)
        s.execute(text("""INSERT INTO approvals (id, tenant_id, action_id, decision, payload_hash, versions,
            max_spend_minor, approver_id, expires_at) VALUES (:i,:t,:a,'APPROVED',:h,CAST(:v AS jsonb),:m,:u,:x)"""),
            {"i": uuid.uuid4(), "t": actor.tenant_id, "a": action_id, "h": a["payload_hash"],
             "v": json.dumps(a["versions"], default=str), "m": limit, "u": actor.user_id, "x": expires})
        op_id = f"po-{action_id}"
        # Outbox intent is written in the same transaction as the approval (no lost or phantom sends).
        s.execute(text("""INSERT INTO outbox (id, tenant_id, action_id, operation_id, payload, payload_hash, status)
            VALUES (:i,:t,:a,:o,CAST(:p AS jsonb),:h,'PENDING')"""),
            {"i": uuid.uuid4(), "t": actor.tenant_id, "a": action_id, "o": op_id, "p": json.dumps(a["payload"]),
             "h": a["payload_hash"]})
        s.execute(text("UPDATE actions SET status='QUEUED', row_version=row_version+1, updated_at=now() "
                       "WHERE id=:i"), {"i": action_id})
        _audit(s, actor.tenant_id, actor.user_id, "action.approved", action_id,
               {"payload_hash": a["payload_hash"], "expires_at": expires.isoformat(), "operation_id": op_id})
        out = {"status": "QUEUED", "operation_id": op_id}
        record_outcome(s, 200, out)
    return out


def reject(actor: Actor, action_id, *, reason: str, expected_row_version: int) -> dict:
    actor.require("action.reject")
    if not reason.strip():
        raise ActionError("reason_required", "a rejection reason is required", 422)
    with tenant_session(actor.tenant_id) as s:
        a = _load(s, action_id, lock=True)
        if a["row_version"] != expected_row_version:
            raise ActionError("version_conflict", "action changed since it was displayed")
        if a["status"] != "PENDING_APPROVAL":
            raise ActionError("invalid_state", f"cannot reject an action in state {a['status']}")
        s.execute(text("""INSERT INTO approvals (id, tenant_id, action_id, decision, payload_hash, versions,
            max_spend_minor, reason, approver_id, expires_at) VALUES (:i,:t,:a,'REJECTED',:h,'{}'::jsonb,0,:r,:u,now())"""),
            {"i": uuid.uuid4(), "t": actor.tenant_id, "a": action_id, "h": a["payload_hash"], "r": reason,
             "u": actor.user_id})
        s.execute(text("UPDATE actions SET status='REJECTED', status_reason=:r, row_version=row_version+1, "
                       "updated_at=now() WHERE id=:i"), {"i": action_id, "r": reason})
        _audit(s, actor.tenant_id, actor.user_id, "action.rejected", action_id, {"reason": reason})
        record_outcome(s, 200, {"status": "REJECTED"})
    return {"status": "REJECTED"}


def edit_quantities(actor: Actor, action_id, *, quantities: dict[str, int], expected_row_version: int,
                    budget_minor: int | None) -> dict:
    """Edit line quantities; revalidates and produces a new payload hash (old approvals become unusable).

    The spend limit is the budget the plan was made under (stored in the decision, audit F08); `budget_minor` is the
    fallback for drafts prepared before the decision carried its budget."""
    actor.require("action.edit")
    with tenant_session(actor.tenant_id) as s:
        a = _load(s, action_id, lock=True)
        if a["row_version"] != expected_row_version:
            raise ActionError("version_conflict", "action changed since it was displayed")
        if a["status"] not in ("PENDING_APPROVAL", "STALE"):
            raise ActionError("invalid_state", f"cannot edit an action in state {a['status']}")
        p = a["payload"]
        d = p["decision"]
        if d.get("budget_minor") is not None:
            budget_minor = int(d["budget_minor"])
        if budget_minor is None:
            raise ActionError("budget_unknown", "the draft carries no budget and the workspace has none", 422)
        res = applicable_terms(actor.tenant_id, [l["sku_id"] for l in p["lines"]],
                               datetime.fromisoformat(d["knowledge_cutoff"]), date.fromisoformat(d["effective_date"]))
        terms = {t.term_id: t for t in res.applicable}
        new_lines = []
        for l in p["lines"]:
            q = int(quantities.get(l["sku_id"], l["quantity"]))
            t = terms.get(l["term_id"])
            if t is None:
                raise ActionError("term_unavailable", f"{l['sku_id']}: term {l['term_id']} no longer applicable")
            new_lines.append(PlanLine(sku_id=l["sku_id"], supplier_id=p["supplier_id"], term_id=t.term_id,
                                      quantity=q, unit_cost_minor=t.unit_cost_minor, line_minor=q * t.unit_cost_minor,
                                      currency=p["currency"], arrival_date=date.fromisoformat(d["effective_date"])
                                      + timedelta(days=t.lead_time_days), document_version_id=t.document_version_id,
                                      section=t.section))
        req = PlanRequest(decision_date=date.fromisoformat(d["effective_date"]),
                          need_by=date.fromisoformat(p["need_by"]), currency=p["currency"], budget_minor=budget_minor,
                          needs=[Need(sku_id=l.sku_id, required_units=0) for l in new_lines],
                          offers=[terms[l.term_id] for l in new_lines])
        result = PlanResult(status="FEASIBLE", lines=new_lines, total_minor=sum(l.line_minor for l in new_lines),
                            currency=p["currency"], input_hash="edit", solver={})
        errors = validate(req, result)
        if errors:
            raise ActionError("validation_failed", "; ".join(errors), 422)
        payload = build_payload(p["supplier_id"], new_lines, p["currency"], date.fromisoformat(p["need_by"]), d)
        h = canonical_hash(payload)
        s.execute(text("""UPDATE actions SET payload=CAST(:p AS jsonb), payload_hash=:h, total_minor=:t,
            status='PENDING_APPROVAL', status_reason='edited; requires fresh approval', row_version=row_version+1,
            updated_at=now() WHERE id=:i"""), {"p": json.dumps(payload), "h": h, "t": payload["total_minor"],
                                              "i": action_id})
        _audit(s, actor.tenant_id, actor.user_id, "action.edited", action_id,
               {"old_hash": a["payload_hash"], "new_hash": h, "quantities": quantities})
        # replay summary if the process dies before the full response is stored; the route stores the full detail
        record_outcome(s, 200, {"id": str(action_id), "status": "PENDING_APPROVAL", "payload_hash": h,
                                "row_version": a["row_version"] + 1, "replay_summary": True})
    return get(actor, action_id)


# ---------------------------------------------------------------- dispatch (worker side)

def _claim(tenant_id, worker: str):
    with tenant_session(tenant_id) as s:
        row = s.execute(text("""
            SELECT id FROM outbox WHERE (status = 'PENDING' AND next_attempt_at <= now())
               OR (status = 'IN_FLIGHT' AND lease_expires_at < now())
            ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED""")).first()
        if not row:
            return None
        claimed = s.execute(text("""
            UPDATE outbox SET status='IN_FLIGHT', attempts=attempts+1, lease_owner=:w,
              lease_expires_at=now() + make_interval(secs => :l), fencing_token=fencing_token+1, updated_at=now()
            WHERE id=:i RETURNING id, action_id, operation_id, payload, payload_hash, attempts, fencing_token"""),
            {"i": row.id, "w": worker, "l": LEASE_SECONDS}).mappings().first()
        return dict(claimed)


def _finish(tenant_id, item, outbox_status, action_status, *, external_ref=None, error=None, reason=None,
            retry_in: int | None = None, keep_lease: bool = False, order: dict | None = None) -> bool:
    lease = "" if keep_lease else "lease_owner=NULL, lease_expires_at=NULL,"
    with tenant_session(tenant_id) as s:
        updated = s.execute(text(f"""
            UPDATE outbox SET status=:st, external_ref=COALESCE(:x, external_ref), last_error=:e, {lease}
              next_attempt_at=now() + make_interval(secs => :r), updated_at=now()
            WHERE id=:i AND fencing_token=:f RETURNING id"""),
            {"st": outbox_status, "x": external_ref, "e": error, "r": retry_in or 0, "i": item["id"],
             "f": item["fencing_token"]}).first()
        if not updated:
            return False  # lease was lost to another worker; its result wins
        s.execute(text("UPDATE actions SET status=:st, external_ref=COALESCE(:x, external_ref), "
                       "status_reason=:r, row_version=row_version+1, updated_at=now() WHERE id=:i"),
                  {"st": action_status, "x": external_ref, "r": reason, "i": item["action_id"]})
        _audit(s, tenant_id, None, f"dispatch.{action_status.lower()}", item["action_id"],
               {"operation_id": item["operation_id"], "external_ref": external_ref, "error": error})
        if action_status == "RECONCILED" and order is not None:
            _open_order_lines(s, tenant_id, item, order)
        supplier = s.execute(text("SELECT payload->>'supplier_id' FROM actions WHERE id=:i"),
                             {"i": item["action_id"]}).scalar()
    key = f"failed_reconciliation:{item['action_id']}"
    mismatch = action_status == "CONFIRMED"
    if action_status in ("UNKNOWN_OUTCOME", "FAILED") or mismatch:
        what = {"UNKNOWN_OUTCOME": "Order outcome unknown", "FAILED": "Dispatch failed",
                "CONFIRMED": "Read-back mismatch"}[action_status]
        alerts.raise_alert(tenant_id, "failed_reconciliation", key, f"{what} for order to {supplier}",
                           {"action_id": str(item["action_id"]), "status": action_status, "reason": reason or error,
                            "operation_id": item["operation_id"]}, "high")
    elif action_status == "RECONCILED":
        alerts.resolve_alert(tenant_id, key)
    return True


def _approval_valid(tenant_id, item) -> str | None:
    with tenant_session(tenant_id) as s:
        a = s.execute(text("SELECT status, payload_hash FROM actions WHERE id=:i"), {"i": item["action_id"]}).first()
        ap = s.execute(text("""SELECT expires_at FROM approvals WHERE action_id=:i AND decision='APPROVED'
            AND payload_hash=:h ORDER BY created_at DESC LIMIT 1"""),
            {"i": item["action_id"], "h": item["payload_hash"]}).first()
    if a.payload_hash != item["payload_hash"]:
        return "payload changed after approval"
    if ap is None:
        return "no approval bound to this payload"
    if ap.expires_at < datetime.now(UTC):
        return "approval expired"
    return None


def _fresh_send_problems(tenant_id, item) -> list[str]:
    """Everything a first send relies on, re-read now (audit S11). Empty list = safe to send."""
    problem = _approval_valid(tenant_id, item)
    if problem:
        return [problem]
    with tenant_session(tenant_id) as s:
        a = s.execute(text("SELECT status, payload, total_minor FROM actions WHERE id=:i"),
                      {"i": item["action_id"]}).mappings().first()
        ap = s.execute(text("""SELECT approver_id, max_spend_minor FROM approvals WHERE action_id=:i
            AND decision='APPROVED' AND payload_hash=:h ORDER BY created_at DESC LIMIT 1"""),
            {"i": item["action_id"], "h": item["payload_hash"]}).mappings().first()
    problems = []
    if a["status"] not in ("QUEUED", "SUBMITTED"):
        problems.append(f"action is {a['status']}, not queued")
    approver = resolve_actor(ap["approver_id"], tenant_id)
    if approver is None or "action.approve" not in MATRIX.get(approver.role, set()):
        problems.append("the approver no longer holds approval rights in this workspace")
    if a["total_minor"] > ap["max_spend_minor"]:
        problems.append("total exceeds the approved maximum spend")
    problems += _recheck_terms(tenant_id, a["payload"])
    return problems


def _norm_line(line: dict) -> tuple:
    return (line.get("sku_id"), int(line.get("quantity", 0)), line.get("unit", "unit"),
            int(line.get("unit_cost_minor", -1)), int(line.get("line_minor", -1)))


def verify(tenant_id, item, order: dict) -> list[str]:
    """Compare the order the target returned with the approved payload (audit F06). Every difference is listed."""
    p = item["payload"]
    mismatches = []
    if order["supplier_id"] != p["supplier_id"]:
        mismatches.append("supplier differs")
    if order["currency"].strip() != p["currency"]:
        mismatches.append("currency differs")
    if order["total_minor"] != p["total_minor"]:
        mismatches.append(f"total {order['total_minor']} differs from approved {p['total_minor']}")
    if (order.get("status") or "OPEN") not in ("OPEN", "CONFIRMED"):
        mismatches.append(f"external order status is {order.get('status')}")
    need_by = order.get("need_by")
    if need_by is not None and str(need_by) != p["need_by"]:
        mismatches.append(f"need-by {need_by} differs from approved {p['need_by']}")
    want, got = Counter(_norm_line(x) for x in p["lines"]), Counter(_norm_line(x) for x in order["lines"])
    if want != got:
        missing, extra = want - got, got - want
        detail = []
        for sku, qty, unit, price, value in sorted(missing.elements(), key=str):
            detail.append(f"approved {sku} x{qty} {unit} @ {price} (line {value}) not returned")
        for sku, qty, unit, price, value in sorted(extra.elements(), key=str):
            detail.append(f"returned {sku} x{qty} {unit} @ {price} (line {value}) not approved")
        mismatches.append("lines differ: " + "; ".join(detail))
    return mismatches


def _open_order_lines(s, tenant_id, item, order: dict) -> None:
    """Record a reconciled order's lines as open supply, once per action and SKU (audit S12)."""
    p = item["payload"]
    ordered_on = p["decision"]["effective_date"]
    for line in p["lines"]:
        s.execute(text("""INSERT INTO purchase_order_lines (id, tenant_id, action_id, operation_id, external_ref,
            supplier_id, sku_id, ordered_units, ordered_on, expected_on) VALUES (:i,:t,:a,:o,:x,:s,:k,:q,:d,:e)
            ON CONFLICT (tenant_id, action_id, sku_id) DO NOTHING"""),
            {"i": uuid.uuid4(), "t": tenant_id, "a": item["action_id"], "o": item["operation_id"],
             "x": order["po_number"], "s": p["supplier_id"], "k": line["sku_id"], "q": line["quantity"],
             "d": ordered_on, "e": p["need_by"]})


def dispatch_once(tenant_id, worker: str | None = None) -> dict | None:
    """Claim and process one outbox item for the tenant. Returns a summary or None if idle."""
    worker = worker or f"{socket.gethostname()}:{uuid.uuid4().hex[:6]}"
    item = _claim(tenant_id, worker)
    if item is None:
        return None
    with telemetry.span("outbox.dispatch", **{"tenant.id": str(tenant_id), "outbox.operation_id": item["operation_id"],
                                              "outbox.attempt": item["attempts"]}) as sp:
        result = _dispatch(tenant_id, item)
        sp.set_attribute("outbox.result", result["result"])
    return result


def _dispatch(tenant_id, item) -> dict:
    key = item["operation_id"]
    if item["attempts"] > 1:
        # A previous attempt may have reached the target: look before anything else (audit F07). An order that exists
        # is verified and reconciled even if the approval has expired since; it is never sent again.
        found = sandbox_erp.lookup(key)
        if found:
            return _confirm(tenant_id, item, found)
    problems = _fresh_send_problems(tenant_id, item)
    if problems:
        reason = "; ".join(problems)
        _finish(tenant_id, item, "FAILED", "STALE", error=reason, reason=reason + " (review again before sending)")
        return {"operation_id": key, "result": "STALE", "reason": reason}
    try:
        resp = sandbox_erp.execute(key, str(item["action_id"]), item["payload"])
    except sandbox_erp.AdapterTimeout as e:
        _finish(tenant_id, item, "UNKNOWN_OUTCOME", "UNKNOWN_OUTCOME", error=str(e),
                reason="submission outcome unknown; reconcile before any retry")
        return {"operation_id": key, "result": "UNKNOWN_OUTCOME"}
    except sandbox_erp.AdapterError as e:
        if item["attempts"] >= 5:
            _finish(tenant_id, item, "FAILED", "FAILED", error=str(e), reason="retries exhausted")
            return {"operation_id": key, "result": "FAILED"}
        backoff = min(300, 2 ** item["attempts"])
        _finish(tenant_id, item, "PENDING", "QUEUED", error=str(e), reason="retry scheduled", retry_in=backoff)
        return {"operation_id": key, "result": "RETRY", "retry_in_s": backoff}
    # Keep the lease: if this worker dies now, lease expiry triggers a lookup-first retry.
    _finish(tenant_id, item, "IN_FLIGHT", "SUBMITTED", external_ref=resp["po_number"], keep_lease=True)
    found = sandbox_erp.lookup(key)
    return _confirm(tenant_id, item, found)


def _confirm(tenant_id, item, order: dict | None) -> dict:
    if order is None:
        _finish(tenant_id, item, "UNKNOWN_OUTCOME", "UNKNOWN_OUTCOME", error="order not found on read-back")
        return {"operation_id": item["operation_id"], "result": "UNKNOWN_OUTCOME"}
    mismatches = verify(tenant_id, item, order)
    if mismatches:
        _finish(tenant_id, item, "DELIVERED", "CONFIRMED", external_ref=order["po_number"],
                reason="read-back mismatch: " + "; ".join(mismatches))
        return {"operation_id": item["operation_id"], "result": "MISMATCH", "mismatches": mismatches}
    _finish(tenant_id, item, "DELIVERED", "RECONCILED", external_ref=order["po_number"],
            reason="sandbox order read back and matched the approved payload line by line", order=order)
    return {"operation_id": item["operation_id"], "result": "RECONCILED", "po_number": order["po_number"]}


def retry_failed(actor: Actor, action_id) -> dict:
    """Re-queue a dispatch that failed after exhausting its retries (for example during a connector outage).

    Safe only while the approval is still valid and the target holds no order for the operation key; if the remote
    order exists the caller must reconcile instead. The idempotency key is unchanged, so the target deduplicates."""
    actor.require("action.reconcile")
    with tenant_session(actor.tenant_id) as s:
        a = _load(s, action_id, lock=True)
        item = s.execute(text("SELECT id, operation_id, payload_hash, status FROM outbox WHERE action_id=:i FOR UPDATE"),
                         {"i": action_id}).mappings().first()
        if a["status"] != "FAILED" or not item or item["status"] != "FAILED":
            raise ActionError("invalid_state", "only a FAILED dispatch can be retried")
        problem = _approval_valid(actor.tenant_id, {"action_id": action_id, "payload_hash": item["payload_hash"]})
        if problem:
            raise ActionError("approval_invalid", f"cannot retry: {problem}; prepare and approve a new draft")
        if sandbox_erp.lookup(item["operation_id"]):
            raise ActionError("remote_order_exists", "the target already holds this order: reconcile it instead")
        s.execute(text("""UPDATE outbox SET status='PENDING', attempts=0, next_attempt_at=now(), last_error=NULL,
            lease_owner=NULL, lease_expires_at=NULL, updated_at=now() WHERE id=:i"""), {"i": item["id"]})
        s.execute(text("UPDATE actions SET status='QUEUED', status_reason='retry requested after failure', "
                       "row_version=row_version+1, updated_at=now() WHERE id=:i"), {"i": action_id})
        _audit(s, actor.tenant_id, actor.user_id, "action.retry_requested", action_id,
               {"operation_id": item["operation_id"]})
    return {"status": "QUEUED", "operation_id": item["operation_id"]}


def reconcile(actor: Actor, action_id) -> dict:
    """Resolve UNKNOWN_OUTCOME by looking the operation up. Never resends while unknown."""
    actor.require("action.reconcile")
    with tenant_session(actor.tenant_id) as s:
        item = s.execute(text("SELECT id, action_id, operation_id, payload, payload_hash, attempts, fencing_token, "
                              "status FROM outbox WHERE action_id=:i FOR UPDATE"), {"i": action_id}).mappings().first()
        if not item or item["status"] != "UNKNOWN_OUTCOME":
            raise ActionError("invalid_state", "only an UNKNOWN_OUTCOME operation can be reconciled")
        item = dict(item)
    order = sandbox_erp.lookup(item["operation_id"])
    if order:
        return _confirm(actor.tenant_id, item, order)
    # Not found: the sandbox deduplicates on the key, so re-queueing is safe for this adapter.
    _finish(actor.tenant_id, item, "PENDING", "QUEUED", reason="not found in sandbox; safe re-queue (idempotent key)")
    return {"operation_id": item["operation_id"], "result": "REQUEUED"}


# ---------------------------------------------------------------- receipts and cancellations (open-order ledger)

def record_receipt(actor: Actor, action_id, *, sku_id: str, quantity: int, received_on: date, key: str) -> dict:
    """Book units received against a reconciled order line. One receipt per idempotency key; never more than open."""
    actor.require("action.reconcile")
    if quantity <= 0:
        raise ActionError("invalid_quantity", "received quantity must be positive", 422)
    with tenant_session(actor.tenant_id) as s:
        dup = s.execute(text("SELECT po_line_id, quantity FROM receipts WHERE idempotency_key=:k"), {"k": key}).first()
        if dup:
            return {"status": "DUPLICATE", "po_line_id": str(dup.po_line_id), "quantity": dup.quantity}
        line = s.execute(text("""SELECT id, ordered_units, received_units, cancelled_units, status, ordered_on
            FROM purchase_order_lines WHERE action_id=:a AND sku_id=:k FOR UPDATE"""),
            {"a": action_id, "k": sku_id}).mappings().first()
        if line is None:
            raise ActionError("not_open", "no reconciled order line for this SKU on this action", 404)
        open_units = line["ordered_units"] - line["received_units"] - line["cancelled_units"]
        if quantity > open_units:
            raise ActionError("over_receipt", f"only {open_units} unit(s) are open on this line", 422)
        if received_on < line["ordered_on"]:
            raise ActionError("invalid_date", "a receipt cannot predate its order", 422)
        s.execute(text("""INSERT INTO receipts (id, tenant_id, po_line_id, sku_id, quantity, received_on, idempotency_key,
            created_by) VALUES (:i,:t,:l,:k,:q,:d,:key,:u)"""),
            {"i": uuid.uuid4(), "t": actor.tenant_id, "l": line["id"], "k": sku_id, "q": quantity, "d": received_on,
             "key": key, "u": actor.user_id})
        received = line["received_units"] + quantity
        status = "RECEIVED" if received + line["cancelled_units"] == line["ordered_units"] else "PARTIAL"
        s.execute(text("UPDATE purchase_order_lines SET received_units=:r, status=:s, updated_at=now() WHERE id=:i"),
                  {"r": received, "s": status, "i": line["id"]})
        _audit(s, actor.tenant_id, actor.user_id, "order.received", action_id,
               {"sku_id": sku_id, "quantity": quantity, "received_on": received_on.isoformat()})
    return {"status": status, "po_line_id": str(line["id"]), "received_units": received,
            "open_units": open_units - quantity}


def cancel_open_units(actor: Actor, action_id, *, sku_id: str, reason: str) -> dict:
    """Release the still-open units of a reconciled line (the supplier cancelled or short-shipped)."""
    actor.require("action.reconcile")
    if not reason.strip():
        raise ActionError("reason_required", "a cancellation reason is required", 422)
    with tenant_session(actor.tenant_id) as s:
        line = s.execute(text("""SELECT id, ordered_units, received_units, cancelled_units FROM purchase_order_lines
            WHERE action_id=:a AND sku_id=:k FOR UPDATE"""), {"a": action_id, "k": sku_id}).mappings().first()
        if line is None:
            raise ActionError("not_open", "no reconciled order line for this SKU on this action", 404)
        released = line["ordered_units"] - line["received_units"] - line["cancelled_units"]
        if released <= 0:
            raise ActionError("nothing_open", "no open units remain on this line")
        s.execute(text("""UPDATE purchase_order_lines SET cancelled_units = cancelled_units + :c,
            status = CASE WHEN received_units = 0 THEN 'CANCELLED' ELSE 'RECEIVED' END, updated_at=now() WHERE id=:i"""),
            {"c": released, "i": line["id"]})
        _audit(s, actor.tenant_id, actor.user_id, "order.cancelled_open_units", action_id,
               {"sku_id": sku_id, "units": released, "reason": reason})
    return {"status": "CANCELLED", "released_units": released}


def open_orders(actor: Actor) -> list[dict]:
    actor.require("read")
    with tenant_session(actor.tenant_id) as s:
        rows = s.execute(text("""SELECT l.action_id, l.external_ref, l.supplier_id, l.sku_id, l.ordered_units,
            l.received_units, l.cancelled_units, l.ordered_units - l.received_units - l.cancelled_units AS open_units,
            l.status, l.ordered_on, l.expected_on FROM purchase_order_lines l
            ORDER BY l.ordered_on DESC, l.sku_id LIMIT 200""")).mappings().all()
    return [dict(r) for r in rows]
