"""Synchronise placed orders with the purchasing system (Phase 6). The worker runs `sync_tenant` every SYNC_EVERY_S.

1. Order status. An order the target cancelled or rejected after we reconciled it releases its open units in the ledger
   (planning then sees the supply gone) and opens an alert. An order the target holds while SupplyLens records the action
   as FAILED, STALE or awaiting approval is drift: alert only, a person decides (nothing is changed automatically).
2. Receipts. The target's goods-receipt feed is read from a cursor and each receipt booked once (key `erp:<receipt_id>`).
   A receipt that cannot be booked (more than is open, unknown line, ...) opens an alert with the receipt's details. A
   receipt for an order not yet reconciled here holds the cursor so it is booked once reconciliation completes.
3. Overdue receipts. An open line past its expected date plus OVERDUE_GRACE_DAYS opens an alert per order; the
   business date is the workspace's operational date (D-045), falling back to today.
Nothing here sends or changes an order in the purchasing system.
"""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import text

from .. import alerts
from ..actions import service as actions
from ..db import tenant_session
from . import connector, schema
from .contract import CLOSED_STATUSES, AdapterAuthError, AdapterUnavailable
from .registry import adapter

log = logging.getLogger("supplylens.sync")
SYNC_EVERY_S = 60
OVERDUE_GRACE_DAYS = 2
MAX_ORDERS = 2000
DRIFT_STATES = ("FAILED", "STALE", "PENDING_APPROVAL", "REJECTED")
WAITING_STATES = ("QUEUED", "SUBMITTED", "UNKNOWN_OUTCOME", "CONFIRMED")


def sync_tenant(tenant_id) -> dict:
    if not schema.has_0011():
        return {"skipped": "database not migrated to 0011"}
    allowed, why = connector.may_dispatch(tenant_id)
    if not allowed:
        return {"skipped": why}
    with tenant_session(tenant_id) as s:
        local = {str(r.id): r for r in s.execute(text("""SELECT a.id, a.status, a.payload->>'supplier_id' AS supplier
            FROM actions a JOIN outbox o ON o.action_id = a.id ORDER BY a.created_at DESC LIMIT :n"""), {"n": MAX_ORDERS})}
        cursor = s.execute(text("SELECT receipts_cursor FROM erp_connector_state")).scalar() or 0
    if not local:
        out = {"orders": 0, "receipts": 0}
        out["overdue"] = overdue(tenant_id)
        return out
    try:
        target = adapter()
        orders = target.orders_for(list(local))
        receipts = target.receipts_since(list(local), cursor, 500)
    except (AdapterUnavailable, AdapterAuthError) as e:
        connector.record_failure(tenant_id, e)
        return {"error": str(e)}
    connector.record_success(tenant_id)
    out = {"orders": len(orders), **_orders(tenant_id, local, orders), **_receipts(tenant_id, local, receipts, cursor)}
    out["overdue"] = overdue(tenant_id)
    return out


def _orders(tenant_id, local: dict, orders: list[dict]) -> dict:
    released, drift = 0, set()
    for o in orders:
        a = local.get(o["caller_ref"])
        if a is None:
            continue
        if a.status == "RECONCILED" and o["status"] in CLOSED_STATUSES:
            with tenant_session(tenant_id) as s:
                still_open = s.execute(text("SELECT coalesce(sum(ordered_units - received_units - cancelled_units), 0) "
                                            "FROM purchase_order_lines WHERE action_id = :a"), {"a": a.id}).scalar()
                if not still_open:
                    continue
                units = actions.release_open_units(s, tenant_id, a.id, event="order.closed_by_target",
                                                   reason=f"{o['status'].lower()} in the purchasing system")
            released += units
            alerts.raise_alert(tenant_id, "erp_sync", f"erp_sync:closed:{a.id}",
                               f"Order {o['po_number']} to {a.supplier} was {o['status'].lower()} in the purchasing system",
                               {"action_id": str(a.id), "po_number": o["po_number"], "released_units": units,
                                "action": "the open units were released; re-plan if the need remains"}, "high")
        elif a.status in DRIFT_STATES and o["status"] not in CLOSED_STATUSES:
            key = f"erp_sync:drift:{a.id}"
            drift.add(key)
            alerts.raise_alert(tenant_id, "erp_sync", key,
                               f"Purchasing system holds order {o['po_number']} that SupplyLens records as {a.status}",
                               {"action_id": str(a.id), "po_number": o["po_number"], "local_status": a.status,
                                "target_status": o["status"],
                                "action": "check the order in the purchasing system; cancel it there or record it here"},
                               "high")
    with tenant_session(tenant_id) as s:
        alerts._resolve_missing(s, "erp_sync:drift", drift)
        s.execute(text("UPDATE erp_connector_state SET last_order_sync_at = now() WHERE tenant_id = :t"), {"t": tenant_id})
    return {"released_units": released, "drift": len(drift)}


