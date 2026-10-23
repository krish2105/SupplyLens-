"""Operational health and order reconciliation reports (Phase 6, COO readiness).

`health` answers "is the service doing its job right now": database, workers, job queue, order outbox, imports, alerts,
ERP connector. `reconciliation` answers "does every approved order have a known, matching outcome": order states, items
needing a person, the open-order ledger, receipt synchronisation, and the service-level indicators the runbook defines
(docs/operations/slo.md). Both read the database only; neither calls the purchasing system.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime

from sqlalchemy import text

from .config import settings
from .db import control_session, tenant_session
from .integrations import schema
from .integrations.sync import OVERDUE_GRACE_DAYS

WORKER_STALE_S = 30            # a worker ticks every second when idle; 30 s without a tick means it is stopped or stuck
OUTBOX_STUCK_S = 300           # an approved order not dispatched within 5 minutes breaches the dispatch objective
JOB_STUCK_S = 600


def _age(ts) -> float | None:
    return None if ts is None else round((datetime.now(UTC) - ts).total_seconds(), 1)


def workers() -> dict:
    if settings.inline_jobs:
        return {"mode": "inline", "status": "ok", "note": "serverless hosting: requests run queued work themselves"}
    if not schema.has_0011():
        return {"mode": "worker", "status": "unknown", "note": "database not migrated to 0011; heartbeats not recorded"}
    with control_session() as s:
        rows = [dict(r) for r in s.execute(text("""SELECT worker_id, host, started_at, last_tick_at, ticks, last_error,
            last_error_at FROM worker_heartbeats WHERE last_tick_at > now() - interval '1 day' ORDER BY last_tick_at DESC"""))
            .mappings()]
    for r in rows:
        r["age_s"] = _age(r["last_tick_at"])
    live = [r for r in rows if r["age_s"] is not None and r["age_s"] <= WORKER_STALE_S]
    return {"mode": "worker", "status": "ok" if live else "failing", "live": len(live), "recent": rows[:10],
            "stale_after_s": WORKER_STALE_S}


def health(tenant_id) -> dict:
    t0 = time.perf_counter()
    problems: list[str] = []
    with tenant_session(tenant_id) as s:
        s.execute(text("SELECT 1"))
        db_ms = round((time.perf_counter() - t0) * 1000, 1)
        jobs = dict(s.execute(text("""SELECT
              count(*) FILTER (WHERE status = 'QUEUED') AS queued,
              count(*) FILTER (WHERE status = 'RUNNING') AS running,
              count(*) FILTER (WHERE status = 'FAILED' AND updated_at > now() - interval '24 hours') AS failed_24h,
              max(extract(epoch FROM now() - run_after)) FILTER (WHERE status = 'QUEUED') AS oldest_queued_s,
              count(*) FILTER (WHERE status = 'RUNNING' AND lease_expires_at < now()) AS lease_expired
            FROM jobs""")).mappings().first())
        failed_jobs = [dict(r) for r in s.execute(text("""SELECT id, kind, attempts, max_attempts, error, updated_at FROM jobs
            WHERE status = 'FAILED' ORDER BY updated_at DESC LIMIT 5""")).mappings()]
        outbox = _outbox(s)
        imports = dict(s.execute(text("""SELECT
              count(*) FILTER (WHERE status = 'REJECTED' AND created_at > now() - interval '7 days') AS rejected_7d,
              count(*) FILTER (WHERE status IN ('UPLOADED', 'VALIDATED') AND created_at < now() - interval '1 day')
                AS unpublished_over_1d,
              coalesce(sum(rows_quarantined) FILTER (WHERE created_at > now() - interval '7 days'), 0) AS quarantined_rows_7d
            FROM import_batches""")).mappings().first())
        failed_imports = [dict(r) for r in s.execute(text("""SELECT id, kind, file_name, status, rows_total, rows_quarantined,
            report->'errors' AS errors, created_at FROM import_batches WHERE status = 'REJECTED' OR rows_quarantined > 0
            ORDER BY created_at DESC LIMIT 5""")).mappings()]
        open_alerts = [dict(r) for r in s.execute(text("""SELECT kind, severity, count(*) AS n, min(first_seen) AS oldest
            FROM alerts WHERE status <> 'RESOLVED' GROUP BY kind, severity ORDER BY kind, severity""")).mappings()]
        conn = (dict(s.execute(text("SELECT adapter, status, consecutive_failures, paused_until, last_error, "
                                    "last_success_at, last_failure_at, last_order_sync_at, last_receipt_sync_at "
                                    "FROM erp_connector_state")).mappings().first() or {})
                if schema.has_0011() else {})
    w = workers()
    if w["status"] == "failing":
        problems.append(f"no worker has ticked in the last {WORKER_STALE_S} s: queued work and order dispatch are stopped")
    if (jobs["oldest_queued_s"] or 0) > JOB_STUCK_S:
        problems.append(f"a job has waited {jobs['oldest_queued_s']:.0f} s to start")
    if jobs["lease_expired"]:
        problems.append(f"{jobs['lease_expired']} job(s) running past their lease")
    if outbox["oldest_pending_s"] and outbox["oldest_pending_s"] > OUTBOX_STUCK_S:
        problems.append(f"an approved order has waited {outbox['oldest_pending_s']:.0f} s for dispatch")
    if outbox["in_flight_lease_expired"]:
        problems.append(f"{outbox['in_flight_lease_expired']} dispatch(es) interrupted (lease expired)")
    if conn.get("status") not in (None, "OK"):
        problems.append(f"ERP connector {conn['status']}: {conn.get('last_error')}")
    high = sum(a["n"] for a in open_alerts if a["severity"] == "high")
    status = "failing" if (w["status"] == "failing" or conn.get("status") == "CREDENTIALS_INVALID") else (
        "degraded" if problems or high else "ok")
    return {"status": status, "problems": problems, "checked_at": datetime.now(UTC),
            "database": {"status": "ok", "latency_ms": db_ms, "schema_0011": schema.has_0011()},
            "workers": w, "jobs": {**jobs, "recent_failures": failed_jobs}, "outbox": outbox,
            "imports": {**imports, "recent_problems": failed_imports}, "alerts": open_alerts, "connector": conn}


def _outbox(s) -> dict:
    by = {r.status: r.n for r in s.execute(text("SELECT status, count(*) n FROM outbox GROUP BY status"))}
    row = s.execute(text("""SELECT
          max(extract(epoch FROM now() - next_attempt_at)) FILTER (WHERE status = 'PENDING' AND next_attempt_at <= now())
            AS oldest_pending_s,
          count(*) FILTER (WHERE status = 'IN_FLIGHT' AND lease_expires_at < now()) AS in_flight_lease_expired
        FROM outbox""")).mappings().first()
    kinds = ({r.failure_kind: r.n for r in s.execute(text("SELECT failure_kind, count(*) n FROM outbox WHERE "
                                                           "failure_kind IS NOT NULL GROUP BY failure_kind"))}
             if schema.has_0011() else {})
    return {"by_status": by, "failure_kinds": kinds, "oldest_pending_s": row["oldest_pending_s"],
            "in_flight_lease_expired": row["in_flight_lease_expired"]}


ATTENTION = {"UNKNOWN_OUTCOME": "outcome unknown: reconcile (looks the order up; never resends)",
             "CONFIRMED": "the purchasing system's order differs from the approval: accept it or cancel it there",
             "FAILED": "dispatch failed: see the reason; retry only if the failure was transient",
             "STALE": "terms, approval or payload changed: review again before anything is sent"}


def reconciliation(tenant_id, *, days: int = 30) -> dict:
    with tenant_session(tenant_id) as s:
        by_status = {r.status: r.n for r in s.execute(text("SELECT status, count(*) n FROM actions GROUP BY status"))}
        kind = "o.failure_kind" if schema.has_0011() else "NULL"     # a fixed column expression, never input
        attention = [dict(r) for r in s.execute(text(
            "SELECT a.id AS action_id, a.status, a.status_reason, a.payload->>'supplier_id' AS supplier_id, a.total_minor, "
            "a.currency, a.external_ref, a.updated_at, o.attempts, o.last_error, " + kind + " AS failure_kind "
            "FROM actions a LEFT JOIN outbox o ON o.action_id = a.id "
            "WHERE a.status IN ('UNKNOWN_OUTCOME', 'CONFIRMED', 'FAILED', 'STALE') ORDER BY a.updated_at LIMIT 100")).mappings()]
        for x in attention:
            x["age_s"] = _age(x["updated_at"])
            x["next_step"] = ATTENTION[x["status"]]
        ledger = dict(s.execute(text("""
            WITH today AS (SELECT coalesce((SELECT operational_as_of::date FROM tenant_settings), current_date) AS d)
            SELECT count(*) FILTER (WHERE status = 'OPEN') AS open_lines,
                   count(*) FILTER (WHERE status = 'PARTIAL') AS partial_lines,
                   count(*) FILTER (WHERE status IN ('OPEN', 'PARTIAL') AND expected_on + :g < (SELECT d FROM today))
                     AS overdue_lines,
                   coalesce(sum(ordered_units - received_units - cancelled_units), 0) AS open_units,
                   (SELECT d FROM today) AS business_date
            FROM purchase_order_lines"""), {"g": OVERDUE_GRACE_DAYS}).mappings().first())
        overdue = [dict(r) for r in s.execute(text("""
            WITH today AS (SELECT coalesce((SELECT operational_as_of::date FROM tenant_settings), current_date) AS d)
            SELECT action_id, external_ref, supplier_id, sku_id, location_id, ordered_units, received_units,
                   cancelled_units, expected_on, (SELECT d FROM today) - expected_on AS days_overdue
            FROM purchase_order_lines WHERE status IN ('OPEN', 'PARTIAL') AND expected_on + :g < (SELECT d FROM today)
            ORDER BY expected_on LIMIT 50"""), {"g": OVERDUE_GRACE_DAYS}).mappings()]
        sync_alerts = [dict(r) for r in s.execute(text("""SELECT dedupe_key, kind, severity, title, detail, first_seen,
            occurrences FROM alerts WHERE status <> 'RESOLVED' AND kind IN ('erp_sync', 'erp_connector', 'overdue_receipt')
            ORDER BY first_seen""")).mappings()] if schema.has_0011() else []
        sli = dict(s.execute(text("""
            WITH ap AS (SELECT entity_id, min(at) AS approved_at FROM audit_events WHERE action = 'action.approved'
                          AND at > now() - make_interval(days => :d) GROUP BY entity_id),
                 rc AS (SELECT entity_id, min(at) AS reconciled_at FROM audit_events WHERE action = 'dispatch.reconciled'
                          GROUP BY entity_id),
                 lat AS (SELECT extract(epoch FROM rc.reconciled_at - ap.approved_at) AS s FROM ap JOIN rc USING (entity_id))
            SELECT (SELECT count(*) FROM ap) AS approved,
                   (SELECT count(*) FROM lat) AS reconciled,
                   (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY s) FROM lat) AS p50_s,
                   (SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY s) FROM lat) AS p95_s,
                   (SELECT count(*) FROM lat WHERE s <= 300) AS within_5_min,
                   (SELECT count(DISTINCT entity_id) FROM audit_events WHERE action = 'dispatch.unknown_outcome'
                      AND at > now() - make_interval(days => :d)) AS unknown_outcomes"""), {"d": days}).mappings().first())
        sli["window_days"] = days
        sli["approved_to_reconciled_within_5_min"] = (round(sli["within_5_min"] / sli["reconciled"], 4)
                                                      if sli["reconciled"] else None)
        conn = (dict(s.execute(text("SELECT status, receipts_cursor, last_order_sync_at, last_receipt_sync_at, last_error "
                                    "FROM erp_connector_state")).mappings().first() or {})
                if schema.has_0011() else {})
        outbox = _outbox(s)
    unaccounted = sum(by_status.get(k, 0) for k in ("UNKNOWN_OUTCOME", "CONFIRMED"))
    return {"generated_at": datetime.now(UTC), "adapter": settings.erp_adapter, "actions_by_status": by_status,
            "outbox": outbox, "needs_attention": attention, "unaccounted_orders": unaccounted, "ledger": ledger,
            "overdue_lines": overdue, "sync": conn, "sync_alerts": sync_alerts, "service_levels": sli}
