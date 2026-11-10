"""Request authentication (dev session cookie), tenant membership, CSRF and idempotency."""
from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, Header, HTTPException, Query, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import text

from ..authz import Actor, resolve_actor
from ..config import settings
from ..db import control_session, tenant_session
from ..idempotency import current_key

COOKIE = "sl_session"
SESSION_MAX_AGE = 60 * 60 * 12          # absolute lifetime of any session (signed into the cookie)
DEV_IDLE_SECONDS = 60 * 60 * 2          # a development session unused this long ends (ASVS V3 idle timeout)
TOUCH_SECONDS = 60                      # how often last use is written back, at most
DEV_SUBJECT = "development-account"     # auth_sessions.oidc_subject for development sign-ins
serializer = URLSafeTimedSerializer(settings.session_secret, salt="supplylens-session")


def start_dev_session(user_id: uuid.UUID) -> str:
    """Server-side record for a development sign-in, so sign-out and deactivation end it (Phase 2, SEC-P2-02)."""
    sid = uuid.uuid4()
    with control_session() as s:
        s.execute(text("INSERT INTO auth_sessions (id, user_id, oidc_subject) VALUES (:i, :u, :s)"),
                  {"i": sid, "u": user_id, "s": DEV_SUBJECT})
    return serializer.dumps({"uid": str(user_id), "sid": str(sid), "kind": "dev"})


def _confirm_dev_session(sid: uuid.UUID, uid: uuid.UUID) -> bool:
    """Raise 401 if the session ended; return True when this request recorded a new last use (the cookie is then
    refreshed, see SessionCookie)."""
    with control_session() as s:
        row = s.execute(text("""SELECT user_id, revoked_at, now() - checked_at AS idle FROM auth_sessions
            WHERE id = :i AND oidc_subject = :s"""), {"i": sid, "s": DEV_SUBJECT}).first()
    if row is None or row.revoked_at is not None or row.user_id != uid:
        raise HTTPException(401, {"code": "session_revoked", "message": "session ended; sign in again"})
    idle = row.idle.total_seconds()
    if idle > DEV_IDLE_SECONDS or idle > TOUCH_SECONDS:
        with control_session() as s:          # committed before any 401 is raised
            if idle > DEV_IDLE_SECONDS:
                s.execute(text("UPDATE auth_sessions SET revoked_at = now(), revoked_reason = 'idle timeout' WHERE id = :i"),
                          {"i": sid})
            else:
                s.execute(text("UPDATE auth_sessions SET checked_at = now() WHERE id = :i"), {"i": sid})
    if idle > DEV_IDLE_SECONDS:
        raise HTTPException(401, {"code": "session_expired", "message": "session expired after inactivity; sign in again"})
    return idle > TOUCH_SECONDS


def current_user_id(request: Request) -> uuid.UUID:
    raw = request.cookies.get(COOKIE)
    if not raw:
        raise HTTPException(401, {"code": "unauthenticated", "message": "sign in required"})
    try:
        return _session_user(request, raw)
    except HTTPException as e:
        if e.status_code == 401:
            request.state.session_cookie = None        # a dead session's cookie is deleted (SessionCookie)
        raise


def _session_user(request: Request, raw: str) -> uuid.UUID:
    try:
        data, signed_at = serializer.loads(raw, max_age=SESSION_MAX_AGE, return_timestamp=True)
    except BadSignature:
        raise HTTPException(401, {"code": "session_invalid", "message": "session expired or invalid"}) from None
    if not data.get("sid"):
        # stateless sessions (before Phase 2) could not be revoked: they are no longer accepted
        raise HTTPException(401, {"code": "session_invalid", "message": "session expired or invalid"})
    if data.get("kind") == "dev":
        if not settings.dev_login_available:
            raise HTTPException(401, {"code": "session_invalid", "message": "development sessions are not accepted here"})
        if _confirm_dev_session(uuid.UUID(data["sid"]), uuid.UUID(data["uid"])):
            # Sliding expiry (FE-P8-07): the browser keeps the cookie only as long as the server keeps the session idle-
            # alive, never past its absolute lifetime. The value is unchanged, so its signed issue time stays the same.
            left = SESSION_MAX_AGE - int((datetime.now(UTC) - signed_at).total_seconds())
            request.state.session_cookie = (raw, max(0, min(DEV_IDLE_SECONDS, left)))
    else:
        # identity-provider session: re-confirmed with the provider periodically (deactivation ends it)
        from .oidc import confirm_session
        confirm_session(uuid.UUID(data["sid"]))
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


def actor(request: Request, user_id: uuid.UUID = Depends(current_user_id),
          tenant_id: uuid.UUID = Depends(tenant_from_header)) -> Actor:
    a = resolve_actor(user_id, tenant_id)
    if a is None:
        # Same response whether the tenant exists for others or not.
        raise HTTPException(404, {"code": "tenant_not_found", "message": "unknown workspace"})
    request.state.workspace = str(a.tenant_id)      # per-workspace consumption metrics (metrics.py), set only once authorised
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
    raises, the claim is released so the caller can correct the request and retry with the same key. Services that
    commit a durable change also mark the key DONE inside that transaction (`idempotency.record_outcome`), so a crash
    between the commit and the final update below replays instead of executing twice."""
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
    token = current_key.set(key)       # services record their outcome in their own transaction (audit F05)
    try:
        status, response = fn()
    except BaseException:
        _release(a, key)
        raise
    finally:
        current_key.reset(token)
    with tenant_session(a.tenant_id) as s:
        s.execute(text("""UPDATE idempotency_keys SET state='DONE', status_code=:c, response=CAST(:b AS jsonb),
            claimed_until=NULL WHERE key=:k"""), {"c": status, "b": json.dumps(response, default=str), "k": key})
    return status, response


class SessionCookie:
    """ASGI middleware that applies what authentication decided about the session cookie (FE-P8-07): refresh its Max-Age
    after a request recorded a new last use, or delete it when the request found the session dead (401). It never
    overrides a cookie the route set or deleted itself (sign-in, sign-out). Pure ASGI, so streamed responses pass through."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_cookie(message):
            if message["type"] == "http.response.start":
                state = scope.get("state") or {}
                if "session_cookie" in state:
                    headers = list(message.get("headers", []))
                    prefix = f"{COOKIE}=".encode()
                    if not any(k.lower() == b"set-cookie" and v.startswith(prefix) for k, v in headers):
                        from starlette.responses import Response
                        r = Response()
                        decision = state["session_cookie"]
                        if decision is None:
                            r.delete_cookie(COOKIE, path="/")
                        else:
                            value, max_age = decision
                            r.set_cookie(COOKIE, value, max_age=max_age, httponly=True, samesite="lax",
                                         secure=settings.cookie_secure, path="/")
                        headers += [(k, v) for k, v in r.raw_headers if k.lower() == b"set-cookie"]
                        message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_cookie)
