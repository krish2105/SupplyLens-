"""Connector health per workspace: a circuit breaker in front of the purchasing system (Phase 6).

* An outage (AdapterUnavailable) counts consecutive failures. From OUTAGE_THRESHOLD on, the connector is UNAVAILABLE and
  dispatch pauses with an exponential cool-down; when it ends, one dispatch is let through as a probe. Paused items keep
  their retry budget: before this, a 30-second outage spent all five attempts and failed every queued order.
* Rejected or expired credentials (AdapterAuthError) set CREDENTIALS_INVALID at once. Nothing is sent until a health
  probe (worker, every PROBE_EVERY_S) succeeds, which a person triggers by fixing the credentials.
* Any successful call closes the circuit and resolves the connector alerts.
State lives in erp_connector_state (migration 0011); on an older schema every check answers "go ahead" (the pre-Phase-6
behaviour) so the hosted demo keeps working until it is migrated.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import text

from .. import alerts
from ..config import settings
from ..db import tenant_session
from . import schema
from .contract import AdapterAuthError, AdapterUnavailable
from .registry import adapter

log = logging.getLogger("supplylens.connector")
OUTAGE_THRESHOLD = 3
MAX_PAUSE_S = 300
PROBE_EVERY_S = 60
ALERT_UNAVAILABLE = "erp_connector:unavailable"
ALERT_CREDENTIALS = "erp_connector:credentials"


def _ensure(s, tenant_id) -> None:
    s.execute(text("INSERT INTO erp_connector_state (tenant_id, adapter) VALUES (:t, :a) ON CONFLICT (tenant_id) DO NOTHING"),
              {"t": tenant_id, "a": settings.erp_adapter})


DEFAULT = {"status": "OK", "consecutive_failures": 0, "paused_until": None, "last_error": None, "last_probe_at": None,
           "receipts_cursor": 0}


def state(tenant_id) -> dict | None:
    """Read-only: a workspace without a row is OK. Reads never create the row, so a deleted workspace stays empty
    (the worker finishes its tick for a workspace it has just deleted)."""
    if not schema.has_0011():
        return None
    with tenant_session(tenant_id) as s:
        row = s.execute(text("SELECT * FROM erp_connector_state")).mappings().first()
    return dict(row) if row else {"tenant_id": tenant_id, "adapter": settings.erp_adapter, **DEFAULT}


def may_dispatch(tenant_id) -> tuple[bool, str | None]:
    """Whether the dispatcher may call the target now; the reason when it may not."""
    st = state(tenant_id)
    if st is None or st["status"] == "OK":
        return True, None
    if st["status"] == "CREDENTIALS_INVALID":
        return False, "ERP credentials invalid; dispatch paused until a health check succeeds"
    if st["paused_until"] and st["paused_until"] > datetime.now(UTC):
        return False, f"ERP unavailable; dispatch paused until {st['paused_until'].isoformat(timespec='seconds')}"
    return True, None          # cool-down over: let one attempt through as a probe


def record_success(tenant_id) -> None:
    if not schema.has_0011():
        return
    with tenant_session(tenant_id) as s:
        _ensure(s, tenant_id)
        was = s.execute(text("SELECT status FROM erp_connector_state WHERE tenant_id=:t FOR UPDATE"), {"t": tenant_id}).scalar()
        s.execute(text("""UPDATE erp_connector_state SET status='OK', consecutive_failures=0, paused_until=NULL,
            last_success_at=now(), updated_at=now() WHERE tenant_id=:t"""), {"t": tenant_id})
    if was != "OK":
        alerts.resolve_alert(tenant_id, ALERT_UNAVAILABLE)
        alerts.resolve_alert(tenant_id, ALERT_CREDENTIALS)


def record_failure(tenant_id, exc: Exception) -> str:
    """Record an outage or credential failure; returns the connector status afterwards."""
    if not schema.has_0011():
        return "OK"
    credentials = isinstance(exc, AdapterAuthError)
    with tenant_session(tenant_id) as s:
        _ensure(s, tenant_id)
        row = s.execute(text("""UPDATE erp_connector_state SET consecutive_failures = consecutive_failures + 1,
            last_error = :e, last_failure_at = now(), updated_at = now(),
            status = CASE WHEN :cred THEN 'CREDENTIALS_INVALID'
                          WHEN consecutive_failures + 1 >= :n THEN 'UNAVAILABLE' ELSE status END,
            paused_until = CASE WHEN :cred THEN NULL
                                WHEN consecutive_failures + 1 >= :n
                                THEN now() + make_interval(secs => LEAST(:mx, 30 * power(2, consecutive_failures + 1 - :n)))
                                ELSE paused_until END
            WHERE tenant_id = :t RETURNING status, consecutive_failures, paused_until"""),
            {"t": tenant_id, "e": f"{type(exc).__name__}: {exc}", "cred": credentials, "n": OUTAGE_THRESHOLD,
             "mx": MAX_PAUSE_S}).mappings().first()
    if row["status"] == "CREDENTIALS_INVALID":
        alerts.raise_alert(tenant_id, "erp_connector", ALERT_CREDENTIALS, "ERP credentials rejected: order dispatch paused",
                           {"error": str(exc), "adapter": settings.erp_adapter,
                            "action": "renew the credentials, then use Test connection (or wait for the next health check)"},
                           "high")
    elif row["status"] == "UNAVAILABLE":
        alerts.raise_alert(tenant_id, "erp_connector", ALERT_UNAVAILABLE, "ERP unavailable: order dispatch paused",
                           {"error": str(exc), "consecutive_failures": row["consecutive_failures"],
                            "paused_until": row["paused_until"], "adapter": settings.erp_adapter}, "high")
    return row["status"]


def probe(tenant_id, *, force: bool = False) -> dict:
    """Health-check the target. The worker calls this every PROBE_EVERY_S while the connector is not OK; an operator can
    force it after renewing credentials. Never sends an order."""
    st = state(tenant_id)
    if st is None:
        return {"status": "OK", "checked": False, "note": "database not migrated to 0011; connector state not tracked"}
    if not force and st["status"] == "OK":
        return {"status": "OK", "checked": False}
    if not force and st["last_probe_at"] and (datetime.now(UTC) - st["last_probe_at"]).total_seconds() < PROBE_EVERY_S:
        return {"status": st["status"], "checked": False}
    with tenant_session(tenant_id) as s:
        s.execute(text("UPDATE erp_connector_state SET last_probe_at = now() WHERE tenant_id = :t"), {"t": tenant_id})
    try:
        detail = adapter().health()
    except (AdapterUnavailable, AdapterAuthError) as e:
        return {"status": record_failure(tenant_id, e), "checked": True, "error": str(e)}
    record_success(tenant_id)
    return {"status": "OK", "checked": True, "adapter": detail.get("adapter"), "qualification": detail.get("status")}
