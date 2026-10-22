"""Request-level guards that run before routing, authentication or body parsing (Phase 2, SEC-P2-03).

* BodyLimit refuses request bodies over MAX_BODY_BYTES with 413: by Content-Length when the client sends it, and by
  counting streamed bytes when it does not. Multipart parsing (CSV upload) spools whatever it receives, so the cap has to
  sit in front of it; the largest legitimate body is a 5 MB CSV plus form overhead.
* SignInThrottle limits sign-in attempts per client address (development sign-in and the OIDC start/callback) with a
  token bucket. It is per process: on a platform with many instances it slows, rather than stops, a distributed burst.
"""
from __future__ import annotations

import json
import threading
import time

MAX_BODY_BYTES = 6 * 1024 * 1024
SIGN_IN_PATHS = ("/api/v1/auth/dev-login", "/api/v1/auth/oidc/login", "/api/v1/auth/oidc/callback")


async def _reply(send, status: int, code: str, message: str, headers: list[tuple[bytes, bytes]] | None = None) -> None:
    body = json.dumps({"code": code, "message": message}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                            (b"cache-control", b"no-store"), *(headers or [])]})
    await send({"type": "http.response.body", "body": body})


class BodyLimit:
    def __init__(self, app, max_bytes: int = MAX_BODY_BYTES):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        declared = dict(scope.get("headers") or []).get(b"content-length")
        too_large = f"request bodies are limited to {self.max_bytes} bytes"
        if declared is not None:
            # the server enforces Content-Length framing, so a declared length within the cap is the real length
            if not declared.isdigit() or int(declared) > self.max_bytes:
                return await _reply(send, 413, "payload_too_large", too_large)
            return await self.app(scope, receive, send)
        # No declared length (chunked): read up to the cap first, then replay what was read to the application.
        buffered, seen = [], 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                buffered.append(message)
                break
            seen += len(message.get("body", b""))
            if seen > self.max_bytes:
                return await _reply(send, 413, "payload_too_large", too_large)
            buffered.append(message)
            if not message.get("more_body", False):
                break
        replay = iter(buffered)

        async def replayed():
            return next(replay, None) or await receive()

        await self.app(scope, replayed, send)


def client_address(scope, trust_forwarded_for: bool) -> str:
    """The caller's address: the connection's peer, or the first X-Forwarded-For entry when the deployment sits behind a
    proxy that overwrites that header (settings.trust_forwarded_for). Without such a proxy the header is caller-chosen and
    is ignored."""
    if trust_forwarded_for:
        forwarded = dict(scope.get("headers") or []).get(b"x-forwarded-for", b"").decode("latin-1").split(",")[0].strip()
        if forwarded:
            return forwarded
    return (scope.get("client") or ("unknown", 0))[0]


class SignInThrottle:
    def __init__(self, app, per_minute: int | None = None, trust_forwarded_for: bool | None = None):
        from ..config import settings
        per_minute = per_minute or settings.sign_in_per_minute
        self.trust = settings.trust_forwarded_for if trust_forwarded_for is None else trust_forwarded_for
        self.app, self.rate, self.cap = app, per_minute / 60.0, float(per_minute)
        self.buckets: dict[str, tuple[float, float]] = {}
        self.lock = threading.Lock()

    def _take(self, key: str) -> float | None:
        now = time.monotonic()
        with self.lock:
            tokens, last = self.buckets.get(key, (self.cap, now))
            tokens = min(self.cap, tokens + (now - last) * self.rate)
            if tokens < 1:
                self.buckets[key] = (tokens, now)
                return (1 - tokens) / self.rate
            self.buckets[key] = (tokens - 1, now)
            if len(self.buckets) > 10_000:          # bounded memory: forget idle clients
                self.buckets = {k: v for k, v in self.buckets.items() if now - v[1] < 120}
            return None

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path", "").startswith(SIGN_IN_PATHS):
            wait = self._take(client_address(scope, self.trust))
            if wait is not None:
                retry = str(int(wait) + 1)
                return await _reply(send, 429, "rate_limited", f"too many sign-in attempts; retry in {retry}s",
                                    [(b"retry-after", retry.encode())])
        return await self.app(scope, receive, send)
