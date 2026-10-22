# Security verification record (BUS-021)

**What this is.** An engineering self-review of the code on branch `feat/close-p0-gaps`, with the automated scans that now
run in CI. **What it is not.** It is not an independent penetration test, it does not cover a production deployment, and it
does not cover real identity (OIDC), a real ERP connector or any customer data: none of those exist in this build.
BUS-021 asks that no unresolved critical or unmitigated high-severity finding remains for the release; the table below
states which findings are open and why. A third-party review before any pilot with real users is still advisable.

Date: 2026-10-21. Reviewer: the engineering agent that wrote the changes (so this is not independent of the author).

## Requirements applied (versioned)

| Source | Version | Applied as |
|---|---|---|
| Project security specification | `docs/specs/02_architecture_and_agents.md` (SEC-01 … SEC-n) and `docs/acceptance/acceptance_register.csv` | Controls and tests below |
| OWASP ASVS | 4.0.3 (levels 1–2 headings used as a checklist, not a certification) | Section "Checklist" |
| CWE Top 25 | 2024 | Used to pick the scanner rule families |

## Automated verification (CI: `.github/workflows/ci.yml`)

| Check | Tool | Result at this commit |
|---|---|---|
| Static analysis, correctness + security rules | `ruff` with the bandit-derived `S` rules enabled (config in `pyproject.toml`) | clean; 62 `S` findings triaged (see F-08), 0 left unexplained |
| Secrets in the working tree and in all 24 commits | `gitleaks` 8.21.2, config `.gitleaks.toml` | no leaks; the only allow-listed strings are the published development credentials |
| Python dependency advisories | `pip-audit` over the locked set (`uv export`), live OSV/PyPI advisory data | no known vulnerabilities in 330 pinned packages |
| JavaScript dependency advisories | `npm audit --omit=dev --audit-level=high` | 0 vulnerabilities |
| Lockfile integrity | `uv lock --check` | passes |
| Isolation and authorization tests | `tests/test_security_matrix.py` (64 cases), `tests/test_db_rls.py`, `tests/test_security_hardening.py`, `tests/test_lifecycle.py` | pass |

Advisory databases change without a commit, so CI also runs on a weekly schedule.

## Findings

Severity is the reviewer's judgement of impact if exploited in a production deployment of this build.

| ID | Severity | Finding | Status |
|---|---|---|---|
| F-01 | Medium | `assert` was the only guard on the table names interpolated into SQL during tenant deletion; Python strips asserts under `-O`. The names come from the PostgreSQL catalogue, not users, so exploitability was low. | **Fixed**: explicit `raise` (`lifecycle.py`). |
| F-02 | Low | `X-Trace-Id` from the caller was echoed into the response and the access log unvalidated (log forging / header noise). | **Fixed**: accepted only if 8–64 hex/dash characters, else a fresh id is generated (`api/app.py`). |
| F-03 | Low | Alert webhook signature covered only the body, so a captured delivery could be replayed. | **Fixed**: `X-SupplyLens-Timestamp` is signed with the body (`"<ts>.<body>"`); receivers should reject deliveries older than a few minutes and de-duplicate on `Idempotency-Key`. Test: `test_webhook_delivery_is_signed_retried_and_recorded`. |
| F-04 | Medium | **Availability.** Under row-level security the full-text GIN index cannot be used (the `@@` operator is not leakproof, so PostgreSQL will not evaluate it before the policy), and after a driver's fifth use of a prepared statement PostgreSQL switched retrieval to a generic plan that re-parsed the search text and query vector for every row. Together these made one authenticated search cost 5–8 s of database time at 100,000 chunks, a cheap way for one user to exhaust the database. | **Fixed / reduced**: custom plans forced (`db.py`, test `test_db_config.py`), inline storage for the searched columns (migration 0006). **Remaining**: lexical search still scans the tenant's chunks (0.2–0.3 s CPU at 100,000). See `docs/operations/load-test.md`. |
| F-05 | Medium | Search cost is high enough (≈0.7 core-second per request at 100,000 chunks) that the per-user limit (120/min) lets a handful of accounts saturate a small database. There is no per-tenant ceiling. | **Open, accepted for the current dev-account build.** Add a tenant-wide bucket before real multi-user use. |
| F-06 | Medium | Sessions are stateless signed cookies. Logout deletes the cookie but a captured cookie stays valid until it expires (`SESSION_MAX_AGE`). | **Open, accepted.** Sign-in is development accounts only and is switched off by `SUPPLYLENS_DEV_AUTH=false` (the process then refuses to start with default secrets, `test_refuses_to_start_without_dev_auth_and_with_default_secrets`). Real sign-in (OIDC, server-side sessions, revocation) is BUS-012/022 and needs an identity provider the owner must choose. |
| F-07 | Low | `/auth/dev-login` has no rate limit. | **Open, accepted** (same reason as F-06; the route does not exist when dev auth is off). |
| F-08 | Info | 62 `S` findings: 30 `S608` (SQL built with f-strings), 12 `S603`/7 `S607` (subprocess), 6 `S310` (URL open), others. | **Triaged.** Every `S608` site interpolates a module constant, a fixed filter fragment or a catalogue identifier checked against `^[a-z_][a-z0-9_]*$`; every value is a bound parameter. Subprocess calls use an argument list with a fixed interpreter and a hash-verified artifact path (no shell). Per-file exceptions are listed in `pyproject.toml` so a new file with the same pattern is still flagged. |
| F-09 | Info | CSP allows `'unsafe-inline'` for scripts and styles because Next.js inlines hydration scripts. | **Accepted.** No user-supplied HTML is rendered (React escapes), `object-src 'none'`, `frame-ancestors 'none'`, `connect-src 'self'`. A nonce-based CSP via middleware is the upgrade path. |
| F-10 | Info | Alert webhook destination is operator configuration, not tenant-supplied; `httpx` does not follow redirects by default; timeout 5 s. | No SSRF path from tenant input. |

