"""Operational alert queue (BUS-018).

Four conditions raise alerts: stale data, failed reconciliation, exhausted budgets and unavailable models.
Failure sites raise alerts immediately (`raise_alert`); `evaluate` re-checks the state-based conditions on a
schedule, ages them and resolves alerts whose condition has cleared. The `alerts` table is the designated queue
(shown in the Exceptions inbox and `GET /api/v1/alerts`); when a webhook URL is configured each newly opened alert
is also delivered there, signed with HMAC-SHA256, with bounded retries.

An alert is deduplicated by (tenant, dedupe_key) while it is open: repeats increment `occurrences`.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import text

from .config import settings
from .db import tenant_session

log = logging.getLogger("supplylens.alerts")

KINDS = ("stale_data", "failed_reconciliation", "budget_exhausted", "model_unavailable", "job_failed")
DEFAULT_RULES = {"max_runs_per_day": 200}
MAX_DELIVERY_ATTEMPTS = 6


def raise_alert(tenant_id, kind: str, dedupe_key: str, title: str, detail: dict | None = None,
                severity: str = "medium") -> dict:
    """Open an alert, or bump the open one with the same dedupe key. Never raises into the caller's workflow."""
    if kind not in KINDS:
        raise ValueError(f"unknown alert kind {kind!r}")
    try:
        with tenant_session(tenant_id) as s:
            row = s.execute(text("""
                INSERT INTO alerts (id, tenant_id, kind, severity, dedupe_key, title, detail, delivery_status,
                                    next_delivery_at)
                VALUES (:i, :t, :k, :sev, :d, :ti, CAST(:de AS jsonb), :ds, CASE WHEN :ds = 'PENDING' THEN now() END)
                ON CONFLICT (tenant_id, dedupe_key) WHERE status <> 'RESOLVED'
                DO UPDATE SET occurrences = alerts.occurrences + 1, last_seen = now(), title = EXCLUDED.title,
                              detail = EXCLUDED.detail, severity = EXCLUDED.severity
                RETURNING id, (xmax = 0) AS opened, occurrences"""),
                {"i": uuid.uuid4(), "t": tenant_id, "k": kind, "sev": severity, "d": dedupe_key, "ti": title,
                 "de": json.dumps(detail or {}, default=str),
                 "ds": "PENDING" if settings.alert_webhook_url else "NONE"}).mappings().first()
        return dict(row)
    except Exception:
        log.exception("could not record alert %s", dedupe_key)
        return {}


def resolve_alert(tenant_id, dedupe_key: str) -> int:
    with tenant_session(tenant_id) as s:
        return s.execute(text("UPDATE alerts SET status='RESOLVED', resolved_at=now() "
                              "WHERE dedupe_key=:d AND status <> 'RESOLVED'"), {"d": dedupe_key}).rowcount


def _resolve_missing(s, prefix: str, still_failing: set[str]) -> int:
    """Resolve open alerts under `prefix:` whose condition no longer holds."""
    rows = s.execute(text("SELECT dedupe_key FROM alerts WHERE dedupe_key LIKE :p AND status <> 'RESOLVED'"),
                     {"p": prefix + ":%"}).all()
    stale = [r.dedupe_key for r in rows if r.dedupe_key not in still_failing]
    if stale:
        s.execute(text("UPDATE alerts SET status='RESOLVED', resolved_at=now() WHERE dedupe_key = ANY(:k) "
                       "AND status <> 'RESOLVED'"), {"k": stale})
    return len(stale)


