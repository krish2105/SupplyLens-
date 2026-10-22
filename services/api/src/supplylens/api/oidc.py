"""OpenID Connect sign-in: authorization code flow with PKCE (S256), state and nonce.

Verified locally against Keycloak (infra/keycloak/realm-supplylens.json); it is a standard confidential-client flow and
has not been qualified against a corporate identity provider. The provider is the source of truth for who a user is and
which workspaces they may use: the `supplylens_roles` claim ("<workspace-slug>:<role>") replaces the user's
provider-managed memberships at every sign-in and every re-confirmation. A session is re-confirmed with the provider
(refresh-token grant) at most every `oidc_recheck_seconds`; if the provider refuses (account disabled, session ended,
user removed) the SupplyLens session is revoked on that request, and a disabled account is deactivated locally.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from urllib.parse import urlencode

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import text

from ..config import settings
from ..db import control_session
from .deps import COOKIE, SESSION_MAX_AGE, serializer

router = APIRouter(prefix="/api/v1/auth/oidc")
FLOW_COOKIE = "sl_oidc_flow"
flow_serializer = URLSafeTimedSerializer(settings.session_secret, salt="supplylens-oidc-flow")
ROLES = {"viewer", "planner", "approver", "tenant_admin"}


class OidcError(Exception):
    pass


def _fernet() -> Fernet:
    key = hashlib.sha256(("supplylens-refresh:" + settings.session_secret).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


@lru_cache(maxsize=4)
def _discovery(issuer: str) -> dict:
    r = httpx.get(issuer.rstrip("/") + "/.well-known/openid-configuration", timeout=10)
    r.raise_for_status()
    return r.json()


@lru_cache(maxsize=4)
def _jwks(uri: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(uri, cache_keys=True)


def _endpoints() -> dict:
    d = _discovery(settings.oidc_issuer)
    public = (settings.oidc_public_issuer or settings.oidc_issuer).rstrip("/")
    internal = settings.oidc_issuer.rstrip("/")
    return {"authorize": d["authorization_endpoint"].replace(internal, public), "token": d["token_endpoint"],
            "jwks": d["jwks_uri"], "end_session": d.get("end_session_endpoint", "").replace(internal, public),
            "issuer": d["issuer"]}


def _verify(token: str, *, nonce: str | None = None, audience: str | None = None) -> dict:
    ep = _endpoints()
    key = _jwks(ep["jwks"]).get_signing_key_from_jwt(token)
    issuers = {ep["issuer"], (settings.oidc_public_issuer or ep["issuer"]).rstrip("/")}
    claims = jwt.decode(token, key.key, algorithms=["RS256", "ES256"], audience=audience,
                        options={"verify_aud": audience is not None, "verify_iss": False}, leeway=30)
    if claims.get("iss", "").rstrip("/") not in {i.rstrip("/") for i in issuers}:
        raise OidcError("token issuer mismatch")
    if nonce is not None and claims.get("nonce") != nonce:
        raise OidcError("nonce mismatch")
    return claims


def grants_from(claims: dict) -> list[dict]:
    """'uci-research:planner' -> {"tenant": "uci-research", "role": "planner"}; malformed or unknown roles are dropped."""
    raw = claims.get(settings.oidc_role_claim) or []
    if isinstance(raw, str):
        raw = [raw]
    out = []
    for v in raw:
        slug, _, role = str(v).partition(":")
        if slug and role in ROLES:
            out.append({"tenant": slug, "role": role})
    return out


def _token(data: dict) -> dict:
    r = httpx.post(_endpoints()["token"], data={**data, "client_id": settings.oidc_client_id,
                                                "client_secret": settings.oidc_client_secret}, timeout=10)
    if r.status_code != 200:
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        raise OidcError(f"{body.get('error', r.status_code)}: {body.get('error_description', '')}".strip())
    return r.json()


def _require_enabled():
    if not settings.oidc_enabled:
        raise HTTPException(404, {"code": "oidc_not_configured", "message": "identity provider sign-in is not configured"})


@router.get("/login")
def login(request: Request):
    _require_enabled()
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    url = _endpoints()["authorize"] + "?" + urlencode({
        "response_type": "code", "client_id": settings.oidc_client_id, "redirect_uri": settings.oidc_redirect_uri,
        "scope": "openid email profile", "state": state, "nonce": nonce, "code_challenge": challenge,
        "code_challenge_method": "S256"})
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(FLOW_COOKIE, flow_serializer.dumps({"s": state, "n": nonce, "v": verifier}), max_age=600,
                    httponly=True, samesite="lax", secure=settings.cookie_secure, path="/api/v1/auth/oidc")
    return resp


@router.get("/callback")
def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    _require_enabled()
    if error:
        raise HTTPException(401, {"code": "oidc_denied", "message": f"the identity provider refused sign-in: {error}"})
    try:
        flow = flow_serializer.loads(request.cookies.get(FLOW_COOKIE, ""), max_age=600)
    except BadSignature:
        raise HTTPException(400, {"code": "oidc_flow_missing", "message": "sign-in expired; start again"}) from None
    if not code or not state or not secrets.compare_digest(state, flow["s"]):
        raise HTTPException(400, {"code": "oidc_state_mismatch", "message": "sign-in state did not match; start again"})
    try:
        tokens = _token({"grant_type": "authorization_code", "code": code, "redirect_uri": settings.oidc_redirect_uri,
                         "code_verifier": flow["v"]})
        idt = _verify(tokens["id_token"], nonce=flow["n"], audience=settings.oidc_client_id)
        access = _verify(tokens["access_token"])
    except (OidcError, jwt.PyJWTError, KeyError) as e:
        raise HTTPException(401, {"code": "oidc_invalid", "message": f"sign-in could not be verified: {e}"}) from e
    if not idt.get("email") or idt.get("email_verified") is False:
        raise HTTPException(403, {"code": "oidc_email_unverified", "message": "a verified email address is required"})
    sid = uuid.uuid4()
    with control_session() as s:
        uid = s.execute(text("SELECT sl_upsert_oidc_user(:sub, :e, :n)"),
                        {"sub": idt["sub"], "e": idt["email"], "n": idt.get("name") or idt["email"]}).scalar()
        s.execute(text("SELECT sl_sync_oidc_memberships(:u, CAST(:g AS jsonb))"),
                  {"u": uid, "g": json.dumps(grants_from(access) or grants_from(idt))})
        s.execute(text("INSERT INTO auth_sessions (id, user_id, oidc_subject, refresh_token_enc) VALUES (:i,:u,:s,:r)"),
                  {"i": sid, "u": uid, "s": idt["sub"],
                   "r": _fernet().encrypt(tokens["refresh_token"].encode()).decode() if tokens.get("refresh_token") else None})
    resp = RedirectResponse(settings.oidc_post_login_uri, status_code=302)
    resp.set_cookie(COOKIE, serializer.dumps({"uid": str(uid), "sid": str(sid)}), max_age=SESSION_MAX_AGE,
                    httponly=True, samesite="lax", secure=settings.cookie_secure, path="/")
    resp.delete_cookie(FLOW_COOKIE, path="/api/v1/auth/oidc")
    return resp


def confirm_session(sid: uuid.UUID) -> None:
    """Called for every request on a provider session. Raises HTTPException(401) when the session is no longer valid."""
    with control_session() as s:
        row = s.execute(text("""SELECT user_id, oidc_subject, refresh_token_enc, checked_at, revoked_at
            FROM auth_sessions WHERE id=:i"""), {"i": sid}).mappings().first()
    if row is None or row["revoked_at"] is not None:
        raise HTTPException(401, {"code": "session_revoked", "message": "session ended; sign in again"})
    if datetime.now(UTC) - row["checked_at"] < timedelta(seconds=settings.oidc_recheck_seconds):
        return
    try:
        rt = _fernet().decrypt(row["refresh_token_enc"].encode()).decode() if row["refresh_token_enc"] else None
        if rt is None:
            raise OidcError("no refresh token")
        tokens = _token({"grant_type": "refresh_token", "refresh_token": rt})
        access = _verify(tokens["access_token"])
    except (OidcError, InvalidToken, jwt.PyJWTError) as e:
        reason = str(e)
        with control_session() as s:
            s.execute(text("UPDATE auth_sessions SET revoked_at=now(), revoked_reason=:r WHERE id=:i"),
                      {"i": sid, "r": reason[:300]})
            if "disabled" in reason.lower() or "not found" in reason.lower():
                s.execute(text("SELECT sl_deactivate_oidc_user(:s)"), {"s": row["oidc_subject"]})
        raise HTTPException(401, {"code": "session_revoked",
                                  "message": "the identity provider ended this session; sign in again"}) from e
    with control_session() as s:
        s.execute(text("SELECT sl_sync_oidc_memberships(:u, CAST(:g AS jsonb))"),
                  {"u": row["user_id"], "g": json.dumps(grants_from(access))})
        s.execute(text("UPDATE auth_sessions SET checked_at=now(), refresh_token_enc=COALESCE(:r, refresh_token_enc) "
                       "WHERE id=:i"),
                  {"i": sid, "r": _fernet().encrypt(tokens["refresh_token"].encode()).decode()
                   if tokens.get("refresh_token") else None})


def revoke(sid: uuid.UUID, reason: str) -> None:
    with control_session() as s:
        s.execute(text("UPDATE auth_sessions SET revoked_at=now(), revoked_reason=:r WHERE id=:i AND revoked_at IS NULL"),
                  {"i": sid, "r": reason})


def end_session_url() -> str | None:
    if not settings.oidc_enabled:
        return None
    ep = _endpoints().get("end_session")
    return (ep + "?" + urlencode({"client_id": settings.oidc_client_id,
                                  "post_logout_redirect_uri": settings.oidc_post_login_uri})) if ep else None
