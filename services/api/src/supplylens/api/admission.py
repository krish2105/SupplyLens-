"""Admission control: bounded concurrency, a short bounded queue and per-workspace shares (DEF-10, SEC-P2-11, Phase 3).

Three classes are counted per API process:
  * all        every request except health checks, sign-in state and event streams (cap: max_inflight);
  * retrieval  GET /evidence/search, a scan of the workspace's chunks (cap: max_inflight_retrieval);
  * compute    POST /forecasts, /scenarios, /agent-runs: forecasting, the optimiser, run starts (cap: max_inflight_compute).
A request whose class is full waits in a queue of at most `admission_queue` requests for up to `admission_wait_ms`, then
is refused with 503 and Retry-After. A full queue refuses at once. Refusing early is what keeps the accepted requests fast
and recovery immediate (the 2026-10-21 load test without it took minutes to recover).

Per-workspace share: while another workspace holds or waits for a slot of a class, one workspace may hold at most
ceil(cap * tenant_share) of it; a workspace over its share then gets 429 (it is the one sending too much) while the
others are admitted. A workspace alone may use the whole class. The workspace is taken from the
X-SupplyLens-Tenant header (or ?ws= on GET) before authentication; a caller naming a workspace it does not belong to is
refused by authentication a few milliseconds later, so it can hold a slot only that long.

The counters live in this process. Several processes or serverless instances each enforce their own caps, so the
platform's total is caps x instances; the database-backed rate limits (ratelimit.py) are the cross-process bound.
"""
from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field

from ..config import settings

EXEMPT = ("/health", "/metrics", "/api/v1/auth", "/api/v1/me")
COMPUTE = ("/api/v1/scenarios", "/api/v1/forecasts", "/api/v1/agent-runs")
POLL_S = 0.01


@dataclass
class Gate:
    name: str
    cap: int
    inflight: int = 0
    waiting: int = 0
    by_tenant: dict[str, int] = field(default_factory=dict)
    waiting_by_tenant: dict[str, int] = field(default_factory=dict)
    admitted: int = 0
    queued: int = 0
    rejected: dict[str, int] = field(default_factory=dict)
    wait_seconds: float = 0.0

    @property
    def tenant_cap(self) -> int:
        return max(1, math.ceil(self.cap * settings.tenant_share))

    def _over_share(self, tenant: str | None) -> bool:
        """At its share while another workspace holds or awaits a slot. Work-conserving: a workspace alone may use the
        whole class, so a single-workspace installation loses no capacity."""
        if not tenant or self.by_tenant.get(tenant, 0) < self.tenant_cap:
            return False
        return any(n > 0 for k, n in (*self.by_tenant.items(), *self.waiting_by_tenant.items()) if k != tenant)

    def _reject(self, reason: str) -> str:
        self.rejected[reason] = self.rejected.get(reason, 0) + 1
        return reason

    async def acquire(self, tenant: str | None) -> str | None:
        """Take a slot. Returns None when admitted, else the refusal reason ('tenant_share', 'queue_full', 'wait_timeout')."""
        if self._over_share(tenant):
            return self._reject("tenant_share")
        if self.inflight >= self.cap:
            if self.waiting >= settings.admission_queue or settings.admission_wait_ms <= 0:
                return self._reject("queue_full")
            self.waiting += 1
            self.queued += 1
            key = tenant or ""
            self.waiting_by_tenant[key] = self.waiting_by_tenant.get(key, 0) + 1
            start = time.monotonic()
            deadline = start + settings.admission_wait_ms / 1000
            try:
                while self.inflight >= self.cap:      # polled: waiting happens only while the class is full
                    if time.monotonic() >= deadline:
                        return self._reject("wait_timeout")
                    await asyncio.sleep(POLL_S)
                if self._over_share(tenant):
                    return self._reject("tenant_share")
            finally:
                self.waiting -= 1
                left = self.waiting_by_tenant.get(key, 1) - 1
                if left > 0:
                    self.waiting_by_tenant[key] = left
                else:
                    self.waiting_by_tenant.pop(key, None)
                self.wait_seconds += time.monotonic() - start
        self.inflight += 1
        self.admitted += 1
        if tenant:
            self.by_tenant[tenant] = self.by_tenant.get(tenant, 0) + 1
        return None

    def release(self, tenant: str | None) -> None:
        self.inflight -= 1
        if tenant:
            n = self.by_tenant.get(tenant, 1) - 1
            if n > 0:
                self.by_tenant[tenant] = n
            else:
                self.by_tenant.pop(tenant, None)


GATES: dict[str, Gate] = {}


def gates() -> dict[str, Gate]:
    """The process's gates, created on first use so settings changed by tests or the hosting entrypoint apply."""
    if not GATES:
        GATES.update(all=Gate("all", settings.max_inflight), retrieval=Gate("retrieval", settings.max_inflight_retrieval),
                     compute=Gate("compute", settings.max_inflight_compute))
    return GATES


def classify(method: str, path: str) -> str | None:
    """'retrieval', 'compute', 'all' or None (not counted)."""
    if path.startswith(EXEMPT) or path.endswith("/stream"):
        return None
    if path.startswith("/api/v1/evidence/search"):
        return "retrieval"
    if method == "POST" and path.startswith(COMPUTE):
        return "compute"
    return "all"


def tenant_of(scope) -> str | None:
    headers = dict(scope.get("headers") or [])
    slug = headers.get(b"x-supplylens-tenant", b"").decode("latin-1").strip()
    if not slug and scope.get("method") == "GET":
        for part in scope.get("query_string", b"").decode("latin-1").split("&"):
            if part.startswith("ws="):
                slug = part[3:]
    return slug[:80] or None


def refusal(reason: str, cls: str) -> tuple[int, dict, dict]:
    if reason == "tenant_share":
        return 429, {"code": "workspace_busy", "message": "This workspace already has as many requests of this kind running "
                     "as it may; retry in a few seconds.", "retry_after_s": 2}, {"Retry-After": "2"}
    return 503, {"code": "overloaded", "message": "The service is at capacity; retry in a few seconds.",
                 "retry_after_s": 2}, {"Retry-After": "2"}
