"""Deterministic sandbox purchasing system ("another system"), with fault injection.

Implements the adapter contract (integrations/contract.py). It is a local simulator in the same database, outside tenant
row-level security: not a connection to any real ERP, and never presented as one.

Contract: submission is idempotent on the caller's idempotency key - a repeated key returns the original purchase order.
`timeout_after_commit` commits the order and then raises AdapterTimeout, reproducing the "unknown outcome" case for
reconciliation tests; `fail_before_commit` raises a transient AdapterError; `reject` raises AdapterRejected (a business
refusal, nothing created).

Read-back faults make the simulator store an order that differs from the request, the way a real ERP may transform or
reject parts of an order: `alter_line_price` (first line's unit price +1, stated total unchanged), `duplicate_line`
(first line repeated, stated total unchanged), `change_unit`, `change_need_by` (+7 days) and `cancel_after_commit`.
They exist to prove that read-back verification compares the whole order, not just its total.

Connector-wide faults (migration 0011): `set_connector(available=False)` makes every call raise AdapterUnavailable (an
outage), `set_connector(credentials_valid=False)` makes every call raise AdapterAuthError (expired credentials).
`post_receipt` and `cancel_by_supplier` play the warehouse and the supplier: they change the target's records the way
the real world would, for the synchronisation tests and drills.
"""
from __future__ import annotations

import copy
import json
from datetime import date, timedelta

from sqlalchemy import text

from ..db import app_engine
from . import schema
from .contract import (
    AdapterAuthError,
    AdapterError,
    AdapterRejected,
    AdapterTimeout,
    AdapterUnavailable,
)

__all__ = ["AdapterError", "AdapterTimeout", "AdapterRejected", "AdapterUnavailable", "AdapterAuthError", "ADAPTER"]

CAPABILITIES = {
    "adapter": "sandbox_erp", "version": "2.0", "status": "VERIFIED_LOCALLY",
    "operations": ["create_purchase_order", "lookup_by_idempotency_key", "orders_for_caller_refs",
                   "cancel_purchase_order", "receipts_feed", "health"],
    "idempotency": "native, keyed by caller idempotency key",
    "authentication": "none (local simulator); expired credentials are simulated by a switch",
    "note": "Local simulator. Not a connection to any real ERP.",
}


def _gate(c) -> None:
    """Connector-wide faults, checked on every call the way a real endpoint fails before doing anything."""
    if not schema.has_0011():
        return
    row = c.execute(text("SELECT available, credentials_valid FROM sandbox_erp.connector WHERE id = 1")).first()
    if row is None:
        return
    if not row.available:
        raise AdapterUnavailable("sandbox ERP unavailable (simulated outage)")
    if not row.credentials_valid:
        raise AdapterAuthError("sandbox ERP refused the credentials (simulated expiry)")


def health() -> dict:
    with app_engine().connect() as c:
        _gate(c)
        c.execute(text("SELECT 1 FROM sandbox_erp.purchase_orders LIMIT 1"))
    return {"status": "VERIFIED_LOCALLY", **CAPABILITIES}


def set_connector(*, available: bool | None = None, credentials_valid: bool | None = None) -> None:
    with app_engine().begin() as c:
        if available is not None:
            c.execute(text("UPDATE sandbox_erp.connector SET available = :a WHERE id = 1"), {"a": available})
        if credentials_valid is not None:
            c.execute(text("UPDATE sandbox_erp.connector SET credentials_valid = :v WHERE id = 1"), {"v": credentials_valid})


def inject_fault(idempotency_key: str, mode: str) -> None:
    with app_engine().begin() as c:
        c.execute(text("INSERT INTO sandbox_erp.fault_injection VALUES (:k, :m) ON CONFLICT (idempotency_key) "
                       "DO UPDATE SET mode = EXCLUDED.mode"), {"k": idempotency_key, "m": mode})


def _take_fault(c, key: str) -> str | None:
    return c.execute(text("DELETE FROM sandbox_erp.fault_injection WHERE idempotency_key = :k RETURNING mode"),
                     {"k": key}).scalar()


def execute(idempotency_key: str, caller_ref: str, payload: dict) -> dict:
    with app_engine().connect() as c:
        _gate(c)
    with app_engine().begin() as c:  # consume an injected fault in its own committed transaction
        fault = _take_fault(c, idempotency_key)
    with app_engine().begin() as c:
        if fault == "fail_before_commit":
            raise AdapterError("sandbox rejected the request before commit (injected)")
        if fault == "reject":
            raise AdapterRejected("sandbox refused the order: supplier blocked for purchasing (injected)")
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
        _gate(c)
        r = c.execute(text("SELECT po_number, supplier_id, lines, total_minor, currency, status, need_by, created_at "
                           "FROM sandbox_erp.purchase_orders WHERE idempotency_key = :k"),
                      {"k": idempotency_key}).mappings().first()
    return dict(r) if r else None


def orders_for(caller_refs: list[str]) -> list[dict]:
    with app_engine().connect() as c:
        _gate(c)
        rows = c.execute(text("SELECT po_number, idempotency_key, caller_ref, supplier_id, lines, total_minor, currency, "
                              "status, need_by, created_at FROM sandbox_erp.purchase_orders WHERE caller_ref = ANY(:r) "
                              "ORDER BY created_at"), {"r": list(caller_refs)}).mappings().all()
    return [dict(r) for r in rows]


