"""The session cookie lives exactly as long as the session it carries (owner report 2026-11-10, FE-P8-07).

A development session ends on the server after two hours unused, but its cookie used to live twelve hours in the browser.
A returning visitor then still sent a dead cookie, so the web app could not send them to sign-in at once (the proxy only
sees whether a cookie exists) and drew an empty dashboard while a cold API took seconds to answer 401. Now the cookie's
Max-Age follows the idle window (refreshed when the session is used, never past the absolute lifetime), and a response
that finds the session dead deletes the cookie.
"""
import re
import time

import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from sqlalchemy import text

from supplylens.api.app import app
from supplylens.api.deps import COOKIE, DEV_IDLE_SECONDS, SESSION_MAX_AGE, TOUCH_SECONDS, serializer
from supplylens.db import admin_engine
from supplylens.seed import dev_email
from supplylens.simulation import demo

H = {"X-Requested-With": "supplylens"}
DEMO = {**H, "X-SupplyLens-Tenant": "demo"}


@pytest.fixture()
def demo_tenant(clean_db, tenant_b):
    demo.load(tenant_b)
    return tenant_b


def _set_cookie(r) -> str | None:
    """The sl_session Set-Cookie header of a response, if any."""
    found = [v for k, v in r.headers.multi_items() if k.lower() == "set-cookie" and v.startswith(f"{COOKIE}=")]
    assert len(found) <= 1, found
    return found[0] if found else None


def _max_age(header: str) -> int:
    m = re.search(r"max-age=(-?\d+)", header, re.I)
    assert m, header
    return int(m.group(1))


def _login(role="viewer"):
    c = TestClient(app)
    r = c.post("/api/v1/auth/dev-login", json={"email": dev_email(role)}, headers=H)
    assert r.status_code == 200, r.text
    return c, r


def _age_session(c, seconds: int):
    sid = serializer.loads(c.cookies[COOKIE])["sid"]
    with admin_engine().begin() as conn:
        conn.execute(text("UPDATE auth_sessions SET checked_at = now() - make_interval(secs => :s) WHERE id = :i"),
                     {"s": seconds, "i": sid})


def test_a_dev_sign_in_cookie_lives_as_long_as_the_idle_window(demo_tenant):
    _, r = _login()
    assert _max_age(_set_cookie(r)) == DEV_IDLE_SECONDS


def test_using_the_session_refreshes_the_cookie_with_the_same_value(demo_tenant):
    c, _ = _login()
    value = c.cookies[COOKIE]
    _age_session(c, TOUCH_SECONDS + 30)                      # last use recorded a while ago: this request touches it
    r = c.get("/api/v1/overview", headers=DEMO)
    assert r.status_code == 200
    refreshed = _set_cookie(r)
    assert refreshed is not None and refreshed.startswith(f"{COOKIE}={value};")     # same signed value: lifetime unchanged
    assert DEV_IDLE_SECONDS - 5 <= _max_age(refreshed) <= DEV_IDLE_SECONDS
    assert "httponly" in refreshed.lower() and "samesite=lax" in refreshed.lower() and "path=/" in refreshed.lower()


def test_a_request_within_a_minute_of_the_last_does_not_rewrite_the_cookie(demo_tenant):
    c, _ = _login()
    r = c.get("/api/v1/overview", headers=DEMO)
    assert r.status_code == 200 and _set_cookie(r) is None


def test_the_refresh_never_extends_past_the_absolute_lifetime(demo_tenant, monkeypatch):
    c, _ = _login()
    sid = serializer.loads(c.cookies[COOKIE])["sid"]
    uid = serializer.loads(c.cookies[COOKIE])["uid"]
    issued = time.time() - (SESSION_MAX_AGE - 600)          # signed 11 h 50 min ago: 10 minutes of lifetime left
    monkeypatch.setattr(TimestampSigner, "get_timestamp", lambda self: int(issued))
    old = serializer.dumps({"uid": uid, "sid": sid, "kind": "dev"})
    monkeypatch.undo()
    late = TestClient(app)                                  # a browser holding the backdated cookie of the same session
    late.cookies.set(COOKIE, old)
    _age_session(late, TOUCH_SECONDS + 30)
    r = late.get("/api/v1/overview", headers=DEMO)
    assert r.status_code == 200
    assert 0 < _max_age(_set_cookie(r)) <= 600


def test_an_expired_session_deletes_its_cookie(demo_tenant):
    c, _ = _login()
    _age_session(c, DEV_IDLE_SECONDS + 600)
    r = c.get("/api/v1/me")
    assert r.status_code == 401 and r.json()["code"] == "session_expired"
    gone = _set_cookie(r)
    assert gone is not None and _max_age(gone) <= 0


def test_a_revoked_session_deletes_its_cookie_and_sign_out_is_not_undone(demo_tenant):
    c, _ = _login()
    stolen = c.cookies[COOKIE]
    out = c.post("/api/v1/auth/logout", headers=H)
    assert out.status_code == 200 and _max_age(_set_cookie(out)) <= 0          # sign-out deletes it, nothing re-sets it
    replay = TestClient(app)
    replay.cookies.set(COOKIE, stolen)
    r = replay.get("/api/v1/me")
    assert r.status_code == 401 and _max_age(_set_cookie(r)) <= 0


def test_a_request_without_a_cookie_sets_none(demo_tenant):
    r = TestClient(app).get("/api/v1/me")
    assert r.status_code == 401 and _set_cookie(r) is None
