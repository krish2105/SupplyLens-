"""Which optional schema the connected database has.

The hosted demo's database is migrated by the owner through a temporary setup token after a deploy (PD-009, PD-016), so
for a while new code can serve an older schema. Features that need migration 0011 check `has_0011()` and fall back to the
earlier behaviour instead of failing the request. A negative answer is re-checked after a minute; a positive one is final.
"""
from __future__ import annotations

import time

from sqlalchemy import text

from ..db import app_engine

_RECHECK_S = 60.0
_known: bool = False
_checked_at: float = -1e9


def has_0011() -> bool:
    global _known, _checked_at
    if _known:
        return True
    now = time.monotonic()
    if now - _checked_at < _RECHECK_S:
        return False
    _checked_at = now
    with app_engine().connect() as c:
        _known = bool(c.execute(text("SELECT to_regclass('public.erp_connector_state') IS NOT NULL")).scalar())
    return _known
