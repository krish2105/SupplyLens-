# SupplyLens project status

**Updated:** 2026-10-22 (UTC) · **Commit:** see `git log -1`
**Verified gate:** P0 demonstrated locally and on a hosted demo — 59 of 80 acceptance items passed locally, 14 partial,
5 not run (pilot users, support, pricing, production workload), 2 blocked on an ERP sandbox. All 22 CTO-audit findings
are fixed with correct-behaviour tests (`docs/remediation/REGISTER.md`); S09 is fixed for local and hosted-demo use, not
for a corporate deployment. **Live demo:** https://supplylens-self.vercel.app (Vercel Services + Neon; demo accounts on
fictional and public data; `docs/operations/hosted-demo.md`). Still open: field Web Vitals and the overview's 2.76 s
throttled mobile LCP, the manual screen-reader pass, human review of retrieval questions, the declared 8 vCPU load
profile, a corporate identity provider and an ERP sandbox.

## Current state (production-readiness Phase 2, 2026-10-23)
Phase 2 (security hardening) is recorded in `docs/agent-handoff/phases/PHASE-02.md`: revocable server-side sessions,
request-body cap and sign-in throttle, sanitised database errors, personal-data redaction on upload, fixture safety
guards, SHA-pinned CI and lock-pinned hosted dependencies. Every push to `main` now deploys the hosted demo. Measured:
pytest 398 passed / 6 skipped (Keycloak), Playwright 114 passed / 2 skipped. No security certification is claimed; a
penetration test and corporate IdP qualification have not been performed.

## Phase 1 state (2026-10-22)
The live register of open issues, evidence and decisions is `docs/agent-handoff/` (STATUS.md first). Phase 0 audited
commit 9fcbedb (2 P0, 10 P1, 18 P2, 8 P3). Phase 1 fixed both P0s (public demo administration, default shortfall),
five P1s (lead-time sizing, STALE re-approval, unreconciled orders as supply and the CONFIRMED dead end, owner
credentials in the serving process, receipts per location in the UI) and six P2s; see
`docs/agent-handoff/phases/PHASE-01.md`. Measured at the end of Phase 1: pytest 374 passed / 6 skipped (Keycloak), 38
tables with forced RLS, Playwright 116 tests (114 passed, 2 skipped) on an isolated database, CI has 8 jobs.
Sections below are the historical session log; their test counts are as of each session.