def cancel(idempotency_key: str, reason: str) -> dict:
    """Cancel an order on request of the buyer. Refused once every line has been received."""
    with app_engine().begin() as c:
        _gate(c)
        o = c.execute(text("SELECT po_number, status, lines FROM sandbox_erp.purchase_orders WHERE idempotency_key = :k "
                           "FOR UPDATE"), {"k": idempotency_key}).mappings().first()
        if o is None:
            raise AdapterRejected("no order with this key")
        if o["status"] in ("CANCELLED", "REJECTED"):
            return {"po_number": o["po_number"], "status": o["status"], "duplicate": True}
        if o["status"] == "RECEIVED":
            raise AdapterRejected("every line has been received; the order can no longer be cancelled")
        c.execute(text("UPDATE sandbox_erp.purchase_orders SET status = 'CANCELLED', status_reason = :r, updated_at = now() "
                       "WHERE po_number = :p"), {"p": o["po_number"], "r": reason})
    return {"po_number": o["po_number"], "status": "CANCELLED", "duplicate": False}


def cancel_by_supplier(po_number: str, reason: str = "supplier cancelled", status: str = "CANCELLED") -> None:
    """Simulator: the supplier cancels or rejects an order after it was accepted."""
    with app_engine().begin() as c:
        c.execute(text("UPDATE sandbox_erp.purchase_orders SET status = :s, status_reason = :r, updated_at = now() "
                       "WHERE po_number = :p"), {"p": po_number, "s": status, "r": reason})


def post_receipt(po_number: str, sku_id: str, quantity: int, received_on: date, location_id: str | None = None) -> dict:
    """Simulator: the warehouse books a goods receipt in the ERP. The ERP accepts over-deliveries, as real ones may."""
    with app_engine().begin() as c:
        seq = c.execute(text("SELECT nextval('sandbox_erp.receipts_seq_seq')")).scalar()
        rid = f"SBX-GR-{seq}"
        c.execute(text("INSERT INTO sandbox_erp.receipts (seq, receipt_id, po_number, sku_id, location_id, quantity, "
                       "received_on) VALUES (:s,:r,:p,:k,:l,:q,:d)"),
                  {"s": seq, "r": rid, "p": po_number, "k": sku_id, "l": location_id, "q": quantity, "d": received_on})
        o = c.execute(text("SELECT lines FROM sandbox_erp.purchase_orders WHERE po_number = :p"), {"p": po_number}).scalar()
        got = dict(c.execute(text("SELECT sku_id, sum(quantity) FROM sandbox_erp.receipts WHERE po_number = :p "
                                  "GROUP BY sku_id"), {"p": po_number}).all())
        ordered: dict[str, int] = {}
        for line in o:
            ordered[line["sku_id"]] = ordered.get(line["sku_id"], 0) + int(line["quantity"])
        if all(got.get(k, 0) >= q for k, q in ordered.items()):
            c.execute(text("UPDATE sandbox_erp.purchase_orders SET status = 'RECEIVED', updated_at = now() "
                           "WHERE po_number = :p AND status IN ('OPEN', 'CONFIRMED')"), {"p": po_number})
    return {"receipt_id": rid, "sequence": seq}


def receipts_since(caller_refs: list[str], after_sequence: int, limit: int = 200) -> list[dict]:
    with app_engine().connect() as c:
        _gate(c)
        rows = c.execute(text("""SELECT r.receipt_id, r.seq AS sequence, r.po_number, o.caller_ref, o.idempotency_key,
            r.sku_id, r.location_id, r.quantity, r.received_on FROM sandbox_erp.receipts r
            JOIN sandbox_erp.purchase_orders o ON o.po_number = r.po_number
            WHERE o.caller_ref = ANY(:refs) AND r.seq > :after ORDER BY r.seq LIMIT :n"""),
            {"refs": list(caller_refs), "after": after_sequence, "n": limit}).mappings().all()
    return [dict(r) for r in rows]


def count_for_key(idempotency_key: str) -> int:
    with app_engine().connect() as c:
        return c.execute(text("SELECT count(*) FROM sandbox_erp.purchase_orders WHERE idempotency_key = :k"),
                         {"k": idempotency_key}).scalar()


class SandboxErpAdapter:
    """The simulator behind the adapter contract."""
    name = "sandbox_erp"

    def capabilities(self) -> dict:
        return dict(CAPABILITIES)

    def health(self) -> dict:
        return health()

    def submit_purchase_order(self, idempotency_key: str, caller_ref: str, payload: dict) -> dict:
        return execute(idempotency_key, caller_ref, payload)

    def lookup_purchase_order(self, idempotency_key: str) -> dict | None:
        return lookup(idempotency_key)

    def orders_for(self, caller_refs: list[str]) -> list[dict]:
        return orders_for(caller_refs)

    def cancel_purchase_order(self, idempotency_key: str, reason: str) -> dict:
        return cancel(idempotency_key, reason)

    def receipts_since(self, caller_refs: list[str], after_sequence: int, limit: int = 200) -> list[dict]:
        return receipts_since(caller_refs, after_sequence, limit)


ADAPTER = SandboxErpAdapter()
