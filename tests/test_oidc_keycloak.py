"""OIDC sign-in against a real local Keycloak (infra/keycloak/realm-supplylens.json). Skipped when it is not running.

Covers: authorization code + PKCE (S256) with state and nonce, ID-token verification, role-claim -> membership mapping,
a role change and a deactivation in the provider reaching an already open SupplyLens session, logout revocation, and the
production profile refusing development sign-in. Passwords below are the realm file's published local test values.
"""
import re
import urllib.parse

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from supplylens.api.app import app
from supplylens.config import Settings, settings
from supplylens.db import admin_engine

KC = "http://localhost:8180"
ISSUER = f"{KC}/realms/supplylens"
H = {"X-Requested-With": "supplylens"}


def _keycloak_up() -> bool:
    try:
        return httpx.get(f"{ISSUER}/.well-known/openid-configuration", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _keycloak_up(), reason="local Keycloak not running (infra/keycloak/README.md)")


@pytest.fixture()
def oidc(monkeypatch):
    monkeypatch.setattr(settings, "oidc_issuer", ISSUER)
    monkeypatch.setattr(settings, "oidc_client_id", "supplylens-web")
    monkeypatch.setattr(settings, "oidc_client_secret", "supplylens-local-only-client-secret")
    monkeypatch.setattr(settings, "oidc_redirect_uri", "http://testserver/api/v1/auth/oidc/callback")
    monkeypatch.setattr(settings, "oidc_post_login_uri", "http://testserver/")
    monkeypatch.setattr(settings, "oidc_recheck_seconds", 0)
    yield


def admin_token() -> str:
    r = httpx.post(f"{KC}/realms/master/protocol/openid-connect/token",
                   data={"grant_type": "password", "client_id": "admin-cli", "username": "admin", "password": "admin"})
    return r.json()["access_token"]


def kc_user(username: str) -> dict:
    t = admin_token()
    return httpx.get(f"{KC}/admin/realms/supplylens/users", params={"username": username, "exact": "true"},
                     headers={"Authorization": f"Bearer {t}"}).json()[0]


def kc_update(username: str, **changes) -> None:
    u = kc_user(username)
    t = admin_token()
    body = {**u, **changes}
    r = httpx.put(f"{KC}/admin/realms/supplylens/users/{u['id']}", json=body, headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 204, r.text


def sign_in(username: str, password: str) -> TestClient:
    """Drive the real browser flow: SupplyLens -> Keycloak login form -> callback -> session cookie."""
    c = TestClient(app, follow_redirects=False)
    start = c.get("/api/v1/auth/oidc/login")
    assert start.status_code == 302
    auth_url = start.headers["location"]
    q = urllib.parse.parse_qs(urllib.parse.urlparse(auth_url).query)
    assert q["code_challenge_method"] == ["S256"] and q["state"] and q["nonce"]
    with httpx.Client(follow_redirects=False) as kc:
        form = kc.get(auth_url)
        action = re.search(r'action="([^"]+)"', form.text).group(1).replace("&amp;", "&")
        # Keycloak marks its cookies Secure even on http://localhost; browsers still send them to localhost, httpx does not
        jar = "; ".join(f"{c.name}={c.value}" for c in kc.cookies.jar)
        done = kc.post(action, data={"username": username, "password": password, "credentialId": ""},
                       headers={"Cookie": jar})
        assert done.status_code == 302, done.text[:300]
        back = urllib.parse.urlparse(done.headers["location"])
    cb = c.get(back.path + "?" + back.query)
    assert cb.status_code == 302, cb.text
    return c


def memberships(c) -> dict:
    me = c.get("/api/v1/me")
    assert me.status_code == 200, me.text
    return {m["slug"]: m["role"] for m in me.json()["memberships"]}


def test_code_flow_with_pkce_maps_role_claims_to_memberships(oidc):
    kc_update("kc.approver", enabled=True, attributes={"supplylens_roles": ["demo:approver"]})
    c = sign_in("kc.approver", "local-test-approver-pass")
    assert memberships(c) == {"demo": "approver"}
    with admin_engine().connect() as conn:
        src = conn.execute(text("""SELECT m.source FROM memberships m JOIN users u ON u.id = m.user_id
            WHERE u.email = 'kc.approver@supplylens.test'""")).scalar()
    assert src == "oidc"


def test_role_change_in_the_provider_reaches_an_open_session(oidc):
    kc_update("kc.planner", enabled=True, attributes={"supplylens_roles": ["uci-research:planner", "demo:planner"]})
    c = sign_in("kc.planner", "local-test-planner-pass")
    assert memberships(c) == {"uci-research": "planner", "demo": "planner"}
    kc_update("kc.planner", attributes={"supplylens_roles": ["demo:viewer"]})
    assert memberships(c) == {"demo": "viewer"}                     # re-confirmed on this request (recheck 0 s)
    kc_update("kc.planner", attributes={"supplylens_roles": ["uci-research:planner", "demo:planner"]})


def test_deactivation_in_the_provider_ends_the_session(oidc):
    kc_update("kc.viewer", enabled=True, attributes={"supplylens_roles": ["demo:viewer"]})
    c = sign_in("kc.viewer", "local-test-viewer-pass")
    assert memberships(c) == {"demo": "viewer"}
    kc_update("kc.viewer", enabled=False)
    try:
        r = c.get("/api/v1/me")
        assert r.status_code == 401 and r.json()["code"] == "session_revoked"
        with admin_engine().connect() as conn:
            active = conn.execute(text("SELECT active FROM users WHERE email='kc.viewer@supplylens.test'")).scalar()
        assert active is False
        assert c.get("/api/v1/me").status_code == 401                # stays revoked
    finally:
        kc_update("kc.viewer", enabled=True)


def test_logout_revokes_the_server_side_session(oidc):
    kc_update("kc.viewer", enabled=True)
    c = sign_in("kc.viewer", "local-test-viewer-pass")
    cookie = c.cookies.get("sl_session")
    assert c.post("/api/v1/auth/logout", headers=H).status_code == 200
    replay = TestClient(app)
    replay.cookies.set("sl_session", cookie)
    assert replay.get("/api/v1/me").status_code == 401             # a copied cookie is useless after logout


def test_tampered_state_is_refused(oidc):
    c = TestClient(app, follow_redirects=False)
    c.get("/api/v1/auth/oidc/login")
    r = c.get("/api/v1/auth/oidc/callback?code=x&state=forged")
    assert r.status_code == 400 and r.json()["code"] == "oidc_state_mismatch"


def test_production_profile_refuses_development_sign_in():
    with pytest.raises(ValueError, match="production profile refused"):
        Settings(environment="production", dev_auth=True)
    ok = Settings(environment="production", dev_auth=False, session_secret="x" * 40, alert_webhook_secret="y" * 40,
                  database_url="postgresql+psycopg://app:s3cret@db/sl", admin_database_url="postgresql+psycopg://own:s3c@db/sl",
                  cookie_secure=True, oidc_issuer=ISSUER, oidc_client_id="c", oidc_client_secret="s")
    assert not ok.dev_login_available
