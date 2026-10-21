"""Per-tenant, per-actor token buckets for costly endpoints (single-process; documented limitation)."""
from __future__ import annotations

import threading
import time

from fastapi import Depends, HTTPException

from ..authz import Actor
from .deps import actor

_LOCK = threading.Lock()
_BUCKETS: dict[tuple, tuple[float, float]] = {}


def limit(name: str, per_minute: int, burst: int | None = None):
    cap = float(burst or per_minute)
    rate = per_minute / 60.0

    def dep(a: Actor = Depends(actor)) -> Actor:
        key = (name, a.tenant_id, a.user_id)
        now = time.monotonic()
        with _LOCK:
            tokens, last = _BUCKETS.get(key, (cap, now))
            tokens = min(cap, tokens + (now - last) * rate)
            if tokens < 1:
                retry = int((1 - tokens) / rate) + 1
                raise HTTPException(429, {"code": "rate_limited", "message": f"too many {name} requests; retry in {retry}s",
                                          "retry_after_s": retry})
            _BUCKETS[key] = (tokens - 1, now)
        return a
    return dep
