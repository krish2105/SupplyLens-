# Local identity provider (Keycloak) — test only

This realm exists to exercise SupplyLens' OIDC sign-in end to end on a laptop. Every secret and password in
`realm-supplylens.json` is a **published local test value**; never reuse it anywhere else.

```bash
docker compose --profile identity up -d keycloak        # http://localhost:8180 (admin / admin, local only)
```

Then start the API with:

```bash
SUPPLYLENS_OIDC_ISSUER=http://localhost:8180/realms/supplylens \
SUPPLYLENS_OIDC_CLIENT_ID=supplylens-web \
SUPPLYLENS_OIDC_CLIENT_SECRET=supplylens-local-only-client-secret \
uv run uvicorn supplylens.api.app:app --port 8000
```

Test users (`kc.planner`, `kc.approver`, `kc.viewer`) carry a `supplylens_roles` attribute such as
`demo:approver`; the client maps it into ID and access tokens. Changing the attribute or disabling the user in the
Keycloak admin console takes effect at the next session re-confirmation (`SUPPLYLENS_OIDC_RECHECK_SECONDS`, 60 s).

What is verified: code flow with PKCE S256, state and nonce, ID-token signature/issuer/audience, role-claim mapping,
role change and deactivation propagating to an open session (`tests/test_oidc_keycloak.py`). What is not: any corporate
IdP, SCIM provisioning, MFA policy, TLS termination.