## CI on GitHub
`.github/workflows/ci.yml` runs on every push, pull request and weekly. **Run 39700028666 (commit 5809b70): all 7 jobs
passed** — lint (ruff incl. security rules, lockfile), secrets and dependencies (gitleaks over history, pip-audit,
npm audit), backend (296 tests on PostgreSQL 17 + pgvector, including the BUS-020 rehearsals), contracts and web (drift
check, tsc, `next build`), e2e (full Playwright suite against a real API/worker/DB), pitr-drill, compose-smoke (full
`docker compose` build and start with the repository defaults). The first three runs failed and exposed: a stale committed API contract (the drift check works), runner image drift
(`ubuntu-latest` moving to a version Playwright's installer does not support: now pinned), the PITR drill assuming the OS
user is `postgres`, and e2e needing the Demo workspace bootstrapped. Logs are not readable from this build environment, so
failing steps now publish their output tail as annotations (`scripts/ci_annotate.sh`).

## What works (all verified by commands in EVIDENCE_INDEX.md)

- **Data:** UCI Online Retail II (reconciled to the row), plus ACORD, CUAD (73 supply agreements, 2,176 expert labels),
  World Bank IPF awards (295,058), InventoryBench (pinned). Raw files immutable and hashed; provenance per dataset.
- **Forecasting research (F1, protocol 2.0.0):** the 1.0.0 results are superseded — their seasonal-naive baseline was
  wrong beyond horizon 7 (audit F01). Rerun on 503 products with rolling test origins 2011-10-13 and 2011-11-10: pooled
  MAE naive 21.35, LightGBM 14.52, TCN 14.26; TCN − naive −7.09 [−9.01, −5.51]; TCN − LightGBM −0.27 [−0.52, −0.06] with TCN
  better on only 44% of products. Not an untouched holdout (D-042). TCN 2.0.0 is champion by the frozen validation rule.
- **Decision research (S1, simulated, exploratory):** rerun on the 2.0.0 models; lower forecast error still did not lower
  simulated cost under a median policy (fill 78–79% vs 86% naive); the ordering policy dominated. The product first switched to a summed-q90 basis, then (session 3) to the lead-time-demand model (L1, D-032).
- **Retrieval (R1/R2/C1):** temporal logic removes wrong-version citations (92.6% → 100% top-1 on 118 generated
  questions); hybrid wins inside real contracts (hit@3 76.7%) but loses to vector-only on ACORD (negative result kept).
- **InventoryBench (official evaluator):** SupplyLens policy 0.482 vs base-stock 0.433 vs last-value 0.453.
- **Agent (AGT):** 57 scenarios × 3, 100% oracle-verified, 0 unapproved external writes.
- **Security:** forced RLS on 30 tenant tables at session 3 (38 since migration 0007/0008); 64-case cross-tenant/role matrix + RLS tests pass.
- **Ops:** OpenAPI + generated TS types with drift check (the web client is typed from them); atomic idempotency and
  database-shared rate limits; alert queue with signed webhook; OpenTelemetry tracing; verified tenant export and
  certified deletion; logical restore drill (6.2 s / 6.6 s) and WAL-archived point-in-time recovery drill (orders reconcile);
  rehearsed failed migration / rollback / ERP outage / embedding outage; full `docker compose` stack and CI running.
- **Load (ARC-07):** reference data of 100,000 chunks and 1,007,629 sales rows with 20 users: targets met at 4 retrieval
  req/s (metadata p95 165 ms, retrieval p95 970 ms), not at 5 (`docs/operations/load-test.md`).
- **Product UI:** 15 screens (Overview, Exceptions, Inventory with linked 3D/2D/table, Forecast lab with model
  comparison, Scenario studio, Investigations with live stream, Approvals with evidence packets, Policies with
  amendment diff and expert clause labels, Supplier market, Research, Value, Data admission, Administration,
  Settings, sign-in), ⌘K command palette, Light/Dark/System, 3 workspaces.
- **Tests:** 296 pytest (real PostgreSQL; 69 golden boundary cases) · 102 Playwright (journeys, resilience, consistency, accessibility, Web Vitals, layout; desktop + mobile) · `next build` · ruff · tsc.

## Session 3 summary (historical)
Session 3 closed the engineering gaps that needed no outside party (TASKS.md "Done in session 3"). Current state: see
the top of this file and `docs/agent-handoff/STATUS.md`.

## Exact next steps (need a person or something this build lacks)
1. Run the load test on the declared 8 vCPU / 32 GiB profile; decide on a tenant-wide search ceiling, admission control
   and pagination (load-test findings 5 and 6).
2. Manual screen-reader pass (`docs/acceptance/screen-reader-checklist.md`).
3. A reviewer fills in `evaluations/tasksets/r2_review_sample.csv` (`docs/acceptance/r2-human-review.md`).
4. Evaluate the cross-encoder (model weights) and validate the lead-time-demand model on real retail windows (licensed data).
5. Field Web Vitals from real sessions; consider server-rendering the first screen to fix mobile LCP.
6. Independent security test; OIDC; ERP sandbox; pilot.

## Open blockers / owner decisions
- No generative LLM (owner decision) → LLM agent ablations (ML-006 adaptive agent) not run.
- M5 not admitted (owner must accept Kaggle rules). ContractNLI needs manual terms acceptance.
- Enterprise identity, ERP sandbox, pilot users: not available → BUS-012/013/022, EXE-013 blocked.

## Running processes (local, not durable)
API `uvicorn supplylens.api.app:app` :8000 · worker `python -m supplylens_worker.main` · web `next start` :3100 (session 3 ran on a Linux sandbox; none of it persists).

## Environment
Sessions 1–2: macOS 27 arm64 (M4 Pro, 24 GB), Python 3.12.13 (uv 0.11.18), Node 26.10, PostgreSQL 17.11 + pgvector 0.8.6,
Ollama bge-m3:567m, PyTorch 2.14.1 (MPS), LightGBM 4.7.0, OR-Tools 9.15, Next.js 16.4.2.
Session 3: Linux sandbox (4 vCPU Xeon 2.1 GHz, 16 GiB), PostgreSQL 16.15 + pgvector 0.6.0, no Ollama, no GPU, egress allow-list
(no PyTorch index, no model hubs, no UCI/Kaggle downloads); CI on GitHub-hosted ubuntu-24.04 with PostgreSQL 17.

## Last verified commands (2026-10-22 UTC)
```
uv run ruff check .                                         # clean
uv run pytest -q                                            # 296 passed
./scripts/check_contracts.sh                                # contracts match
(cd apps/web && npx tsc --noEmit)                           # ok
(cd apps/web && npx playwright test)                        # 102 passed, 2 skipped
./scripts/pitr_drill.sh                                     # ok: true
scripts/loadtest/run_reference.sh                           # docs/operations/load-test.md
docker compose up -d                                        # artifacts/reports/compose_run_20261022.txt
```

## Re-verified on macOS with the real data and trained models (2026-10-22 UTC)
The integrated code was run on the development machine (real UCI data, registered LightGBM/TCN models, local `bge-m3`),
against a production web build:
```
uv run pytest -q                                            # 296 passed (one test fixed: it assumed no chunk had a vector)
(cd apps/web && npx playwright test)                        # 103 passed incl. mobile; web-vitals, resilience, accessibility
uv run python scripts/smoke_investigation.py              # 24 lines, OPTIMAL, 3 drafts, order read back: RECONCILED
```
Findings fixed in this pass: Forecast lab now falls back to the baseline when the clock precedes the champion's training
cutoff (replay guard) and says so; Approvals reserves space and scrolls internally (CLS 0.12–0.17 → within target); the 3D
hover card no longer covers the toolbar; palette test waits for the option. Against the dev server 16 timing-based
checks fail; they pass against `next start`, which is what CI uses.

## Session 4 — CTO-audit remediation (2026-10-22 UTC, macOS, real UCI data)
Owner decisions this session: push to `main` (D-037), CSV onboarding for sales/stock/terms (D-038), local Keycloak for
identity (D-039), 13 of 16 illustrations with HTML fallbacks for A02/A13/A16 (D-040); generative inference stays off (D-041).

- **Planning:** seasonal baseline fixed in both implementations (F01); coverage window, gaps and stockout walk bounded by
  the decision date (F02); controls that do not apply to the replenishment basis are rejected by the API and disabled in
  the UI (F03); residual capacity reaches CP-SAT and the validator, uncapped need stays visible (F04); an explicit zero
  budget stays zero (F08); declared 60-SKU limit and single-location grain (S21, D-043).
- **Actions:** idempotency outcome committed with the business change and one key per user intent in the client (F05);
  read-back compares every line field, need-by and status (F06); retries look up before any approval check (F07); fresh
  sends recheck approver rights, state, spend and terms (S11); reconciled orders become open supply, receipts and
  cancellations feed replanning (S12).
- **Access:** central document ACL on labels, citations, run events, evidence and term history (S10, D-044); model
  resolution scoped by dataset and status (S14); fail-closed production profile and loopback-only compose ports (S09);
  OIDC code+PKCE with role claims and deactivation, verified against Keycloak 26.0.7 in the browser and in tests.
- **Onboarding:** CSV templates, upload → map → validate → quarantine → publish an immutable snapshot, new customer
  workspaces, membership administration through narrow SECURITY DEFINER functions (S18). Migration 0007 rolls back
  without losing open orders, receipts or imports (D-048, rehearsed).
- **UI:** honest badges (retrieval mode is not verification; DELIVERED is not RECONCILED; read-back mismatch has its own
  state), research headlines from `evaluations/study_registry.json` (S16), native theme radios and opaque sticky
  surfaces (S17 part), gateway HTML and server errors shown with status and reference (S22), scenario context fingerprint
  (S15 part), 13 illustrations through one `EmptyState` component (`docs/design/illustrations.md`).
- **Research:** F1 2.0.0 and S1 rerun, R2 as a 2×2 factorial, AGT rerun; superseded runs listed with reasons.

Last verified commands (2026-10-22 UTC):
```
uv run ruff check .                                   # clean
uv run pytest -q                                      # 330 passed, 6 skipped (Keycloak not running; 6/6 passed earlier with it)
./scripts/check_contracts.sh                          # contracts match
(cd apps/web && npx tsc --noEmit)                     # ok
SUPPLYLENS_WEB_URL=http://localhost:3101 npx playwright test   # 107 passed, 1 skipped (production build)
uv run python scripts/smoke_investigation.py          # OPTIMAL, 3 drafts, order RECONCILED with full read-back
```
CI on GitHub: **run 39757531923 (commit 49a8caa): all 7 jobs passed** (lint, secrets/dependencies, backend, contracts and
web, e2e, PITR drill, compose smoke). The previous push failed only the PITR drill: its repeated workload found the
reference need already covered by its first order (open supply, S12); the workload now releases its own test order.
Local PITR drill: `ok: true` (`artifacts/reports/pitr_drill_20261022T094235Z.json`; on macOS run it with
`LC_ALL=en_US.UTF-8 TMPDIR=/tmp`).

Fresh screenshots with revision labels: `docs/screenshots/session4/` (manifest lists route, theme, viewport, state).

