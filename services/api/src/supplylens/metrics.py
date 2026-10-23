"""In-process service metrics in the Prometheus text format (Phase 3 observability).

Request rate, errors and latency per route template; admission (in-flight, queued, refused per class); connection-pool
saturation; database connections; job and outbox queue depth; consumption per workspace (requests, server seconds,
refusals). Served at GET /metrics only when SUPPLYLENS_METRICS_TOKEN is set, to a caller presenting it as a bearer token:
the per-workspace series name workspace ids, which is operator information, not public.

Values are per process (each API instance reports its own; a scraper sums them). No request bodies, query strings, user
ids or SQL appear in any label.
"""
from __future__ import annotations

import threading
import time
from bisect import bisect_left
from collections import defaultdict

BUCKETS = (0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
MAX_TENANT_SERIES = 500        # bound label cardinality; further workspaces are reported as "other"

_lock = threading.Lock()
_requests: dict[tuple[str, str, str], int] = defaultdict(int)          # (method, route, status class) -> count
_latency: dict[tuple[str, str], list[float]] = {}                     # (method, route) -> bucket counts + [sum, count]
_tenant: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
_counters: dict[str, float] = defaultdict(float)
_queue_cache: dict = {"at": 0.0, "lines": []}
STARTED = time.time()


def observe(method: str, route: str, status: int, seconds: float, tenant: str | None, cls: str | None) -> None:
    sc = f"{status // 100}xx"
    with _lock:
        _requests[(method, route, sc)] += 1
        h = _latency.setdefault((method, route), [0.0] * (len(BUCKETS) + 2))
        i = bisect_left(BUCKETS, seconds)
        if i < len(BUCKETS):
            h[i] += 1
        h[-2] += seconds
        h[-1] += 1
        if tenant:
            key = tenant if tenant in _tenant or len(_tenant) < MAX_TENANT_SERIES else "other"
            t = _tenant[key]
            t["requests"] += 1
            t["seconds"] += seconds
            if cls in ("retrieval", "compute"):
                t[f"{cls}_seconds"] += seconds
            if status in (429, 503):
                t["refused"] += 1
            if status >= 500 and status != 503:
                t["errors"] += 1


def count(name: str, value: float = 1.0) -> None:
    with _lock:
        _counters[name] += value


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _queue_depth(lines: list[str]) -> None:
    """Jobs and outbox items by status, summed over workspaces (row-level security: one transaction per workspace).
    Cached for 15 s so a fast scraper cannot turn this into load."""
    now = time.monotonic()
    if now - _queue_cache["at"] < 15 and _queue_cache["lines"]:
        lines += _queue_cache["lines"]
        return
    from sqlalchemy import text

    from .db import control_session, tenant_session
    jobs: dict[str, int] = defaultdict(int)
    outbox: dict[str, int] = defaultdict(int)
    oldest_queued = 0.0
    oldest_pending_order = 0.0
    connectors_not_ok = 0
    worker_age = None
    from .integrations import schema
    try:
        with control_session() as s:
            tenants = [r.id for r in s.execute(text("SELECT id FROM tenants WHERE deleted_at IS NULL"))]
        for t in tenants:
            with tenant_session(t) as s:
                for r in s.execute(text("""SELECT status, count(*) n, max(extract(epoch FROM now() - created_at)) age
                                           FROM jobs WHERE status IN ('QUEUED','RUNNING') GROUP BY status""")):
                    jobs[r.status] += r.n
                    if r.status == "QUEUED":
                        oldest_queued = max(oldest_queued, float(r.age or 0))
                for r in s.execute(text("""SELECT status, count(*) n FROM outbox
                                           WHERE status IN ('PENDING','IN_FLIGHT','UNKNOWN_OUTCOME') GROUP BY status""")):
                    outbox[r.status] += r.n
                age = s.execute(text("""SELECT max(extract(epoch FROM now() - next_attempt_at)) FROM outbox
                                        WHERE status = 'PENDING' AND next_attempt_at <= now()""")).scalar()
                oldest_pending_order = max(oldest_pending_order, float(age or 0))
                if schema.has_0011():
                    connectors_not_ok += s.execute(text("SELECT count(*) FROM erp_connector_state "
                                                        "WHERE status <> 'OK'")).scalar()
        if schema.has_0011():
            with control_session() as s:
                worker_age = s.execute(text("SELECT min(extract(epoch FROM now() - last_tick_at)) "
                                            "FROM worker_heartbeats")).scalar()
    except Exception:                       # metrics must never fail the scrape because the database is struggling
        count("metrics_queue_depth_errors_total")
        return
    out = ["# TYPE supplylens_jobs gauge"]
    out += [f'supplylens_jobs{{status="{k}"}} {jobs.get(k, 0)}' for k in ("QUEUED", "RUNNING")]
    out += ["# TYPE supplylens_jobs_oldest_queued_seconds gauge", f"supplylens_jobs_oldest_queued_seconds {oldest_queued:.1f}"]
    out += ["# TYPE supplylens_outbox gauge"]
    out += [f'supplylens_outbox{{status="{k}"}} {outbox.get(k, 0)}' for k in ("PENDING", "IN_FLIGHT", "UNKNOWN_OUTCOME")]
    # Phase 6: what the dispatch and worker alerts key on (docs/operations/slo.md)
    out += ["# TYPE supplylens_outbox_oldest_pending_seconds gauge",
            f"supplylens_outbox_oldest_pending_seconds {oldest_pending_order:.1f}",
            "# TYPE supplylens_erp_connectors_not_ok gauge", f"supplylens_erp_connectors_not_ok {connectors_not_ok}"]
    if worker_age is not None:
        out += ["# TYPE supplylens_worker_heartbeat_age_seconds gauge",
                f"supplylens_worker_heartbeat_age_seconds {float(worker_age):.1f}"]
    _queue_cache.update(at=now, lines=out)
    lines += out


def _database(lines: list[str]) -> None:
    from sqlalchemy import text

    from .db import app_engine, control_session
    pool = app_engine().pool
    lines += ["# TYPE supplylens_db_pool_size gauge", f"supplylens_db_pool_size {pool.size()}",
              "# TYPE supplylens_db_pool_checked_out gauge", f"supplylens_db_pool_checked_out {pool.checkedout()}",
              "# TYPE supplylens_db_pool_overflow gauge", f"supplylens_db_pool_overflow {pool.overflow()}"]
    try:
        with control_session() as s:
            r = s.execute(text("""SELECT count(*) FILTER (WHERE state = 'active') AS active, count(*) AS total,
                current_setting('max_connections')::int AS max FROM pg_stat_activity WHERE datname = current_database()""")).one()
        lines += ["# TYPE supplylens_db_connections gauge", f'supplylens_db_connections{{state="active"}} {r.active}',
                  f'supplylens_db_connections{{state="all"}} {r.total}',
                  "# TYPE supplylens_db_max_connections gauge", f"supplylens_db_max_connections {r.max}"]
    except Exception:
        count("metrics_database_errors_total")


def render() -> str:
    from .api.admission import gates
    lines = ["# TYPE supplylens_up gauge", "supplylens_up 1",
             "# TYPE supplylens_process_start_time_seconds gauge", f"supplylens_process_start_time_seconds {STARTED:.0f}"]
    with _lock:
        lines.append("# TYPE supplylens_http_requests_total counter")
        for (m, r, sc), n in sorted(_requests.items()):
            lines.append(f'supplylens_http_requests_total{{method="{m}",route="{_esc(r)}",status="{sc}"}} {n}')
        lines.append("# TYPE supplylens_http_request_duration_seconds histogram")
        for (m, r), h in sorted(_latency.items()):
            labels = f'method="{m}",route="{_esc(r)}"'
            cum = 0.0
            for b, c in zip(BUCKETS, h[:len(BUCKETS)], strict=True):
                cum += c
                lines.append(f'supplylens_http_request_duration_seconds_bucket{{{labels},le="{b}"}} {cum:.0f}')
            lines.append(f'supplylens_http_request_duration_seconds_bucket{{{labels},le="+Inf"}} {h[-1]:.0f}')
            lines.append(f"supplylens_http_request_duration_seconds_sum{{{labels}}} {h[-2]:.6f}")
            lines.append(f"supplylens_http_request_duration_seconds_count{{{labels}}} {h[-1]:.0f}")
        for metric, kind in (("requests", "counter"), ("seconds", "counter"), ("retrieval_seconds", "counter"),
                             ("compute_seconds", "counter"), ("refused", "counter"), ("errors", "counter")):
            lines.append(f"# TYPE supplylens_tenant_{metric}_total {kind}")
            for t, v in sorted(_tenant.items()):
                lines.append(f'supplylens_tenant_{metric}_total{{workspace="{_esc(t)}"}} {v.get(metric, 0.0):g}')
        for name, v in sorted(_counters.items()):
            lines += [f"# TYPE supplylens_{name} counter", f"supplylens_{name} {v:g}"]
    lines += ["# TYPE supplylens_admission_inflight gauge", "# TYPE supplylens_admission_capacity gauge",
              "# TYPE supplylens_admission_waiting gauge", "# TYPE supplylens_admission_rejected_total counter",
              "# TYPE supplylens_admission_queued_total counter", "# TYPE supplylens_admission_wait_seconds_total counter"]
    for name, g in gates().items():
        lines += [f'supplylens_admission_inflight{{class="{name}"}} {g.inflight}',
                  f'supplylens_admission_capacity{{class="{name}"}} {g.cap}',
                  f'supplylens_admission_waiting{{class="{name}"}} {g.waiting}',
                  f'supplylens_admission_queued_total{{class="{name}"}} {g.queued}',
                  f'supplylens_admission_wait_seconds_total{{class="{name}"}} {g.wait_seconds:.3f}']
        for reason in ("tenant_share", "queue_full", "wait_timeout"):
            lines.append(f'supplylens_admission_rejected_total{{class="{name}",reason="{reason}"}} {g.rejected.get(reason, 0)}')
    _database(lines)
    _queue_depth(lines)
    return "\n".join(lines) + "\n"


def reset() -> None:
    """Tests only."""
    with _lock:
        _requests.clear()
        _latency.clear()
        _tenant.clear()
        _counters.clear()
        _queue_cache.update(at=0.0, lines=[])
