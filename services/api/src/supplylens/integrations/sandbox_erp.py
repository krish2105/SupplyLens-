"""Deterministic sandbox purchasing system ("another system"), with fault injection.

Contract: execute() is idempotent on the caller's idempotency key - a repeated key
returns the original purchase order. `timeout_after_commit` commits the order and then
raises AdapterTimeout, reproducing the "unknown outcome" case for reconciliation tests.

Read-back faults make the simulator store an order that differs from the request, the way a real ERP may transform or
reject parts of an order: `alter_line_price` (first line's unit price +1, stated total unchanged), `duplicate_line`
(first line repeated, stated total unchanged), `change_unit`, `change_need_by` (+7 days) and `cancel_after_commit`.
They exist to prove that read-back verification compares the whole order, not just its total.
"""
from __future__ import annotations

import copy
import json
from datetime import date, timedelta

from sqlalchemy import text

from ..db import app_engine


class AdapterError(Exception):
    retryable = True


class AdapterTimeout(AdapterError):
    """The request may or may not have been applied."""


CAPABILITIES = {
    "adapter": "sandbox_erp", "version": "1.0", "status": "VERIFIED_LOCALLY",
    "operations": ["create_purchase_order", "lookup_by_idempotency_key"],
    "idempotency": "native, keyed by caller idempotency key",
    "note": "Local simulator. Not a connection to any real ERP.",
}


def health() -> dict:
    with app_engine().connect() as c:
        c.execute(text("SELECT 1 FROM sandbox_erp.purchase_orders LIMIT 1"))
    return {"status": "VERIFIED_LOCALLY", **CAPABILITIES}


def inject_fault(idempotency_key: str, mode: str) -> None:
    with app_engine().begin() as c:
        c.execute(text("INSERT INTO sandbox_erp.fault_injection VALUES (:k, :m) ON CONFLICT (idempotency_key) "
                       "DO UPDATE SET mode = EXCLUDED.mode"), {"k": idempotency_key, "m": mode})


def _take_fault(c, key: str) -> str | None:
    return c.execute(text("DELETE FROM sandbox_erp.fault_injection WHERE idempotency_key = :k RETURNING mode"),
                     {"k": key}).scalar()


def execute(idempotency_key: str, caller_ref: str, payload: dict) -> dict:
    with app_engine().begin() as c:  # consume an injected fault in its own committed transaction
        fault = _take_fault(c, idempotency_key)
    with app_engine().begin() as c:
        if fault == "fail_before_commit":
            raise AdapterError("sandbox rejected the request before commit (injected)")
        existing = c.execute(text("SELECT po_number, status FROM sandbox_erp.purchase_orders "
                                  "WHERE idempotency_key = :k"), {"k": idempotency_key}).first()
        if existing:
            return {"po_number": existing.po_number, "status": existing.status, "duplicate": True}
        po = "SBX-PO-" + str(c.execute(text("SELECT nextval('sandbox_erp.po_seq')")).scalar())
        lines, need_by, status = _stored_form(payload, fault)
        c.execute(text("INSERT INTO sandbox_erp.purchase_orders (po_number, idempotency_key, caller_ref, "
                       "supplier_id, lines, total_minor, currency, need_by, status) "
                       "VALUES (:p,:k,:r,:s,CAST(:l AS jsonb),:t,:c,:n,:st)"),
                  {"p": po, "k": idempotency_key, "r": caller_ref, "s": payload["supplier_id"],
                   "l": json.dumps(lines), "t": payload["total_minor"], "c": payload["currency"], "n": need_by,
                   "st": status})
    if fault == "timeout_after_commit":
        raise AdapterTimeout("no response from sandbox after submit (injected)")
    return {"po_number": po, "status": "OPEN", "duplicate": False}


def _stored_form(payload: dict, fault: str | None) -> tuple[list[dict], date | None, str]:
    lines = copy.deepcopy(payload["lines"])
    need_by = date.fromisoformat(payload["need_by"]) if payload.get("need_by") else None
    status = "OPEN"
    if fault == "alter_line_price" and lines:
        lines[0]["unit_cost_minor"] += 1
        lines[0]["line_minor"] = lines[0]["unit_cost_minor"] * lines[0]["quantity"]
    elif fault == "duplicate_line" and lines:
        lines.append(copy.deepcopy(lines[0]))
    elif fault == "change_unit" and lines:
        lines[0]["unit"] = "case"
    elif fault == "change_need_by" and need_by:
        need_by += timedelta(days=7)
    elif fault == "cancel_after_commit":
        status = "CANCELLED"
    return lines, need_by, status


def lookup(idempotency_key: str) -> dict | None:
    with app_engine().connect() as c:
        r = c.execute(text("SELECT po_number, supplier_id, lines, total_minor, currency, status, need_by, created_at "
                           "FROM sandbox_erp.purchase_orders WHERE idempotency_key = :k"),
                      {"k": idempotency_key}).mappings().first()
    return dict(r) if r else None


def count_for_key(idempotency_key: str) -> int:
    with app_engine().connect() as c:
        return c.execute(text("SELECT count(*) FROM sandbox_erp.purchase_orders WHERE idempotency_key = :k"),
                         {"k": idempotency_key}).scalar()
