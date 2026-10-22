"""SupplyLens worker: runs queued jobs and dispatches the outbox for every tenant.

Run: uv run python -m supplylens_worker.main [--once]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import tempfile
import threading
import time
import uuid
from pathlib import Path

from sqlalchemy import text

from supplylens import alerts, jobs, lifecycle, telemetry
from supplylens.actions import service as actions
from supplylens.agent.graph import execute_run
from supplylens.config import settings
from supplylens.db import tenant_session

log = logging.getLogger("supplylens.worker")
WORKER_ID = f"{socket.gethostname()}:{uuid.uuid4().hex[:6]}"
HEARTBEAT = Path(os.environ.get("SUPPLYLENS_WORKER_HEARTBEAT") or Path(tempfile.gettempdir()) / "supplylens-worker.heartbeat")


def refresh_runs(tenant_id) -> None:
    """A run waiting for approval completes once all its actions reach a terminal state."""
    with tenant_session(tenant_id) as s:
        rows = s.execute(text("""
            SELECT r.id, array_agg(a.status) AS statuses FROM agent_runs r JOIN actions a ON a.agent_run_id = r.id
            WHERE r.status = 'WAITING_FOR_APPROVAL' GROUP BY r.id""")).all()
        for r in rows:
            st = set(r.statuses)
            if st <= {"RECONCILED", "REJECTED", "STALE", "FAILED"}:
                final = "COMPLETE" if "RECONCILED" in st else "CLOSED_WITHOUT_ORDER"
                s.execute(text("UPDATE agent_runs SET status=:s, updated_at=now() WHERE id=:i"),
                          {"s": final, "i": r.id})
                s.execute(text("INSERT INTO agent_events (tenant_id, run_id, node, kind, summary, data) VALUES "
                               "(:t,:r,'VERIFY','run_finished',:m,CAST(:d AS jsonb))"),
                          {"t": tenant_id, "r": r.id, "m": f"Actions settled: {', '.join(sorted(st))}",
                           "d": json.dumps({"statuses": sorted(st)})})


def run_job(tenant_id, job: dict) -> None:
    with telemetry.continue_trace(job["payload"].get("trace"), f"job.{job['kind']}", **{
            "tenant.id": str(tenant_id), "job.id": str(job["id"]), "job.attempt": job["attempts"]}):
        _run_job(tenant_id, job)


def _run_job(tenant_id, job: dict) -> None:
    stop = threading.Event()
    hb = threading.Thread(target=jobs.heartbeat, args=(tenant_id, job, stop), daemon=True)
    hb.start()
    try:
        if job["kind"] == "agent_run":
            result = execute_run(tenant_id, uuid.UUID(job["payload"]["run_id"]))
            status = "FAILED" if result.get("status") == "FAILED" else "SUCCEEDED"
            jobs.finish(tenant_id, job, status, result, result.get("error"))
        elif job["kind"] == "tenant_export":
            result = lifecycle.run_export(tenant_id, uuid.UUID(job["payload"]["export_id"]))
            jobs.finish(tenant_id, job, "SUCCEEDED", result)
        elif job["kind"] == "tenant_deletion":
            p = job["payload"]
            cert = lifecycle.run_deletion(tenant_id, uuid.UUID(p["deletion_id"]), uuid.UUID(p["requested_by"]),
                                          uuid.UUID(p["export_id"]), job_id=job["id"])
            jobs.finish(tenant_id, job, "SUCCEEDED", {"deletion_id": p["deletion_id"],
                                                      "rows_deleted": sum(cert["rows_deleted"].values())})
        else:
            jobs.finish(tenant_id, job, "FAILED", error=f"unknown job kind {job['kind']}")
    except Exception as e:
        log.exception("job failed")
        jobs.finish(tenant_id, job, "FAILED", error=f"{type(e).__name__}: {e}")
    finally:
        stop.set()


ALERT_EVERY_S = 30
_last_alert_eval: dict = {}


def alert_tick(tenant_id) -> None:
    """Deliver pending alerts every tick; re-evaluate state-based conditions every ALERT_EVERY_S."""
    alerts.deliver_pending(tenant_id)
    now = time.monotonic()
    if now - _last_alert_eval.get(tenant_id, -1e9) >= ALERT_EVERY_S:
        _last_alert_eval[tenant_id] = now
        try:
            alerts.evaluate(tenant_id)
        except Exception:
            log.exception("alert evaluation failed")


# Per tick and workspace: one job and at most this many outbox dispatches, so a workspace with a long backlog cannot hold
# the loop while the others wait (P2-REL-03). The loop comes straight back while any workspace still had work.
DISPATCH_PER_TICK = 10


def tenant_tick(tenant_id) -> int:
    worked = 0
    job = jobs.claim(tenant_id, WORKER_ID)
    if job:
        run_job(tenant_id, job)
        worked += 1
    for _ in range(DISPATCH_PER_TICK):
        r = actions.dispatch_once(tenant_id, WORKER_ID)
        if r is None:
            break
        log.info("dispatch %s", r)
        worked += 1
    refresh_runs(tenant_id)
    alert_tick(tenant_id)
    return worked


def tick() -> int:
    """One pass over every workspace. A failure in one workspace is logged and counted and does not stop the others
    (P2-REL-03): before, one workspace's database error ended the whole tick, every tick."""
    worked = 0
    for t in jobs.tenants():
        try:
            worked += tenant_tick(t)
        except Exception:
            log.exception("worker tick failed for workspace %s; continuing with the others", t)
    return worked


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=float, default=1.0)
    ns = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Exports and deletions may legitimately run long statements; the API's statement_timeout does not apply here.
    settings.db_statement_timeout_ms = settings.worker_statement_timeout_ms
    telemetry.setup(service_name="supplylens-worker")
    log.info("worker %s started", WORKER_ID)
    while True:
        try:
            n = tick()
            HEARTBEAT.touch()          # a container health check reads this file's age
        except Exception:
            if ns.once:
                raise
            log.exception("worker tick failed; retrying")      # a database blip must not end the process
            n = 0
            time.sleep(min(30.0, ns.interval * 5))
        if ns.once:
            break
        if not n:
            time.sleep(ns.interval)
    telemetry.shutdown()


if __name__ == "__main__":
    main()
