# Phase 2 — enterprise security hardening

**Dates:** 2026-10-23 (UTC) · **Start:** `main` @ `eaabf6b` (+ `ec6c208`, Git deploys for Vercel, done first at the owner's
request) · **Code commit:** `1813f43` · **Standards used as checklists, not certifications:** OWASP ASVS 5.0 (V1 encoding,
V2 validation, V3 web frontend, V4 API, V5 files, V6 authentication, V7 sessions, V8 authorization, V13 configuration,
V15 secure coding/dependencies, V16 logging/errors), OWASP API Security Top 10 (2023), NIST SSDF (SP 800-218).

**No security certification is claimed.** Corporate IdP qualification (EXT-01), an independent penetration test
(EXT-07), compliance certification and a production infrastructure assessment were **not performed** and stay
BLOCKED/UNVERIFIED. No intrusive testing was done against any external system; the only live checks on the hosted demo
were non-destructive (EVIDENCE P2-E15, P2-E16).

Evidence IDs `P2-E..` → [`../EVIDENCE.md`](../EVIDENCE.md); issues → [`../ISSUES.md`](../ISSUES.md); product decisions
D-061 … D-067 → root [`DECISIONS.md`](../../DECISIONS.md).

## 0. Done first: Git pushes deploy (P3-OPS-02)
Git-triggered Vercel builds failed in ~4 s on every push (`ENTRYPOINT_NOT_FOUND`: the `api` root `build/vercel-api` was
generated locally and git-ignored). Now `deploy/vercel-api/` is committed (entrypoint, dependencies pinned to `uv.lock`,
the 12 cited documents — 6 fictional, 6 simulated, all labelled), and the service's `buildCommand` runs
`scripts/vercel/build_api.py` to stage code. Proven first on a preview deploy of an exact Git export, then by the first
successful Git production build (`ec6c208`, aliased to `supplylens-self.vercel.app`) and live probes (P2-E01, P2-E02).

## 1. Controls verified in code (leads from earlier phases re-checked)
| Area | What was checked | Verdict |
|---|---|---|
| Authentication | `api/deps.py`, `routes_core.py` dev login, `api/oidc.py` (code+PKCE, state, nonce, issuer, audience on the ID token) | OIDC flow sound; dev sessions were stateless (→ SEC-P2-02); IdP outage → 500 (→ SEC-P2-08) |
| CSRF / CORS | `csrf_guard` (custom header on mutations), no CORS middleware | Sound; new test proves no `Access-Control-Allow-*` for foreign origins |
| Cookies | `set_cookie` calls | HttpOnly, SameSite=Lax, Path=/, Secure required in demo/production (config refuses otherwise); tested |
| Authorization | `authz.MATRIX`, `Actor.require`, membership re-read per request, SoD in approve/accept-remote, demo locks | Sound; existing 64-case matrix plus new cases |
| Object-level / tenancy | RLS policies, `tenant_session`, `_load` 404s | Sound; two routes answered 409 instead of 404 for foreign ids (no oracle, made consistent) |
| RLS completeness | `pg_class`/`pg_policies` for every table with `tenant_id` | All FORCE RLS with USING + WITH CHECK (new completeness test) |
| Injection | f-string SQL sites (module constants), `to_tsquery` builder, React rendering | No injection path found; no `dangerouslySetInnerHTML` |
| SSRF | outbound calls: alert webhook (operator config), OIDC issuer (operator config), Ollama URL (operator config) | No tenant-controlled destination |
| Files / parsing | CSV upload, export download (`test_export_download_cannot_escape_the_storage_root`) | Body unbounded before parse (→ SEC-P2-03); parser 500s (→ SEC-P2-10); PII stored (→ SEC-P2-07) |
| Errors | exception handlers, `str(e)` sites | Generic 500 with reference; DB error text leaked from onboarding (→ SEC-P2-04) |
| Rate limits | `ratelimit.limit` users | Costly routes limited; sign-in and admin writes not (→ SEC-P2-03) |
| Secrets / config | `config._fail_closed`, gitleaks history scan, Vercel sensitive vars | Sound after Phase 1; no secrets in Git (P2-E10) |
| Supply chain | CI workflow, hosted dependency list | Tags not SHAs, unverified download, unpinned tools, unpinned hosted deps (→ SEC-P2-06) |
| Audit | `audit_events` grants (INSERT, SELECT only for the app role) | Append-only for the app; not tamper-evident against the owner (residual) |
| Worker context | `jobs.claim` per tenant, `execute_run` under the job's tenant, per-node reauthorisation (`agent/graph.py::node`) | Sound; new tests prove a forged cross-tenant job and a revoked creator both stop |
| Test fixtures | `tests/conftest.py` TRUNCATE, `apps/web/e2e/global-setup.ts` and `helpers.ts` cancellations | No proof of a disposable target (→ SEC-P2-01) |

