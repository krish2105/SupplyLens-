"""Safeguards for the public demo profile (SUPPLYLENS_ENVIRONMENT=demo, D-050).

The demo's role accounts are shared by every visitor and need no password, so anything a visitor does is done for all
of them (audit P0-SEC-01). Two rules keep one visitor from breaking the demo for the next:

* Workspace administration is closed: memberships, new workspaces, imports, model promotion (admin.write), tenant
  export and tenant deletion are refused for every role. Reading, planning, approving and reconciling stay open,
  because they are the journey the demo exists to show.
* Orders placed by visitors do not pile up. Their open units become open supply (S12), so after one visitor orders the
  reference case, the next would see nothing to buy. Each demo sign-in releases the open units of order lines nobody
  has touched for RELEASE_AFTER, through the same audited cancellation a planner would record.
"""
from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import text

from .config import settings

DEMO_LOCKED_OPERATIONS = frozenset({"admin.write", "tenant.export", "tenant.delete"})
RELEASE_AFTER = timedelta(hours=1)


def operation_locked(operation: str) -> bool:
    return settings.environment == "demo" and operation in DEMO_LOCKED_OPERATIONS


def release_stale_orders(release_after: timedelta = RELEASE_AFTER) -> int:
    """Release the open units of order lines untouched for `release_after`, in every workspace. Returns lines released."""
    from .db import tenant_session
    from .jobs import tenants

    released = 0
    for t in tenants():
        with tenant_session(t) as s:
            rows = s.execute(text("""
                UPDATE purchase_order_lines
                   SET cancelled_units = ordered_units - received_units,
                       status = CASE WHEN received_units = 0 THEN 'CANCELLED' ELSE 'RECEIVED' END, updated_at = now()
                 WHERE status IN ('OPEN', 'PARTIAL') AND ordered_units - received_units - cancelled_units > 0
                   AND updated_at < now() - make_interval(secs => :age)
             RETURNING action_id, sku_id, location_id, cancelled_units"""),
                {"age": release_after.total_seconds()}).mappings().all()
            reason = f"public demo housekeeping: visitor order released after {int(release_after.total_seconds() // 60)} minutes"
            for r in rows:
                s.execute(text("INSERT INTO audit_events (tenant_id, actor_id, action, entity, entity_id, detail) "
                               "VALUES (:t, NULL, 'order.cancelled_open_units', 'action', :e, CAST(:d AS jsonb))"),
                          {"t": t, "e": str(r["action_id"]),
                           "d": json.dumps({"sku_id": r["sku_id"], "location_id": r["location_id"], "reason": reason})})
            released += len(rows)
    return released
