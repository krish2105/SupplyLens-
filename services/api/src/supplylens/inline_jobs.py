"""Run a tenant's queued work inside the request that queued it (settings.inline_jobs; serverless hosting).

The same functions the worker runs, in the same order: claim queued jobs (agent runs) and dispatch approved orders, with
the same leases and fencing, so a concurrent worker elsewhere could not double-process anything. Bounded so a request
never loops: at most `limit` jobs and dispatches.
"""
from __future__ import annotations

import logging

from .actions import service as actions
from .config import settings

log = logging.getLogger("supplylens.inline_jobs")


def drain(tenant_id, limit: int = 10) -> int:
    if not settings.inline_jobs:
        return 0
    from supplylens_worker.main import WORKER_ID, refresh_runs, run_job

    from . import jobs
    done = 0
    for _ in range(limit):
        job = jobs.claim(tenant_id, WORKER_ID)
        if not job:
            break
        run_job(tenant_id, job)
        done += 1
    for _ in range(limit):
        if actions.dispatch_once(tenant_id, WORKER_ID) is None:
            break
        done += 1
    refresh_runs(tenant_id)
    return done