def evaluate(tenant_id, *, now: datetime | None = None, check_models: bool = True) -> dict:
    """Re-check every state-based condition for a tenant; raise new alerts, resolve cleared ones."""
    now = now or datetime.now(UTC)
    raised: list[str] = []
    resolved = 0
    with tenant_session(tenant_id) as s:
        st = s.execute(text("SELECT operational_as_of, planning FROM tenant_settings")).first()
    rules = {**DEFAULT_RULES, **((st.planning or {}).get("alerts", {}) if st else {})}

    # 1. stale data: only for workspaces that declare a freshness requirement (replay workspaces are historic).
    stale_days = rules.get("stale_data_days")
    if st and stale_days is not None:
        age = (now - st.operational_as_of).total_seconds() / 86400
        if age > float(stale_days):
            raise_alert(tenant_id, "stale_data", "stale_data:operational",
                        f"Operational data is {age:.1f} days old (limit {stale_days})",
                        {"operational_as_of": st.operational_as_of, "age_days": round(age, 2), "limit_days": stale_days},
                        "medium")
            raised.append("stale_data:operational")
        else:
            resolved += resolve_alert(tenant_id, "stale_data:operational")

    # 2. failed reconciliation
    failing: set[str] = set()
    with tenant_session(tenant_id) as s:
        bad = s.execute(text("""
            SELECT id, status, status_reason, total_minor, currency, payload->>'supplier_id' AS supplier, updated_at
            FROM actions WHERE status IN ('FAILED', 'CONFIRMED', 'UNKNOWN_OUTCOME')""")).mappings().all()
    for a in bad:
        key = f"failed_reconciliation:{a['id']}"
        failing.add(key)
        what = {"FAILED": "Dispatch failed", "CONFIRMED": "Read-back mismatch",
                "UNKNOWN_OUTCOME": "Order outcome still unknown"}[a["status"]]
        raise_alert(tenant_id, "failed_reconciliation", key, f"{what} for order to {a['supplier']}",
                    {"action_id": str(a["id"]), "status": a["status"], "reason": a["status_reason"],
                     "total_minor": a["total_minor"], "currency": a["currency"]}, "high")
        raised.append(key)
    with tenant_session(tenant_id) as s:
        resolved += _resolve_missing(s, "failed_reconciliation", failing)

    # 3. exhausted budgets: runs that stopped on their tool/time budget, and the daily run allowance
    budget_keys: set[str] = set()
    with tenant_session(tenant_id) as s:
        partial = s.execute(text("SELECT id, state->>'tool_calls' AS calls FROM agent_runs WHERE status='PARTIAL' "
                                 "AND updated_at > now() - interval '24 hours'")).mappings().all()
        runs_24h = s.execute(text("SELECT count(*) FROM agent_runs WHERE created_at > now() - interval '24 hours'")).scalar()
    for r in partial:
        key = f"budget_exhausted:run:{r['id']}"
        budget_keys.add(key)
        raise_alert(tenant_id, "budget_exhausted", key, "Investigation stopped: run budget exhausted",
                    {"run_id": str(r["id"]), "tool_calls": r["calls"]}, "medium")
        raised.append(key)
    if runs_24h > int(rules["max_runs_per_day"]):
        key = "budget_exhausted:daily_runs"
        budget_keys.add(key)
        raise_alert(tenant_id, "budget_exhausted", key, f"{runs_24h} runs in 24 h exceeds the daily allowance",
                    {"runs_24h": runs_24h, "limit": rules["max_runs_per_day"]}, "medium")
        raised.append(key)
    with tenant_session(tenant_id) as s:
        resolved += _resolve_missing(s, "budget_exhausted", budget_keys)

    # 4. unavailable models: tampered/missing model artifacts, embedding service down
    if check_models:
        model_keys: set[str] = set()
        for key, title, detail in _model_problems(tenant_id):
            model_keys.add(key)
            raise_alert(tenant_id, "model_unavailable", key, title, detail, "high")
            raised.append(key)
        with tenant_session(tenant_id) as s:
            resolved += _resolve_missing(s, "model_unavailable", model_keys)
    return {"raised": sorted(set(raised)), "resolved": resolved}


