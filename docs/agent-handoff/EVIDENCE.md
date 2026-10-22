# Agent handoff — evidence log

Every row is a command that was actually executed, with its observed result. Rows are appended by phase; never edit
an old row (add a new one that supersedes it). Earlier project evidence (sessions 1–4) is in the root
[`EVIDENCE_INDEX.md`](../../EVIDENCE_INDEX.md) (E-01 … E-50) and was **not** re-run unless a row below says so.

## Phase 0 — baseline (2026-10-22, UTC)

**Repository state:** `main` @ `9fcbedb19b0831ad2599b5291569dfae309d5b6e` (= `origin/main`), working tree clean before
Phase 0; 44 commits; 399 tracked files. Remote `https://github.com/krish2105/SupplyLens-.git`.

**Environment:** macOS 27.0 (Darwin 27.0.0) arm64, 12 CPU, 24 GiB; uv 0.11.18; Python 3.12.13 (`.venv`);
Node v26.10.0, npm 11.19.1; PostgreSQL 17.11 (Homebrew) accepting connections on localhost:5432; Ollama present and
answering (worker log shows `POST /api/embed 200`); gitleaks, gh, vercel CLIs present; **Docker daemon not running**
(colima socket missing).

| ID | Check | Command (repo root unless noted) | Result | Notes |
|---|---|---|---|---|
| P0-E01 | Git state | `git rev-parse HEAD; git status --porcelain; git branch -a` | `9fcbedb…`, clean, only `main` | — |
| P0-E02 | Lockfile | `uv lock --check` | exit 0 ("Resolved 111 packages") | — |
| P0-E03 | Python lint + security rules | `uv run ruff check .` | exit 0, "All checks passed!" | Rule set in `pyproject.toml` (E4/E7/E9/F/I/UP/B/S/RUF100); 7 files carry reviewed per-file S608/S603 ignores |
| P0-E04 | Backend tests | `uv run pytest -q -p no:cacheprovider` | **336 passed, 6 skipped** in 82.7 s, exit 0 | DB `supplylens_test` (local PG 17.11). The 6 skips are `tests/test_oidc_keycloak.py` (Keycloak not running). README says 296, PROJECT_STATUS says 330 → doc drift (ISSUES P3-DOC-01) |
| P0-E05 | API contract drift | `./scripts/check_contracts.sh` | "contracts match", exit 0 | — |
| P0-E06 | TypeScript | `(cd apps/web && npx tsc --noEmit)` | exit 0 | No ESLint configured for the web app (ISSUES P2-FE-03) |
| P0-E07 | Web production build | `(cd apps/web && NEXT_DIST_DIR=.next-build npx next build)` | exit 0; 17 static routes (15 app screens + login + not-found) | Next.js 16.4.2 Turbopack |
| P0-E08 | Secret scan (full history) | `gitleaks detect --source . --redact --config .gitleaks.toml` | 43 commits scanned, "no leaks found", exit 0 | Local gitleaks version, not CI's pinned 8.21.2 |
| P0-E09 | Python advisories | `uv export --frozen … \| sed 's/+cpu//' > req.txt; uvx pip-audit --requirement req.txt --no-deps --disable-pip --strict` | "No known vulnerabilities found", exit 0 | Advisory data as of 2026-10-22 |
| P0-E10 | JS advisories (prod tree) | `npm --prefix apps/web audit --omit=dev --audit-level=high` | "found 0 vulnerabilities", exit 0 | — |
| P0-E11 | Isolated E2E stack | `CREATE DATABASE supplylens_p0e2e`, `CREATE EXTENSION vector`, `alembic upgrade head`, `python -m supplylens.bootstrap` (UCI skipped via `SUPPLYLENS_UCI_ZIP=/nonexistent`), `scripts/seed_e2e_fixture.py`; API :8000, worker, `next start` :3100 on that DB, storage `storage_p0e2e` | Demo loaded (6 docs); fixture 36 products / 13,171 sales rows; `/health` ok | Decision PD-002. Started from local, git-excluded launch configs `p0-api`, `p0-worker`, `p0-web` |
| P0-E12 | Browser E2E (full) | `(cd apps/web && npx playwright test --reporter=list)` (6 workers, desktop + mobile projects) | **116 tests: 113 passed, 1 failed, 2 skipped**, 1.1 min, exit 1 | Failure: `e2e/consistency.spec.ts:59` "run … ended SUCCEEDED without a draft". Skips: `journey.spec.ts:87` (replay guard, needs trained model) and mobile `a11y.spec.ts:83` |
| P0-E13 | E2E failure isolation | `npx playwright test e2e/consistency.spec.ts --project=desktop` | 5 passed, exit 0 | Order-dependent: 5 specs share the Demo reference SKU; a parallel test's reconciled order becomes open supply, so the run proposes nothing (ISSUES P2-QA-01) |
| P0-E14 | RLS coverage | `psql -d supplylens_test -c "select … relrowsecurity, relforcerowsecurity …"` | 38 of 44 public tables ENABLE + FORCE RLS; the 6 without: `alembic_version, auth_sessions, memberships, tenant_deletions, tenants, users` | Policies `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid` USING + WITH CHECK. README says 34 tables, PROJECT_STATUS/TASKS say 30 (P3-DOC-01) |
| P0-E15 | Role flags | `select rolname, rolsuper, rolbypassrls from pg_roles where rolname like 'supplylens%'` | `supplylens_owner f f`, `supplylens_app f f` | App role grants on control plane: SELECT on users/memberships/tenants/tenant_deletions; INSERT,SELECT on audit_events |
| P0-E16 | Stuck-job probe | Python probe on `supplylens_test`: insert `jobs` row `RUNNING`, attempts 3/3, lease expired 1 h ago; call `jobs.claim()` | `claim -> None`; row still `RUNNING`, owner `dead-worker` | No other code path finalizes it (grep `max_attempts`). Probe row deleted (ISSUES P2-REL-01) |
| P0-E17 | CI on HEAD | `gh run view 39813602236 --json jobs` | **success**: lint, secrets-and-dependencies, backend, contracts-and-web, e2e, pitr-drill, compose-smoke, acceptance-evidence (8 jobs) | Previous 4 pushes failed e2e/acceptance-evidence; 2 cancelled. PROJECT_STATUS says "7 jobs" |
| P0-E18 | Hosted demo liveness | `curl https://supplylens-self.vercel.app/health` | 200 `{"status":"ok","database":"ok"}` in 0.48 s | — |
| P0-E19 | Hosted demo headers | `curl -D - https://supplylens-self.vercel.app/login` | CSP (script-src `'self' 'unsafe-inline'`), HSTS preload, XFO DENY, nosniff, Referrer-Policy, Permissions-Policy | `'unsafe-inline'` is accepted risk F-09 in `docs/security/security_review.md` |
| P0-E20 | Hosted demo identity | `curl …/api/v1/auth/config`; `curl …/api/v1/auth/dev-users` | `environment: demo`, `dev_login: true`, `oidc: false`; 5 public passwordless accounts incl. `tenant_admin@dev.supplylens.local` | Basis of ISSUES P0-SEC-01. Destructive actions not exercised (PD-004) |
| P0-E21 | Hosted setup endpoint | `curl -X POST …/api/v1/internal/setup/schema` (no token) | 404 | Cannot distinguish "router absent" from "token check failed" → whether `SUPPLYLENS_SETUP_TOKEN` is still set is UNVERIFIED |

