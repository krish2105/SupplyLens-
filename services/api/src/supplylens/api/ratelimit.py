"""Per-tenant, per-actor token buckets for costly endpoints, shared by every API process.

The bucket lives in PostgreSQL and is updated by one atomic INSERT ... ON CONFLICT DO UPDATE, so the limit holds
across processes and replicas (DEF-03). A request that finds fewer than one token changes nothing.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy import text

from ..authz import Actor
from ..db import tenant_session
from .deps import actor

_TAKE = text("""
    INSERT INTO rate_limit_buckets (tenant_id, bucket, tokens, updated_at)
    VALUES (:t, :b, :cap - 1, clock_timestamp())
    ON CONFLICT (tenant_id, bucket) DO UPDATE
      SET tokens = LEAST(:cap, rate_limit_buckets.tokens
                         + EXTRACT(EPOCH FROM (clock_timestamp() - rate_limit_buckets.updated_at)) * :rate) - 1,
          updated_at = clock_timestamp()
      WHERE LEAST(:cap, rate_limit_buckets.tokens
                  + EXTRACT(EPOCH FROM (clock_timestamp() - rate_limit_buckets.updated_at)) * :rate) >= 1
    RETURNING tokens""")

_PEEK = text("""
    SELECT LEAST(:cap, tokens + EXTRACT(EPOCH FROM (clock_timestamp() - updated_at)) * :rate) AS tokens
    FROM rate_limit_buckets WHERE tenant_id = :t AND bucket = :b""")


def take(tenant_id, bucket: str, per_minute: int, burst: int | None = None) -> int | None:
    """Take one token. Returns None when allowed, else the seconds to wait."""
    cap = float(burst or per_minute)
    rate = per_minute / 60.0
    params = {"t": tenant_id, "b": bucket, "cap": cap, "rate": rate}
    with tenant_session(tenant_id) as s:
        if s.execute(_TAKE, params).first() is not None:
            return None
        tokens = s.execute(_PEEK, params).scalar() or 0.0
    return int((1 - tokens) / rate) + 1


def limit(name: str, per_minute: int, burst: int | None = None):
    def dep(a: Actor = Depends(actor)) -> Actor:
        retry = take(a.tenant_id, f"{name}:{a.user_id}", per_minute, burst)
        if retry is not None:
            raise HTTPException(429, {"code": "rate_limited", "message": f"too many {name} requests; retry in {retry}s",
                                      "retry_after_s": retry}, headers={"Retry-After": str(retry)})
        return a
    return dep