def _model_problems(tenant_id):
    from .config import REPO_ROOT
    from .knowledge.embed import embed
    with tenant_session(tenant_id) as s:
        models = s.execute(text("""SELECT id, family, version, artifact_path, artifact_sha256 FROM model_versions
            WHERE status IN ('CHAMPION', 'CANDIDATE') AND artifact_path IS NOT NULL""")).mappings().all()
        embedded = s.execute(text("SELECT EXISTS (SELECT 1 FROM chunk_vectors)")).scalar()
    for m in models:
        arts = m["artifact_sha256"] if isinstance(m["artifact_sha256"], list) else json.loads(m["artifact_sha256"] or "[]")
        for a in arts:
            f = REPO_ROOT / m["artifact_path"] / a["file"]
            if not f.exists() or hashlib.sha256(f.read_bytes()).hexdigest() != a["sha256"]:
                yield (f"model_unavailable:artifact:{m['id']}", f"{m['family']} {m['version']} artifact missing or altered",
                       {"model_id": str(m["id"]), "family": m["family"], "file": a["file"]})
                break
    if embedded and not embed(["health check"], timeout=3):
        yield ("model_unavailable:embeddings", "Embedding service unavailable; retrieval is lexical-only",
               {"model": settings.embed_model, "effect": "hybrid retrieval degraded to lexical"})


# --------------------------------------------------------------------------------- webhook route
def _sign(body: bytes, timestamp: str) -> str:
    """HMAC-SHA256 over "<unix seconds>.<body>". The timestamp is signed, so a receiver can reject stale or replayed deliveries."""
    return "sha256=" + hmac.new(settings.alert_webhook_secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def deliver_pending(tenant_id, *, client: httpx.Client | None = None, limit: int = 20) -> dict:
    """Deliver newly opened alerts to the webhook with backoff; give up after MAX_DELIVERY_ATTEMPTS."""
    if not settings.alert_webhook_url:
        return {"delivered": 0, "failed": 0, "retry": 0}
    out = {"delivered": 0, "failed": 0, "retry": 0}
    own = client is None
    client = client or httpx.Client(timeout=5)
    try:
        with tenant_session(tenant_id) as s:
            rows = s.execute(text("""SELECT id, kind, severity, dedupe_key, title, detail, status, occurrences, first_seen,
                delivery_attempts FROM alerts WHERE delivery_status='PENDING' AND next_delivery_at <= now()
                ORDER BY first_seen LIMIT :l FOR UPDATE SKIP LOCKED"""), {"l": limit}).mappings().all()
            for r in rows:
                body = json.dumps({"id": str(r["id"]), "tenant_id": str(tenant_id), "kind": r["kind"],
                                   "severity": r["severity"], "title": r["title"], "detail": r["detail"],
                                   "status": r["status"], "occurrences": r["occurrences"],
                                   "first_seen": r["first_seen"].isoformat()}, default=str).encode()
                err = None
                try:
                    ts = str(int(time.time()))
                    resp = client.post(settings.alert_webhook_url, content=body, headers={
                        "Content-Type": "application/json", "X-SupplyLens-Timestamp": ts,
                        "X-SupplyLens-Signature": _sign(body, ts), "Idempotency-Key": f"alert-{r['id']}"})
                    if resp.status_code >= 300:
                        err = f"HTTP {resp.status_code}"
                except httpx.HTTPError as e:
                    err = f"{type(e).__name__}: {e}"
                attempts = r["delivery_attempts"] + 1
                if err is None:
                    s.execute(text("UPDATE alerts SET delivery_status='DELIVERED', delivered_at=now(), "
                                   "delivery_attempts=:n, delivery_error=NULL, next_delivery_at=NULL WHERE id=:i"),
                              {"n": attempts, "i": r["id"]})
                    out["delivered"] += 1
                elif attempts >= MAX_DELIVERY_ATTEMPTS:
                    s.execute(text("UPDATE alerts SET delivery_status='FAILED', delivery_attempts=:n, "
                                   "delivery_error=:e, next_delivery_at=NULL WHERE id=:i"),
                              {"n": attempts, "e": err, "i": r["id"]})
                    out["failed"] += 1
                else:
                    s.execute(text("UPDATE alerts SET delivery_attempts=:n, delivery_error=:e, "
                                   "next_delivery_at=now() + make_interval(secs => :b) WHERE id=:i"),
                              {"n": attempts, "e": err, "b": min(300, 2 ** attempts), "i": r["id"]})
                    out["retry"] += 1
    finally:
        if own:
            client.close()
    return out
