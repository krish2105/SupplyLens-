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

## Phase 1 — core correctness and procurement safety (2026-10-22/23, UTC)

**Starting point:** `main` @ `8171994` (Phase 0 handoff). **Code commit:** `037e42b`. Environment as in Phase 0.

| ID | Check | Command | Result | Notes |
|---|---|---|---|---|
| P1-E01 | Lint | `uv run ruff check .` | "All checks passed!" | After hoisting test imports (no new `noqa`) |
| P1-E02 | Lockfile / contracts / types | `uv lock --check`; `./scripts/update_contracts.sh` then `./scripts/check_contracts.sh`; `(cd apps/web && npx tsc --noEmit)` | pass; contract regenerated (69 paths: `accept-remote`, `ChecksRef.warnings`, `ScenarioTerms.excluded_for_conflict`) | — |
| P1-E03 | Phase 1 regression tests | `uv run pytest -q tests/test_phase1_correctness.py` | **38 passed** | Covers every fixed P0/P1/P2 (test names carry the issue IDs) |
| P1-E04 | Full backend suite | `uv run pytest -q -p no:cacheprovider` | **374 passed, 6 skipped** in 89.4 s | Skips = Keycloak OIDC tests (not running). Phase 0 baseline was 336 passed |
| P1-E05 | Migration rehearsals | `uv run pytest -q tests/test_rehearsals.py` | 7 passed | Head constant updated to 0009; rollback 0009→0008→0007 and back keeps all records |
| P1-E06 | Migration 0009 on the test DB | `alembic upgrade head`; `downgrade 0008`; `upgrade head` on `supplylens_test` | version 0009; index `actions_one_draft_per_run_supplier` present | Pre-check: 0 duplicate drafts per run+supplier in `supplylens`, `supplylens_test`, `supplylens_p0e2e` |
| P1-E07 | Web build | `NEXT_DIST_DIR=.next-build npx next build` | pass, 17 routes | — |
| P1-E08 | Browser E2E (isolated DB at 0009) | fresh `supplylens_p0e2e` + bootstrap + `seed_e2e_fixture.py`; API/worker/`next start`; `npx playwright test` | **114 passed, 2 skipped, 0 failed** (1.1 min) | Same 2 skips as Phase 0 |
| P1-E09 | E2E repeat | second full `npx playwright test` | **114 passed, 2 skipped** | The Phase 0 order-dependent failure (P2-QA-01) did not recur in 2 runs; its cause is not removed |
| P1-E10 | UI check of mismatch acceptance | API: planner run → approver injects `alter_line_price` → approve → worker ⇒ CONFIRMED; browser as `approver2`: Approvals page | shows READBACK MISMATCH, reason field and "Accept supplier's version"; after click ⇒ RECONCILED with differences in the reason | Console: only the expected 401s of the pre-sign-in session check |
| P1-E11 | Hosted migration | temporary `SUPPLYLENS_SETUP_TOKEN` (Vercel, sensitive) → `vercel deploy --prod` → `POST /api/v1/internal/setup/schema` | `{"migrated_to":"0009"}` | Token generated locally, never printed; removed afterwards (`vercel env rm`), local copy deleted |
| P1-E12 | Hosted redeploy without token | `vercel deploy --prod` | Ready: `supplylens-e9j301hgg-…vercel.app` aliased to production | `vercel ls` also shows Git-triggered production builds failing in 4–6 s on each push (P3-OPS-02), before and after Phase 1 |
| P1-E13 | Owner credentials (indirect) | live `/health` after redeploy without token | 200 | The `demo` profile refuses to start if an owner URL is configured without the setup token, so a healthy start shows the entrypoint removed it. Platform-level injection is UNVERIFIED-removable (owner action) |
| P1-E14 | Live lockdown probes (non-destructive) | `scratchpad live_probe.py`: tenant_admin `POST /models/{random uuid}/status`, `POST /admin/members` (nonexistent email) | both **403** "'admin.write' is disabled in the public demo…"; setup endpoint 404; planner `/overview` 200, `/me` 200 | Probes cannot change data even if the lock were absent |
| P1-E15 | Branch protection | `gh api -X PUT repos/krish2105/SupplyLens-/branches/main/protection` | required checks `lint, secrets-and-dependencies, backend, contracts-and-web`; force-push and deletion off; `enforce_admins: false` | e2e not required while P2-QA-02 is open; admins exempt to keep D-037 direct pushes |
| P1-E16 | CI on the Phase 0 docs commit | `gh run view 39827354915` | **failure**: e2e `vitals.spec.ts:21` desktop INP proxy 224 ms > 200 ms; all other 7 jobs success | Docs-only commit ⇒ timing flake (P2-QA-02). Phase 0 summary had said it would likely pass; it did not |
| P1-E17 | CI on `037e42b` | `gh run view 39831397239` | **success, 8/8 jobs** (lint, secrets-and-dependencies, backend, contracts-and-web, e2e, pitr-drill, compose-smoke, acceptance-evidence) | — |

