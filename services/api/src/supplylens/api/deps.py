"""Request authentication (dev session cookie), tenant membership, CSRF and idempotency."""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Callable

from fastapi import Depends, Header, HTTPException, Request
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


def tenant_from_header(x_supplylens_tenant: str = Header(...)) -> uuid.UUID:
    with control_session() as s:
        tid = s.execute(text("SELECT id FROM tenants WHERE slug = :s"), {"s": x_supplylens_tenant}).scalar()
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


def idempotent(a: Actor, key: str | None, route: str, body: Any, fn: Callable[[], tuple[int, Any]]):
    """Replay the stored response for a repeated key; reject a reused key with a different body."""
    if not key or len(key) > 200:
        raise HTTPException(428, {"code": "idempotency_key_required", "message": "Idempotency-Key header required"})
    rhash = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
    with tenant_session(a.tenant_id) as s:
        row = s.execute(text("SELECT route, request_hash, status_code, response FROM idempotency_keys WHERE key=:k"),
                        {"k": key}).first()
    if row:
        if row.route != route or row.request_hash != rhash:
            raise HTTPException(409, {"code": "idempotency_key_reused",
                                      "message": "this Idempotency-Key was used for a different request"})
        return row.status_code, {**row.response, "idempotent_replay": True}
    status, response = fn()
    with tenant_session(a.tenant_id) as s:
        s.execute(text("""INSERT INTO idempotency_keys (tenant_id, key, route, request_hash, status_code, response)
            VALUES (:t,:k,:r,:h,:c,CAST(:b AS jsonb)) ON CONFLICT DO NOTHING"""),
            {"t": a.tenant_id, "k": key, "r": route, "h": rhash, "c": status,
             "b": json.dumps(response, default=str)})
    return status, response