## 2. Findings and remediation (risk order)
| ID | Sev. | Affected | Exploitability assumptions | Remediation | Test | Residual risk |
|---|---|---|---|---|---|---|
| SEC-P2-01 | High | `tests/conftest.py`; `apps/web/e2e/global-setup.ts`, `helpers.ts` | An engineer or CI job runs a suite with a URL pointing at a real database or the hosted demo (env typo, copied command). pytest TRUNCATEs every tenant table; Playwright cancels open orders through the API | pytest refuses unless both URLs are on a local host (or `SUPPLYLENS_TEST_DB_HOST`) and name a database ending `_test`, and the environment is development/test. Playwright resets only when: loopback URL, server reports development/test, server declares itself disposable (`SUPPLYLENS_E2E_DISPOSABLE`, refused by demo/production config), runner opts in (`SUPPLYLENS_E2E_ALLOW_DESTRUCTIVE=1`); read-only runs use `SUPPLYLENS_E2E_SKIP_RESET=1` (D-065) | `test_SEC_P2_01_*` (4); P2-E07 refusal and skip runs | Scripts outside the suites (`seed_e2e_fixture.py`, load-test seeders) keep their own checks only |
| SEC-P2-02 | Medium | `api/deps.py`, `routes_core.py` | A development-session cookie is copied (shared machine, logs, proxy). Before: valid for 12 h after sign-out; no idle limit. On the public demo every visitor uses these accounts | Server-side sessions in `auth_sessions` for dev sign-ins; sign-out revokes; 2 h idle timeout (revocation committed before the 401); stateless cookies refused (D-061) | `test_SEC_P2_02_*` (6: creation, revocation, idle, legacy refusal, cookie flags, CORS) | 12 h absolute lifetime remains; no concurrent-session cap; `auth_sessions` has no retention job |
| SEC-P2-03 | Medium | `api/app.py`, `api/guards.py` (new), `routes_onboarding.py` | Unauthenticated multi-GB POST fills disk (multipart spools before auth); unlimited dev-login attempts; a tenant admin floods workspace creation or imports | 6 MB body cap as outermost ASGI middleware (declared length checked; chunked bodies buffered to the cap); sign-in throttle per client address (per process, `X-Forwarded-For` only when `trust_forwarded_for`, set for Vercel); `limit()` on import upload/validate/publish, workspace creation, membership changes (D-062) | `test_SEC_P2_03_*` (4) | Throttle is per process (Vercel instances multiply it); Vercel's own 4.5 MB request cap applies first on the hosted demo; per-tenant retrieval ceiling (security review F-05) still open |
| SEC-P2-06 | Medium | `.github/workflows/ci.yml`, `deploy/vercel-api/pyproject.toml` | A moved action tag or a tampered release asset runs in CI with repo read access; the hosted function installed the latest version of every dependency on each build | Actions pinned to commit SHAs; gitleaks tarball sha256-verified; `pip-audit==2.10.1`; hosted direct deps pinned to `uv.lock` with `build_api.py --check` in CI; Dependabot for actions, uv, npm (D-066) | CI `lint` job runs the pin check; P2-E09 | Transitive deps of the hosted function are resolved at build time; Docker base images not digest-pinned (P3-CI-01 remainder) |
| SEC-P2-07 | Medium (privacy) | `onboarding/csv_import.py` | A user uploads a file containing emails/phone numbers: they were stored verbatim, shown to viewers in the batch view and copied into an immutable quarantine table | Cells that look like personal data are replaced by a marker before storage; the row is still quarantined with the reason (D-064) | `test_P2_PRIV_01_*` | Rows stored before Phase 2 in existing databases are not rewritten; no retention policy for import rows |
| SEC-P2-04 | Low–Medium | `onboarding/service.py`, `api/routes_core.py` | Any tenant admin triggers a database error (e.g. a constraint) and reads constraint/table names or driver text in the response; integration status echoed exception text (could include connection details) | Only SQLSTATE P0001 messages raised by SupplyLens functions pass through; others are logged and replaced; integration status says "not reachable" (D-063) | `test_SEC_P2_04_*` (2) | Other routes still return validation `ValueError` texts written by the code (reviewed, no secrets) |
| SEC-P2-08 | Low | `api/oidc.py` | IdP outage or network partition: every request on an OIDC session returned an unhandled 500 | Network/JWKS errors answer 503 `identity_provider_unavailable` with Retry-After; session not revoked | Not exercised (Keycloak not running); code review only — UNVERIFIED by test | Needs a Keycloak-down test when the identity profile runs |
| SEC-P2-05 | Low | `actions/service.py::reconcile`, `routes_lifecycle.py` alert acknowledge | A foreign or unknown id returned 409 instead of 404 (same answer for both, so no existence oracle) | Both answer 404 like every other object route | `test_SEC_P2_05_*` (3: completeness, leak scan of every FORCE-RLS table, Phase 1 routes cross-tenant) | — |
| SEC-P2-10 | Low | `onboarding/csv_import.py` | Oversized field (>131,072 chars) or NUL byte crashed the request (500) | `malformed_csv` / `binary_content` 422s | `test_P3_ONB_01_*` (2) | — |
| SEC-P2-09 | Info | worker / jobs | Could a job run another tenant's work or outlive its creator's access? | No defect: jobs execute under the queue's tenant and runs reauthorise per node | `test_SEC_P2_09_*` (2) | — |