## Not run in Phase 0 (and why)

| Check | Reason | Substitute evidence |
|---|---|---|
| `docker compose up -d --build` smoke | Docker daemon not running locally (PD-003) | CI job `compose-smoke` passed on HEAD (P0-E17) |
| `./scripts/pitr_drill.sh`, `./scripts/backup_restore_drill.sh` | Long-running cluster rehearsals; not needed to establish code baseline | CI job `pitr-drill` passed on HEAD; root EVIDENCE_INDEX records local runs |
| Load test (`scripts/loadtest/*`) | Needs the 1M-row reference dataset and a declared 8 vCPU profile | `docs/operations/load-test.md` (4 vCPU sandbox, session 3) — not re-verified |
| Keycloak OIDC tests (6) | Keycloak container not running | Root PROJECT_STATUS claims 6/6 passed earlier — UNVERIFIED this phase |
| Research studies (F1/S1/R1/R2/C1/AGT/InventoryBench) | Hours of compute; raw data and model artifacts are local-only | Committed `artifacts/experiments/*/metrics.json` — numbers not recomputed |
| Real ERP, corporate IdP, pilot users | Do not exist (external blockers) | — |
| Field Web Vitals / manual screen-reader pass | Need real users / a person | — |

## Validation limitations
- All results are from one developer machine plus GitHub-hosted CI; no staging or production environment exists
  apart from the public hosted demo.
- The E2E data is the synthetic fixture, not the real UCI workspace.
- Three delegated read-only code reviews (planning/ML, web, retrieval/agent/onboarding) informed ISSUES.md; every finding carried
  into ISSUES.md is labelled VERIFIED only where the file and line were re-read by the auditing session.