**Unresolved critical or high findings: none.** Open mediums: F-05, F-06 (accepted with the stated conditions).

## Controls verified (with the test that proves each)

| Control | Evidence |
|---|---|
| Forced row-level security on every tenant table; app role is a non-owner without `BYPASSRLS` | `test_db_rls.py::test_app_role_is_not_owner_and_cannot_bypass_rls`, `…tenant_rows_invisible_across_tenants`, `…missing_tenant_context_sees_nothing`, `…cannot_write_into_other_tenant` |
| Tenant context never leaks between pooled connections | `test_db_rls.py::test_tenant_context_does_not_leak_between_pooled_transactions` (GUC is transaction-local) |
| 64 cross-tenant and cross-role denial cases over APIs, streams, retrieval, downloads | `test_security_matrix.py` |
| Audit log append-only for the app role | `test_db_rls.py::test_app_role_cannot_write_control_plane_or_rewrite_audit`; `test_rehearsals.py::test_rollback_to_previous_release_keeps_operational_records_and_audit` |
| CSRF: mutations need `X-Requested-With: supplylens`; workspace-in-query only for GET | `test_missing_csrf_header_blocks_mutation`, `test_query_param_workspace_not_accepted_for_mutations` |
| API responses not cacheable or sniffable | `test_security_hardening.py::test_api_responses_are_not_cacheable_or_sniffable` |
| CSV/audit export neutralises spreadsheet formulas | `test_csv_cells_cannot_start_a_formula`, `test_audit_export_neutralises_formula_in_user_controlled_fields` |
| Export download cannot escape the storage root | `test_export_download_cannot_escape_the_storage_root` |
| Refuses to start with default secrets when dev auth is off | `test_refuses_to_start_without_dev_auth_and_with_default_secrets` |
| Concurrent identical requests execute once (DEF-02); rate limits shared across processes (DEF-03) | `test_reliability.py` |
| Tenant deletion needs typed slug, a downloaded verified export and a reason; certificate kept; the SECURITY DEFINER finalizer refuses to act outside the caller's tenant or on non-customer workspaces | `test_lifecycle.py::test_deletion_requires_confirmation_and_a_downloaded_export`, `…full_deletion_removes_everything_and_leaves_a_certificate` |
| Untrusted model artifacts refused (hash check) | `test_forecast_service.py::test_untrusted_artifact_is_refused` |
| Retrieved document text is labelled untrusted in API responses; the agent is deterministic, so no language model reads it as instructions | `untrusted_content: true` on document responses (`GET /documents/versions/{id}`) |

## ASVS 4.0.3 checklist (headings only; L1/L2 where applicable to this build)

| Area | State |
|---|---|
| V2 Authentication | **Not met for production**: dev accounts only (F-06, F-07). |
| V3 Session management | Partially: HttpOnly, SameSite=Lax, `Secure` when dev auth is off; no server-side revocation (F-06). |
| V4 Access control | Met for the implemented roles; permission matrix is not owner-approved (BUS-011/019, blocked on the owner). |
| V5 Validation, sanitisation | Met: typed request models, parameterised SQL, formula-injection guard on CSV. |
| V7 Error handling and logging | Met: structured errors without stack traces; trace id on every response (F-02). |
| V8 Data protection | Cache-Control `no-store` on API; secrets validator; no secrets in history. At-rest encryption is deployment-level (not in this repository). |
| V9 Communications | Out of scope here (TLS terminates at the deployment edge). |
| V10 Malicious code | Dependency and secret scans in CI; lockfiles enforced. |
| V12 Files and resources | Export path confinement tested; no user file upload endpoint. |
| V13 API | Response models validated against the schema (`test_contract_responses.py`); rate limits on costly routes. |
| V14 Configuration | Security headers on the web tier; CSP caveat F-09. |

## Not covered

Penetration testing, fuzzing, threat modelling with a business owner, infrastructure hardening, supply-chain provenance
(SBOM/signing), and anything that depends on real identity or a real ERP. These are tracked as open in the acceptance register.