def _receipts(tenant_id, local: dict, receipts: list[dict], cursor: int) -> dict:
    booked = held = exceptions = 0
    hold_at: int | None = None
    for r in receipts:
        a = local.get(r["caller_ref"])
        try:
            with tenant_session(tenant_id) as s:
                res = actions.book_receipt(s, tenant_id, a.id, sku_id=r["sku_id"], quantity=int(r["quantity"]),
                                           received_on=_as_date(r["received_on"]), key=f"erp:{r['receipt_id']}",
                                           location_id=r.get("location_id"), source="erp")
            booked += res["status"] != "DUPLICATE"
        except actions.ActionError as e:
            if e.code == "not_open" and a.status in WAITING_STATES:
                held += 1                     # booked once the order is reconciled here
                hold_at = r["sequence"] if hold_at is None else hold_at
                continue
            exceptions += 1
            alerts.raise_alert(tenant_id, "erp_sync", f"erp_sync:receipt:{r['receipt_id']}",
                               f"Receipt {r['receipt_id']} for order {r['po_number']} could not be booked",
                               {"receipt": {k: str(v) for k, v in r.items()}, "error": str(e), "code": e.code,
                                "action": "check the receipt in the purchasing system; book or cancel units by hand"},
                               "high")
    # held receipts keep the cursor just before the first of them; the ones after it are re-read and skip as duplicates
    new_cursor = hold_at - 1 if hold_at is not None else (receipts[-1]["sequence"] if receipts else cursor)
    with tenant_session(tenant_id) as s:
        s.execute(text("UPDATE erp_connector_state SET receipts_cursor = :c, last_receipt_sync_at = now() "
                       "WHERE tenant_id = :t"), {"c": new_cursor, "t": tenant_id})
    return {"receipts": len(receipts), "receipts_booked": booked, "receipts_held": held,
            "receipt_exceptions": exceptions}


def _as_date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def overdue(tenant_id) -> int:
    keys: set[str] = set()
    with tenant_session(tenant_id) as s:
        rows = s.execute(text("""
            WITH today AS (SELECT coalesce((SELECT operational_as_of::date FROM tenant_settings), current_date) AS d)
            SELECT l.action_id, l.external_ref, l.supplier_id, min(l.expected_on) AS expected_on,
                   sum(l.ordered_units - l.received_units - l.cancelled_units) AS open_units, (SELECT d FROM today) AS today
            FROM purchase_order_lines l
            WHERE l.status IN ('OPEN', 'PARTIAL') AND l.expected_on IS NOT NULL
              AND l.expected_on + :g < (SELECT d FROM today)
            GROUP BY l.action_id, l.external_ref, l.supplier_id"""), {"g": OVERDUE_GRACE_DAYS}).mappings().all()
    for r in rows:
        key = f"overdue_receipt:{r['action_id']}"
        keys.add(key)
        days = (r["today"] - r["expected_on"]).days
        alerts.raise_alert(tenant_id, "overdue_receipt", key,
                           f"Order {r['external_ref']} from {r['supplier_id']} is {days} days overdue",
                           {"action_id": str(r["action_id"]), "po_number": r["external_ref"],
                            "expected_on": r["expected_on"], "open_units": r["open_units"], "days_overdue": days,
                            "action": "chase the supplier; book the receipt when it arrives or cancel the open units"},
                           "medium")
    with tenant_session(tenant_id) as s:
        alerts._resolve_missing(s, "overdue_receipt", keys)
    return len(keys)
