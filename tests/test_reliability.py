"""DEF-02 (atomic idempotency under concurrency) and DEF-03 (rate limits shared across processes)."""
import subprocess
import sys
import textwrap
import threading
import time
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from supplylens.api.deps import CLAIM_SECONDS, idempotent
from supplylens.api.ratelimit import take
from supplylens.authz import Actor
from supplylens.db import admin_engine, tenant_session
from supplylens.seed import tenant_id, user_id


@pytest.fixture()
def actor_demo():
    return Actor(user_id("planner@dev.supplylens.local"), tenant_id("demo"), "planner", "planner@dev.supplylens.local")


@pytest.fixture(autouse=True)
def _clean():
    with admin_engine().begin() as c:
        c.execute(text("TRUNCATE rate_limit_buckets, idempotency_keys"))
    yield


# --------------------------------------------------------------------------- DEF-02
def test_concurrent_identical_requests_execute_once(actor_demo):
    calls, results = [], []
    gate = threading.Barrier(8)

    def work():
        calls.append(1)
        time.sleep(0.4)  # long enough that every other thread arrives while this one is in flight
        return 202, {"run_id": "r1"}

    def caller():
        gate.wait()
        try:
            results.append(idempotent(actor_demo, "k-concurrent", "agent-runs", {"a": 1}, work))
        except HTTPException as e:
            results.append((e.status_code, e.detail["code"]))

    threads = [threading.Thread(target=caller) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(calls) == 1, "the operation must run exactly once"
    winners = [r for r in results if r[0] == 202]
    losers = [r for r in results if r[0] == 409]
    assert len(winners) == 1 and len(losers) == 7
    assert {code for _, code in losers} == {"idempotency_in_progress"}
    # After completion a retry replays the stored response without running again.
    code, body = idempotent(actor_demo, "k-concurrent", "agent-runs", {"a": 1}, work)
    assert code == 202 and body["idempotent_replay"] is True and len(calls) == 1


def test_failed_operation_releases_the_claim(actor_demo):
    def boom():
        raise HTTPException(422, {"code": "invalid", "message": "bad input"})

    with pytest.raises(HTTPException):
        idempotent(actor_demo, "k-fail", "r", {"x": 1}, boom)
    code, body = idempotent(actor_demo, "k-fail", "r", {"x": 1}, lambda: (200, {"ok": True}))
    assert code == 200 and body == {"ok": True}


def test_reused_key_with_different_body_is_rejected(actor_demo):
    idempotent(actor_demo, "k-reuse", "r", {"x": 1}, lambda: (200, {"ok": 1}))
    with pytest.raises(HTTPException) as e:
        idempotent(actor_demo, "k-reuse", "r", {"x": 2}, lambda: (200, {"ok": 2}))
    assert e.value.status_code == 409 and e.value.detail["code"] == "idempotency_key_reused"


def test_abandoned_claim_is_recoverable_after_its_lease(actor_demo):
    """A process that crashed mid-operation leaves IN_PROGRESS; the same request may retake it after the lease."""
    import hashlib
    import json
    rhash = hashlib.sha256(json.dumps({"x": 1}, sort_keys=True, default=str).encode()).hexdigest()
    with tenant_session(actor_demo.tenant_id) as s:
        s.execute(text("INSERT INTO idempotency_keys (tenant_id, key, route, request_hash, state, claimed_until) "
                       "VALUES (:t,'k-crash','r',:h,'IN_PROGRESS', now() + interval '60 seconds')"),
                  {"t": actor_demo.tenant_id, "h": rhash})
    with pytest.raises(HTTPException) as e:  # lease still valid: someone may still be working
        idempotent(actor_demo, "k-crash", "r", {"x": 1}, lambda: (200, {"ok": 1}))
    assert e.value.detail["code"] == "idempotency_in_progress"
    with tenant_session(actor_demo.tenant_id) as s:
        s.execute(text("UPDATE idempotency_keys SET claimed_until = now() - interval '1 second' WHERE key='k-crash'"))
    code, _ = idempotent(actor_demo, "k-crash", "r", {"x": 1}, lambda: (200, {"ok": 1}))
    assert code == 200 and CLAIM_SECONDS > 0


# --------------------------------------------------------------------------- DEF-03
def test_bucket_allows_burst_then_refills():
    t = tenant_id("demo")
    results = [take(t, "unit:u1", per_minute=60, burst=5) for _ in range(7)]
    assert results[:5] == [None] * 5 and all(isinstance(r, int) and r >= 1 for r in results[5:])
    time.sleep(1.2)  # 60/min = 1 token/s
    assert take(t, "unit:u1", per_minute=60, burst=5) is None


def test_buckets_are_independent_per_actor_and_tenant():
    for _ in range(3):
        take(tenant_id("demo"), "unit:a", 60, 3)
    assert take(tenant_id("demo"), "unit:a", 60, 3) is not None   # a exhausted
    assert take(tenant_id("demo"), "unit:b", 60, 3) is None       # b untouched
    assert take(tenant_id("uci-research"), "unit:a", 60, 3) is None  # other tenant untouched


def test_limit_holds_across_processes():
    """The bucket is shared: 2 extra OS processes plus this one together get exactly `burst` tokens."""
    burst = 12
    code = textwrap.dedent(f"""
        import sys
        from supplylens.api.ratelimit import take
        from supplylens.seed import tenant_id
        ok = sum(take(tenant_id("demo"), "xproc:u", per_minute=1, burst={burst}) is None for _ in range(10))
        print(ok)""")
    procs = [subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True,
                              env={**__import__("os").environ}) for _ in range(2)]
    mine = sum(take(tenant_id("demo"), "xproc:u", per_minute=1, burst=burst) is None for _ in range(10))
    theirs = [int(p.communicate(timeout=60)[0].strip()) for p in procs]
    assert mine + sum(theirs) == burst, f"{mine=} {theirs=}"


def test_parallel_takes_never_exceed_burst():
    t = tenant_id("demo")
    out, lock = [], threading.Lock()

    def go():
        r = take(t, "par:u", per_minute=1, burst=10)
        with lock:
            out.append(r)

    ts = [threading.Thread(target=go) for _ in range(40)]
    [x.start() for x in ts]
    [x.join() for x in ts]
    assert sum(r is None for r in out) == 10
    assert uuid.UUID(str(t))
