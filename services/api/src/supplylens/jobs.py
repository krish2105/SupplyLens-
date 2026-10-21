"""Durable job queue on PostgreSQL (FOR UPDATE SKIP LOCKED, lease, heartbeat, fencing)."""
from __future__ import annotations

import json
import threading
import uuid

from sqlalchemy import text

from .db import control_session, tenant_session

LEASE_SECONDS = 45
HEARTBEAT_SECONDS = 10


def tenants() -> list[uuid.UUID]:
    with control_session() as s:
        return [r.id for r in s.execute(text("SELECT id FROM tenants ORDER BY slug"))]


def claim(tenant_id, worker: str) -> dict | None:
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
    while not stop.wait(HEARTBEAT_SECONDS):
        with tenant_session(tenant_id) as s:
            ok = s.execute(text("""UPDATE jobs SET lease_expires_at = now() + make_interval(secs => :l)
                WHERE id=:i AND fencing_token=:f AND status='RUNNING' RETURNING id"""),
                {"i": job["id"], "f": job["fencing_token"], "l": LEASE_SECONDS}).first()
        if not ok:
            return


def finish(tenant_id, job: dict, status: str, result: dict | None = None, error: str | None = None) -> bool:
    with tenant_session(tenant_id) as s:
        return s.execute(text("""UPDATE jobs SET status=:s, result=CAST(:r AS jsonb), error=:e, lease_owner=NULL,
            lease_expires_at=NULL, updated_at=now() WHERE id=:i AND fencing_token=:f RETURNING id"""),
            {"s": status, "r": json.dumps(result or {}, default=str), "e": error, "i": job["id"],
             "f": job["fencing_token"]}).first() is not None
