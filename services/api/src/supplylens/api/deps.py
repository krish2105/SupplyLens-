"""Request authentication (dev session cookie), tenant membership, CSRF and idempotency."""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Callable

from fastapi import Depends, Header, HTTPException, Query, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import text

from ..authz import Actor, resolve_actor
from ..config import settings
from ..db import control_session, tenant_session

COOKIE = "sl_session"
SESSION_MAX_AGE = 60 * 60 * 12
serializer = URLSafeTimedSerializer(settings.session_secret, salt="supplylens-session")


def current_user_id(request: Request) -> uuid.UUID:
    raw = request.cookies.get(COOKIE)
    if not raw:
        raise HTTPException(401, {"code": "unauthenticated", "message": "sign in required"})
    try:
        data = serializer.loads(raw, max_age=SESSION_MAX_AGE)
    except BadSignature:
        raise HTTPException(401, {"code": "session_invalid", "message": "session expired or invalid"})
    return uuid.UUID(data["uid"])


def tenant_from_header(request: Request, x_supplylens_tenant: str | None = Header(None),
                       ws: str | None = Query(None)) -> uuid.UUID:
    # EventSource cannot send headers, so read-only GETs may name the workspace in ?ws=.
    slug = x_supplylens_tenant or (ws if request.method == "GET" else None)
    if not slug:
        raise HTTPException(400, {"code": "tenant_required", "message": "X-SupplyLens-Tenant header required"})
    with control_session() as s:
        tid = s.execute(text("SELECT id FROM tenants WHERE slug = :s AND deleted_at IS NULL"), {"s": slug}).scalar()
    if tid is None:
        raise HTTPException(404, {"code": "tenant_not_found", "message": "unknown workspace"})
    return tid


def actor(user_id: uuid.UUID = Depends(current_user_id),
          tenant_id: uuid.UUID = Depends(tenant_from_header)) -> Actor:
    a = resolve_actor(user_id, tenant_id)
    if a is None:
        # Same response whether the tenant exists for others or not.
        raise HTTPException(404, {"code": "tenant_not_found", "message": "unknown workspace"})
    return a


def csrf_guard(request: Request) -> None:
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if request.headers.get("x-requested-with") != "supplylens":
            raise HTTPException(403, {"code": "csrf", "message": "missing anti-CSRF header"})


CLAIM_SECONDS = 120


def _claim(a: Actor, key: str, route: str, rhash: str) -> bool:
    """Atomically claim the key. Exactly one concurrent caller wins; a claim abandoned by a crashed
    process becomes claimable again once its lease (CLAIM_SECONDS) has passed."""
    with tenant_session(a.tenant_id) as s:
        won = s.execute(text("""
            INSERT INTO idempotency_keys (tenant_id, key, route, request_hash, state, claimed_until)
            VALUES (:t, :k, :r, :h, 'IN_PROGRESS', now() + make_interval(secs => :l))
            ON CONFLICT (tenant_id, key) DO UPDATE
              SET claimed_until = now() + make_interval(secs => :l), route = EXCLUDED.route,
                  request_hash = EXCLUDED.request_hash
              WHERE idempotency_keys.state = 'IN_PROGRESS' AND idempotency_keys.claimed_until < now()
                AND idempotency_keys.route = EXCLUDED.route AND idempotency_keys.request_hash = EXCLUDED.request_hash
            RETURNING key"""), {"t": a.tenant_id, "k": key, "r": route, "h": rhash, "l": CLAIM_SECONDS}).first()
    return won is not None


def _release(a: Actor, key: str) -> None:
    with tenant_session(a.tenant_id) as s:
        s.execute(text("DELETE FROM idempotency_keys WHERE key = :k AND state = 'IN_PROGRESS'"), {"k": key})


def idempotent(a: Actor, key: str | None, route: str, body: Any, fn: Callable[[], tuple[int, Any]]):
    """Execute `fn` at most once per key.

    The key is claimed with a single INSERT ... ON CONFLICT before `fn` runs, so concurrent identical
    requests cannot both execute: the loser gets 409 `idempotency_in_progress` (retry shortly) and a later
    retry replays the stored response. A key reused for a different request is rejected (409). If `fn`
    raises, the claim is released so the caller can correct the request and retry with the same key."""
    if not key or len(key) > 200:
        raise HTTPException(428, {"code": "idempotency_key_required", "message": "Idempotency-Key header required"})
    rhash = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
    if not _claim(a, key, route, rhash):
        with tenant_session(a.tenant_id) as s:
            row = s.execute(text("SELECT route, request_hash, state, status_code, response FROM idempotency_keys "
                                 "WHERE key=:k"), {"k": key}).first()
        if row is None:  # released between our claim attempt and the read: ask the caller to retry
            raise HTTPException(409, {"code": "idempotency_in_progress", "message": "request is being processed; retry"},
                                headers={"Retry-After": "1"})
        if row.route != route or row.request_hash != rhash:
            raise HTTPException(409, {"code": "idempotency_key_reused",
                                      "message": "this Idempotency-Key was used for a different request"})
        if row.state != "DONE":
            raise HTTPException(409, {"code": "idempotency_in_progress",
                                      "message": "an identical request is still being processed; retry shortly"},
                                headers={"Retry-After": "1"})
        return row.status_code, {**row.response, "idempotent_replay": True}
    try:
        status, response = fn()
    except BaseException:
        _release(a, key)
        raise
    with tenant_session(a.tenant_id) as s:
        s.execute(text("""UPDATE idempotency_keys SET state='DONE', status_code=:c, response=CAST(:b AS jsonb),
            claimed_until=NULL WHERE key=:k"""), {"c": status, "b": json.dumps(response, default=str), "k": key})
    return status, response
