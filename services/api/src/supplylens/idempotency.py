"""Idempotency outcome recorded in the same transaction as the business effect (audit F05).

`api.deps.idempotent` claims the key before the work runs and stores the response after it. Between those two steps a
process can commit the business change (an approval, a queued run) and die before storing the response; once the claim
lease lapsed, a retry would run the work a second time. Services that make a durable change call `record_outcome` inside
their own transaction, so the change and the stored response commit or roll back together, and a retry replays it.
"""
from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Any

from sqlalchemy import text

current_key: ContextVar[str | None] = ContextVar("idempotency_key", default=None)


def record_outcome(s, status_code: int, response: Any) -> None:
    """Mark the claimed key DONE with `response`, inside the caller's (tenant) transaction `s`. No-op without a key."""
    key = current_key.get()
    if key is None:
        return
    s.execute(text("""UPDATE idempotency_keys SET state='DONE', status_code=:c, response=CAST(:b AS jsonb),
        claimed_until=NULL WHERE key=:k AND state='IN_PROGRESS'"""),
              {"c": status_code, "b": json.dumps(response, default=str), "k": key})