### Not run in Phase 1
Keycloak OIDC tests (Keycloak not running), local Docker compose (daemon down; CI `compose-smoke` passed on `037e42b`),
load test, research reruns, hosted Playwright suite (only the non-destructive probes above).

## Phase 2 — security hardening (2026-10-23, UTC)

**Starting point:** `main` @ `eaabf6b`. **Commits:** `ec6c208` (Git deploys), `1813f43` (security fixes). Environment as before.

| ID | Check | Command | Result | Notes |
|---|---|---|---|---|
| P2-E01 | Git-shaped Vercel build | `git archive HEAD` into a scratch dir → `vercel deploy` (preview) | Ready; build ran `python3 ../../scripts/vercel/build_api.py` | Preview answers 302 (deployment protection); a Ready build proves staging and bundling |
| P2-E02 | Git-triggered production deploys | push `ec6c208`, then `1813f43`; `vercel ls`, `vercel inspect` | both **Ready** (56 s, 45 s), aliased to `supplylens-self.vercel.app` | First successful Git deploys; before: `ENTRYPOINT_NOT_FOUND` in 4 s on every push |
| P2-E03 | Phase 2 security tests | `uv run pytest -q tests/test_phase2_security.py` | **24 passed** | During development they exposed two defects in the new code (idle revocation rolled back; chunked overflow surfaced as 500), both fixed |
| P2-E04 | Full backend suite | `uv run pytest -q -p no:cacheprovider` | **398 passed, 6 skipped** in 103.5 s | Skips = Keycloak |
| P2-E05 | Lint / lock / hosted pins | `ruff check .`; `uv lock --check`; `python3 scripts/vercel/build_api.py --check` | pass; "hosted API pins match uv.lock" | — |
| P2-E06 | Browser suite, disposable stack | API with `SUPPLYLENS_E2E_DISPOSABLE=true`; `SUPPLYLENS_E2E_ALLOW_DESTRUCTIVE=1 npx playwright test` | **114 passed, 2 skipped** (1.0 min) | `/api/v1/auth/config` reported `disposable: true` |
| P2-E07 | Destructive-setup guard | same stack, no opt-in: `npx playwright test e2e/consistency.spec.ts`; then `SUPPLYLENS_E2E_SKIP_RESET=1 npx playwright test e2e/layout.spec.ts` | refused: "Refusing to modify business data: SUPPLYLENS_E2E_ALLOW_DESTRUCTIVE is not 1"; read-only run: 15 passed, "not resetting test orders" | pytest guard: `SUPPLYLENS_ADMIN_DATABASE_URL=…/supplylens pytest` → UsageError "refusing to run" |
| P2-E08 | Contracts / types | `./scripts/update_contracts.sh`; `check_contracts.sh`; `npx tsc --noEmit` | contract regenerated (`AuthConfig.disposable`); match; tsc ok | — |
| P2-E09 | Dependency advisories | `uvx pip-audit==2.10.1 …`; `npm --prefix apps/web audit --omit=dev --audit-level=high` | no known vulnerabilities; 0 vulnerabilities | — |
| P2-E10 | Secret scan | `gitleaks detect --source . --redact --config .gitleaks.toml` | no leaks (≈3.6 MB) | Includes the new committed `deploy/vercel-api/hosted_storage` documents |
| P2-E11 | CI pins resolved | `gh api repos/<action>/commits/<tag>` | checkout 11d5960…, setup-uv d0cc045…, setup-node 49933ea…, upload-artifact ea165f8…, download-artifact d3f86a1…; gitleaks 8.21.2 linux_x64 sha256 5bc41815… | From the publishers' repositories over HTTPS |
| P2-E12 | CI on `ec6c208` | `gh run list --workflow ci.yml --branch main` | **cancelled** (superseded by the `1813f43` push; workflow `cancel-in-progress`) | `eaabf6b` likewise cancelled; `1813f43` covers both |
| P2-E13 | CI on `1813f43` | `gh run view 39836268410` | **success, 8/8 jobs** (lint incl. hosted pin check, secrets-and-dependencies with checksum-verified gitleaks, backend, contracts-and-web, e2e with the disposable-stack guard, pitr-drill, compose-smoke, acceptance-evidence) | First run with SHA-pinned actions |
| P2-E15 | Live session revocation (non-destructive) | `scratchpad live_p2.py`: viewer signs in, reads, signs out; the copied cookie is replayed | before sign-out 200; replay **401 `session_revoked`**; no cookie 401; `auth/config` `disposable: false` | — |
| P2-E16 | Live demo lockdown re-probe | `scratchpad live_probe.py` | admin writes 403; setup 404; planner overview 200 | Same probes as P1-E14 |

