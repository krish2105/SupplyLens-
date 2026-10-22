"""Durable job queue on PostgreSQL (FOR UPDATE SKIP LOCKED, lease, heartbeat, fencing)."""
from __future__ import annotations

import json
import logging
import threading
import uuid

from sqlalchemy import text

from .db import control_session, tenant_session

log = logging.getLogger("supplylens.jobs")
LEASE_SECONDS = 45
HEARTBEAT_SECONDS = 10


def tenants() -> list[uuid.UUID]:
    with control_session() as s:
        return [r.id for r in s.execute(text("SELECT id FROM tenants WHERE deleted_at IS NULL ORDER BY slug"))]


def expire_exhausted(tenant_id) -> list[dict]:
    """Fail jobs whose lease ran out on their last attempt (audit P2-REL-01). Without this they stay RUNNING forever: claim()
    never takes them again, and their agent run shows as running. The run is failed with the reason and an alert opens."""
    with tenant_session(tenant_id) as s:
        gone = [dict(r) for r in s.execute(text("""
            UPDATE jobs SET status='FAILED', lease_owner=NULL, lease_expires_at=NULL, updated_at=now(),
              error='lease expired on the final attempt (' || attempts || ' of ' || max_attempts || '); the worker stopped'
            WHERE status='RUNNING' AND lease_expires_at < now() AND attempts >= max_attempts
            RETURNING id, kind, payload, attempts""")).mappings()]
        for j in gone:
            run_id = (j["payload"] or {}).get("run_id")
            if j["kind"] == "agent_run" and run_id:
                s.execute(text("""UPDATE agent_runs SET status='FAILED', updated_at=now() WHERE id=:r
                    AND status NOT IN ('SUCCEEDED','FAILED','CANCELLED','REVIEW_REQUIRED','WAITING_FOR_APPROVAL','COMPLETE')"""),
                          {"r": run_id})
                s.execute(text("INSERT INTO agent_events (tenant_id, run_id, node, kind, summary, data) VALUES "
                               "(:t,:r,'WORKER','failed',:m,CAST(:d AS jsonb))"),
                          {"t": tenant_id, "r": run_id, "m": "Run failed: its worker stopped on the final attempt",
                           "d": json.dumps({"job_id": str(j["id"]), "attempts": j["attempts"]})})
    for j in gone:
        from . import alerts
        alerts.raise_alert(tenant_id, "job_failed", f"job_failed:{j['id']}", f"Background job {j['kind']} failed",
                           {"job_id": str(j["id"]), "attempts": j["attempts"], "reason": "lease expired on the final attempt"},
                           "high")
    return gone


def claim(tenant_id, worker: str) -> dict | None:
    expire_exhausted(tenant_id)
    with tenant_session(tenant_id) as s:
        row = s.execute(text("""
            SELECT id FROM jobs WHERE (status = 'QUEUED' AND run_after <= now())
               OR (status = 'RUNNING' AND lease_expires_at < now() AND attempts < max_attempts)
            ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED""")).first()
        if not row:
            return None
        return dict(s.execute(text("""
            UPDATE jobs SET status='RUNNING', attempts=attempts+1, lease_owner=:w,
              lease_expires_at=now() + make_interval(secs => :l), fencing_token=fencing_token+1, updated_at=now()
            WHERE id=:i RETURNING id, kind, payload, attempts, fencing_token"""),
            {"i": row.id, "w": worker, "l": LEASE_SECONDS}).mappings().first())


def heartbeat(tenant_id, job: dict, stop: threading.Event) -> None:
    """Extend the lease every HEARTBEAT_SECONDS. A transient database error is retried on the next beat instead of
    silently ending the thread (P2-REL-02); the lease (45 s) outlasts several missed beats."""
    while not stop.wait(HEARTBEAT_SECONDS):
        try:
            with tenant_session(tenant_id) as s:
                ok = s.execute(text("""UPDATE jobs SET lease_expires_at = now() + make_interval(secs => :l)
                    WHERE id=:i AND fencing_token=:f AND status='RUNNING' RETURNING id"""),
                    {"i": job["id"], "f": job["fencing_token"], "l": LEASE_SECONDS}).first()
        except Exception:
            log.warning("heartbeat for job %s failed; retrying", job["id"], exc_info=True)
            continue
        if not ok:
            return


def finish(tenant_id, job: dict, status: str, result: dict | None = None, error: str | None = None) -> bool:
    with tenant_session(tenant_id) as s:
        return s.execute(text("""UPDATE jobs SET status=:s, result=CAST(:r AS jsonb), error=:e, lease_owner=NULL,
            lease_expires_at=NULL, updated_at=now() WHERE id=:i AND fencing_token=:f RETURNING id"""),
            {"s": status, "r": json.dumps(result or {}, default=str), "e": error, "i": job["id"],
             "f": job["fencing_token"]}).first() is not None