## 3. Tests and checks executed
| What | Result | Evidence |
|---|---|---|
| Phase 2 security tests | 24 passed | P2-E03 |
| Full backend suite | 398 passed, 6 skipped (Keycloak) | P2-E04 |
| Browser suite on the disposable stack | 114 passed, 2 skipped | P2-E06 |
| Destructive-setup refusal / read-only skip | refused without opt-in; 15 layout tests passed with skip | P2-E07 |
| ruff, lockfile, hosted pin check, contracts, tsc | pass | P2-E05, P2-E08 |
| gitleaks (history), pip-audit, npm audit (prod) | no leaks; no known vulnerabilities; 0 vulnerabilities | P2-E09, P2-E10 |
| Git deploy + live probes | Ready from Git; revoked cookie 401; lockdown 403 | P2-E01, P2-E02, P2-E15, P2-E16 |
| CI on `1813f43` | 8/8 jobs success | P2-E13 |

## 4. Not performed (must stay BLOCKED/UNVERIFIED)
Corporate IdP qualification; penetration test; compliance certification; production infrastructure review; Keycloak
tests (container not running); DAST against the hosted demo; Docker image scanning (daemon not running); backup
encryption review (local WAL archive is unencrypted; no production backups exist).

## 5. Remaining work (checkpoint)
1. Per-tenant retrieval ceiling and admission control (security review F-05, P2-PERF-01).
2. Distributed sign-in throttle (database- or edge-backed) for multi-instance hosting.
3. Retention jobs for `auth_sessions`, `import_rows`, `web_vitals`, alerts; documented retention periods.
4. Tamper-evident audit (hash chain or external append-only sink) — the owner role can still rewrite history.
5. CSP without `'unsafe-inline'` (nonces) — P3-SEC-03 remainder.
6. Docker base-image digest pins and image scanning (P3-CI-01 remainder).
7. Owner actions: scope Neon variables (P1-SEC-02 residual); require `e2e` in branch protection once P2-QA-02 is fixed.

## Status update (2026-10-23, at hand-over — `550b427`)
- CI on `1813f43`: 8/8 success; the security fixes are live from a Git deploy.
- Dependabot opened 7 PRs (actions v7/v8, setup-uv v10, TypeScript 7, web-vitals 6). None merged (PD-013).
- §5 remaining work is unchanged and is mapped to phases in `../PROGRESS.md`.