### Not run in Phase 2
Keycloak OIDC tests (SEC-P2-08 is code-reviewed only), local Docker compose and image scans (daemon down), DAST or any
intrusive test of the hosted demo, penetration test, corporate IdP qualification.


## Phase 3 — performance, scalability and backend reliability (2026-10-23, UTC)

**Starting point:** `main` @ `2365f49` (clean; CI run 39843966060 success). **Machine:** Apple M4 Pro, 12 cores, 24 GB,
macOS 27; PostgreSQL 17.11 (Homebrew, default settings), pgvector 0.8.6; Python 3.12.13; Node 26.10; Ollama running but
**not** used by the load test (embedding stub). Docker daemon not running.

| ID | Check | Command | Result | Notes |
|---|---|---|---|---|
| P3-E01 | Baseline before changes | `uv run ruff check .`; `uv lock --check`; `uv run pytest -q -p no:cacheprovider` | pass; pass; **398 passed, 6 skipped** (110 s) | Skips = Keycloak; matches the hand-over |
| P3-E02 | Reference data set | `PGHOST=/tmp PGUSER=<local superuser> SUPPLYLENS_LOAD_DB=supplylens_load uv run python scripts/loadtest/seed_reference.py` | 100,000 chunks, 1,008,206 sales rows, 2,000 products, 2,000 documents in 75 s; database 1,045 MB | Synthetic (fixed seed); `PGUSER` override added for hosts without a `postgres` role |
| P3-E03 | Query profile before | `EXPLAIN (ANALYZE, BUFFERS)` of the lexical and vector queries as `supplylens_app` under RLS (scratch `explain.py`) | lexical 54 ms, vector 155 ms; **both read ≈100,000 buffers (782 MB heap)**; distance evaluated in the sort key and again in the select list | One chunk row per 8 KB page because of the inline 4 KB vector |
| P3-E04 | Load before (`2365f49`) | `run_load.py --retrieval-rate {5,8,12,16,20}` (+ `--compute-users 3` mixed) on port 8100 against `supplylens_load` | 5/s: retrieval p95 256 ms, metadata p95 44 ms, 0 failures; knee ≈ 8–9 served/s; 12/s: p95 1,953 ms, 280 × 503; 20/s: 9.0/s served, 773 × 503 | `artifacts/reports/loadtest-p3-before-*.json`. The 2026-10-21 4 vCPU collapse at 5/s is **not reproducible on this machine** |
| P3-E05 | Migration 0010 and query timings after | `alembic upgrade head` on `supplylens_load`; scratch `time_search.py` (18 queries) | migration 31 s for 100,000 vectors; chunks heap 782 → **131 MB**; chunk_vectors 781 MB; lexical 29 ms, vector 113 ms, hybrid 140 ms (medians) | Vector page layout unchanged (PERF-P3-09) |
| P3-E06 | Load after (final build) | same commands, same data and durations | 5/s: retrieval p95 **157 ms**, metadata p95 52 ms, PostgreSQL 0.67 cores (was 1.09); 12/s: 900/900 served, p95 177 ms; 16/s: 1,200/1,200, p95 442 ms; 20/s: 15.3/s served, p95 978 ms, 253 × 503; mixed: retrieval p95 399 ms, metadata p95 201 ms | `artifacts/reports/loadtest-p3-after-*.json`; one client-side transport error (599, no response, nothing in API log) per 5/s run, cause UNVERIFIED |
| P3-E07 | Overload and recovery | `overload_probe.py --base http://127.0.0.1:8100 --tenant load-ref --email load01@… --burst 120 --concurrency 60` | final build: 9 accepted (p95 1,016 ms), 111 × 503 (p95 522 ms = queue wait), next request 200 in 223 ms | An earlier build with a 1.5 s wait: 18 accepted (p95 1.7 s), 102 refused; its 20/s run had accepted p95 1.9 s → wait lowered to 0.5 s |
| P3-E08 | Phase 3 tests | `uv run pytest -q tests/test_phase3_performance.py` | **15 passed** | Admission (share, queue, bounds, separate classes), pool timeout → 503, statement timeout → 503, statement_timeout per role, paging, metrics auth/content, dead letter, worker isolation, dispatch bound. Found a defect in the new share rule (own queue counted against a lone workspace → 429 at 20/s); fixed and covered |
| P3-E09 | Metrics under load | scrape `/metrics` with the bearer token after the runs | 292 lines: per-route counts and histograms, per-workspace requests and retrieval seconds, admission queued 1,210 / refused 318 queue_full + 124 wait_timeout, pool, connections, job/outbox depth | `artifacts/reports/metrics-sample-p3-loadtest.txt` (synthetic workspace id only) |
| P3-E10 | Full backend suite after | `uv run ruff check .`; `uv lock --check`; `uv run pytest -q -p no:cacheprovider` | pass; pass; **413 passed, 6 skipped** (109 s) | Includes migration rehearsal 0006 → 0010 → rollback → head with bit-identical vectors |
| P3-E11 | Contracts, types, build | `scripts/export_openapi.py` + `openapi-typescript` (regenerate); `./scripts/check_contracts.sh`; `npx tsc --noEmit`; `NEXT_DIST_DIR=.next-build npx next build`; `python3 scripts/vercel/build_api.py --check` | contracts match; tsc ok; build ok; hosted pins match | Inventory gains `total`, `offset`, `next_offset`; `/inventory` and `/documents` gain `limit`, `offset` |
| P3-E12 | Browser suite, disposable stack | `supplylens_p0e2e` migrated to 0010; p0-api/p0-worker/p0-web; `SUPPLYLENS_E2E_ALLOW_DESTRUCTIVE=1 npx playwright test` | **116 passed, 2 skipped** (1.1 min), twice (before and after the truncation-note wording change) | New: busy banner + automatic recovery after a 503; truncated-inventory note |
| P3-E13 | UI evidence | Playwright script with route mocking | `docs/screenshots/phase3-service-busy-banner.png`, `docs/screenshots/phase3-inventory-truncated.png` | With three refusals in a row a read is attempted 3 times, then the page shows the capacity message and "Try again" |
| P3-E14 | First hosted migration attempt | temporary `SUPPLYLENS_SETUP_TOKEN` (sensitive, generated locally, never printed) → push `8a0bb4d` (Git deploy Ready in 51 s) → `POST /api/v1/internal/setup/schema` | **500**; log: `UniqueViolation … chunk_vectors_pkey` in the 0010 per-workspace copy | Neon's owner role bypasses row-level security, so every pass saw every workspace. Alembic's transactional DDL rolled back: hosted schema stayed at 0009 and the demo kept working (retrieval there is lexical and does not touch `chunk_vectors`) |
| P3-E15 | Fix and regression test | migration copies `WHERE … AND tenant_id = t`; new `test_migration_0010_is_correct_for_a_role_that_bypasses_row_level_security` (two workspaces, migrated as a superuser) | test **fails on the old migration** with the same UniqueViolation, passes with the fix; rehearsals 8 passed; full suite **414 passed, 6 skipped** | Lesson recorded in PHASE-03 §6: rehearse hosted migrations with a role that bypasses RLS |
| P3-E16 | Backend-only push did not deploy | push `66cd20a` (migration fix, tests, docs); `gh api …/commits/66cd20a/statuses`; `gh api …/deployments`; `vercel ls` | CI run 39857106309 **success**; **no Vercel status, no deployment** after > 10 min (8a0bb4d, which touched `apps/web`, deployed in 51 s) | Cause INFERRED: service-root change detection. Fix: `deploy/vercel-api/source.sha256` (`build_api.py --pin`, `--check` in CI fails when stale: verified failing before the pin, passing after). A direct `vercel deploy --prod` from a Git export was not used |

### Not run in Phase 3
Declared 8 vCPU / 32 GiB profile (EXT-04); real embedding latency (stub); several API processes, a pooler or replicas;
a multi-tenant load (fairness is unit-tested only); sustained load beyond 3 minutes; batch phase (`--phase batch`);
Keycloak tests; local Docker compose; any load against the hosted demo.
