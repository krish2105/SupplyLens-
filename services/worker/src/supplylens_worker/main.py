"""SupplyLens worker: runs queued jobs and dispatches the outbox for every tenant.

Run: uv run python -m supplylens_worker.main [--once]
"""
from __future__ import annotations

import argparse
import logging
import socket
import threading
import time
import uuid

from sqlalchemy import text

from supplylens import jobs
from supplylens.actions import service as actions
from supplylens.agent.graph import execute_run
from supplylens.db import tenant_session

log = logging.getLogger("supplylens.worker")
WORKER_ID = f"{socket.gethostname()}:{uuid.uuid4().hex[:6]}"


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
                           "d": '{"statuses": %s}' % str(sorted(st)).replace("'", '"')})


def run_job(tenant_id, job: dict) -> None:
    stop = threading.Event()
    hb = threading.Thread(target=jobs.heartbeat, args=(tenant_id, job, stop), daemon=True)
    hb.start()
    try:
        if job["kind"] == "agent_run":
            result = execute_run(tenant_id, uuid.UUID(job["payload"]["run_id"]))
            status = "FAILED" if result.get("status") == "FAILED" else "SUCCEEDED"
            jobs.finish(tenant_id, job, status, result, result.get("error"))
        else:
            jobs.finish(tenant_id, job, "FAILED", error=f"unknown job kind {job['kind']}")
    except Exception as e:  # noqa: BLE001 - recorded on the job
        log.exception("job failed")
        jobs.finish(tenant_id, job, "FAILED", error=f"{type(e).__name__}: {e}")
    finally:
        stop.set()


def tick() -> int:
    worked = 0
    for t in jobs.tenants():
        job = jobs.claim(t, WORKER_ID)
        if job:
            run_job(t, job)
            worked += 1
        while (r := actions.dispatch_once(t, WORKER_ID)) is not None:
            log.info("dispatch %s", r)
            worked += 1
        refresh_runs(t)
    return worked


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=float, default=1.0)
    ns = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info("worker %s started", WORKER_ID)
    while True:
        n = tick()
        if ns.once:
            break
        if not n:
            time.sleep(ns.interval)


if __name__ == "__main__":
    main()
