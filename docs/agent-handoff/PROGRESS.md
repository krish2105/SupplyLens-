# Agent handoff — progress across phases

Consolidated view of Phases 0–5 (2026-10-22/24, UTC). Detail lives in `ISSUES.md` (register with acceptance criteria),
`EVIDENCE.md` (every command and result), `DECISIONS.md` and `phases/PHASE-0N.md`. This file is a map, not proof: verify
anything you rely on.

## Timeline
| Phase | Commits | What it delivered | Verified by |
|---|---|---|---|
| 0 — baseline audit | `8171994` | Architecture map, 38 findings (2 P0, 10 P1, 18 P2, 8 P3), 10 external blockers, scores, execution order | P0-E01…E21 |
| 1 — core correctness and procurement safety | `037e42b`, `eaabf6b` | Demo lockdown; owner credentials out of the serving process; coverage-first planner; per-supplier lead times; committed orders as supply; mismatch acceptance; STALE re-approval; job failure alerts; draft uniqueness (migration 0009); cutoff-bounded replays; calendar lags; scenario conflicts; branch protection | P1-E01…E17; CI 8/8 on `037e42b` |
| Git deploys | `ec6c208` | Pushes to `main` deploy the hosted demo (committed `deploy/vercel-api`, build step, lock-pinned dependencies) | P2-E01, P2-E02 |
| 2 — security hardening | `1813f43`, `550b427` | Fixture safety guards; revocable server-side sessions; body cap and sign-in throttle; sanitised DB errors; PII redaction on upload; SHA-pinned CI and Dependabot; IdP-outage 503; 404 consistency | P2-E01…E16; CI 8/8 on `1813f43` |
| 3 — performance and backend reliability (owner brief) | see `git log` after `2365f49` | `chunk_vectors` (0010); admission classes, queue, workspace share; statement/pool timeouts → 503; bounded listings; `/metrics`; outbox dead letter; worker isolation; busy banner in the web app | P3-E01…; before/after load matrix on an M4 Pro laptop |
| 4 — frontend, UX and journeys (owner brief) | see `git log` after `55e0b1c` | 12 journeys end to end; document upload; workspace reconciliation; inventory per SKU@location; error boundaries and states; per-intent keys; 401 → sign-in and back; lint/unit/typed e2e in CI; Firefox/WebKit/iPhone projects; reference-case lock | P4-E01… |
| 4B — visual UI/UX gate (owner brief) | `967ba0b`, `85f9b6b` | 13 visual/UX defects fixed; 42 screenshot baselines per platform enforced in CI | P4B-E01… |
| 5 — AI/ML, retrieval, optimisation, MLOps (owner brief) | see `git log` after `36f4f9d` | Panel-date defect (TCN weekday inputs constant) fixed, F1 2.1.0; model fallbacks and verified loading; promotion gate; monitoring/shadow/drift report; S2 decision study (simulated); R3 answer support and ambiguity; phone overflow fix | P5-E01… |

Test counts over time: pytest 336 → 374 → 398 → 414 → 419 → 421 → **447 passed, 6 skipped** (Keycloak; Phase 5). Playwright 113
(+1 order-dependent failure) → 114 → 116 → 174 → **191 passed, 7 skipped** on four local projects (Phase 4B/5; Firefox in CI);
42 screenshot baselines per platform. Web unit tests: 19.

## Issue status (as of `550b427`; Phase 3 changes below)
**Fixed (19):** P0-SEC-01, P0-PLAN-01, P1-PLAN-02, P1-ACT-01, P1-ACT-02, P2-REL-01, P2-REL-02, P2-PLAN-03, P2-PLAN-04,
P2-PLAN-05, P2-API-01, P3-DOC-01, P3-DOC-02, P3-OPS-02, SEC-P2-01, SEC-P2-02, SEC-P2-04, SEC-P2-05, SEC-P2-10
— plus SEC-P2-07 (same as P2-PRIV-01, fixed for new uploads) and SEC-P2-08 (fixed in code, not exercised). 53 register rows in total.

**Partially fixed (10):** P1-SEC-02 (platform still injects owner variables — owner action), P1-FE-02 (inventory/3D/floor
plan still key by SKU), P1-PROC-01 (admins exempt; e2e not required), P2-FE-05 (several mutations still mint a key per
click), P2-PRIV-01 (rows stored before Phase 2), SEC-P2-03 (throttle per process), SEC-P2-06 / P3-CI-01 (Docker image
digests), P3-ONB-01 (publish re-check, atomic workspace creation), P3-SEC-03 (CSP `'unsafe-inline'`, stream role).

**Open (22):**
- P1: P1-FE-01 workspace default · P1-IAM-01 identity model (needs EXT-01) · P1-OPS-01 production platform ·
  P1-SAAS-01 SaaS plumbing (owner scope decision)
- P2: P2-REL-03 worker throughput / outbox re-claim · P2-ML-01 trained-model path test · P2-KNOW-01 abstention ·
  P2-FE-03 ESLint + unit tests · P2-FE-04 error boundaries · P2-FE-06 errors shown as loading/empty · P2-FE-07
  onboarding stale state · P2-FE-08 vitals observers · P2-QA-01 shared e2e fixture · P2-QA-02 lab-vitals timing on CI ·
  P2-PERF-01 throughput and mobile LCP · SEC-P2-11 per-tenant retrieval ceiling
- P3: P3-PLAN-06 · P3-ML-02 · P3-FE-09 · P3-FE-10 · SEC-P2-12 audit tamper-evidence · SEC-P2-13 retention jobs
- Known design residual (D-056): drafts awaiting approval are not counted as supply; two drafts for one need can both
  be approved.

**External blockers (10, unchanged):** EXT-01 corporate IdP · EXT-02 ERP sandbox · EXT-03 pilot users · EXT-04 8 vCPU
load profile · EXT-05 screen-reader pass · EXT-06 R2 human review · EXT-07 penetration test · EXT-08 LLM decision
(D-041) · EXT-09 dataset licences · EXT-10 pricing/SLA/support.

## Scores (evidence-weighted judgement, rules in DECISIONS PD-006; not measurements)
| Category | Phase 0 | After Phase 2 | After Phase 3 | After Phase 5 | Why it moved / what caps it |
|---|---|---|---|---|---|
| CTO | 66 | 73 | 76 | 76 | Measured capacity work, admission control, timeouts, metrics; still no production platform |
| CEO | 38 | 40 | 40 | 40 | Unchanged: no customers, pilot, pricing or ERP |
| COO | 42 | 47 | 51 | 51 | Metrics endpoint and overload runbook; no scraper, SLOs or on-call yet |
| AI Engineering | 58 | 65 | 66 | 70 | Phase 5: a P1 model-input defect found and fixed, promotion gate, fallbacks, monitoring, decision-level and answer-support studies with negative results reported; capped by no real outcomes, no human-reviewed labels and no untouched holdout |
| Security | 55 | 70 | 71 | 71 | Per-workspace admission share (SEC-P2-11), statement timeouts; no pentest or corporate IdP |
| Real MVP | 40 | 45 (cap 50) | 45 (cap 50) | 45 (cap 50) | Unchanged (no real user, ERP or IdP) |
| Real SaaS | 28 | 30 | 31 | 31 | Tenant-level consumption metrics exist; no signup, billing or metering product |

## Phase 3 changes to the issue status
SEC-P2-11 fixed per process; P2-PERF-01 and P2-REL-03 partially fixed; new PERF-P3-01…07 fixed, PERF-P3-08/09/10 open
(see ISSUES.md "Phase 3 resolution notes").

## Phase 5 changes to the issue status
Fixed: ML-P5-01 (P1), P2-ML-01, ML-P5-02, P3-ML-02, KNOW-P5-01, FE-P5-01, QA-P5-01. Partially fixed: P2-KNOW-01 (answer
support and ambiguity; out-of-scope detection limited, KNOW-P5-02), P3-PLAN-06 (explainer and timeout parts). New open:
ML-P5-05, ML-P5-06, KNOW-P5-02, KNOW-P5-03, PLAN-P5-01 (owner decision). See ISSUES.md "Phase 5 resolution notes".

## Recommended order for the remaining work
1. **Phase 4B — done** (visual UI/UX and asset gate; PHASE-04B): 13 defects fixed, screenshot regression (`visual` project), Playwright 191 passed / 7 skipped locally.
1. **Phase 4 — done** (frontend, UX, journeys; PHASE-04). Formerly: P1-FE-01, rest of P1-FE-02, P2-FE-03 (ESLint + unit tests in CI first),
   P2-FE-04/05/06/07/08, P2-QA-01/02 (then require `e2e` in branch protection), P3-FE-09/10.
2. **Phase 5 — done** (AI/ML, retrieval, optimisation, MLOps; PHASE-05). The owner's Phase 5 brief replaced the earlier
   data-protection plan, whose items move to Phase 6.
3. **Phase 6 — planning depth and data protection:** PLAN-P5-01 (after the owner's decision), P3-PLAN-06 rest, ML-P5-05,
   KNOW-P5-03, P2-REL-03; SEC-P2-12, SEC-P2-13, P3-SEC-03 (nonce CSP), P2-PRIV-01 backfill, P3-ONB-01 rest, D-056
   duplicate warning, PERF-P3-09 (with the retrieval studies re-run).
4. **Phase 7 — production platform and operations:** P1-OPS-01 (IaC, staging, secrets manager, replicas, SLOs,
   dashboards), P2-PERF-01 rest (declared profile), PERF-P3-08/10, Docker digests, distributed sign-in throttle; rerun drills and load test there.
5. **Phase 8 — identity and SaaS:** P1-IAM-01, P1-SAAS-01 (owner decisions first; EXT-01).
6. **Owner actions, any time:** scope Neon integration variables (P1-SEC-02), review the 7 Dependabot PRs, decide on the
   branch-protection admin exemption, pursue EXT-01…EXT-10.

## What is NOT on GitHub (by design) and how to recreate it
| Local item | Why not in Git | Recreate |
|---|---|---|
| `.env`, `.env.local` | Secrets / local settings | `cp .env.example .env` (development defaults only) |
| `data/raw/**` (≈2.3 GB: UCI Online Retail II, ACORD, CUAD, World Bank IPF, InventoryBench) | Licensed or large raw data, kept immutable and hashed | `python3 -I scripts/download_datasets.py --dataset online_retail_ii` (others: see `scripts/download_datasets.py` catalogue and `data/raw/ADD_DATASETS_HERE.md`; some need manual licence acceptance) |
| Trained model files in `artifacts/experiments/*/` (`*.pt`, `lightgbm_*.txt`, `_work/`) | Model weights and per-run outputs; only small metrics JSON is committed | `uv run python evaluations/forecast_study.py` (hours; see `docs/research/results.md`) |
| `storage/`, `storage_test/`, `storage_p0e2e/` | Runtime document storage and test scratch | Created by `python -m supplylens.bootstrap` and the test suites |
| `build/hosted-storage`, `deploy/vercel-api/hosted_data/` | Hosted-demo dataset export (only for first install via `/setup/data`) | `docs/operations/hosted-demo.md` → "Deploy" |
| `.vercel/` | Vercel project link for the CLI | `vercel link` (project `supplylens`, team of the owner) |
| Local dev-server launch configuration | Machine-specific (git-excluded) | Optional; see the disposable E2E stack notes in STATUS.md |
| Starter packs and ZIPs at the repo root | Owner's original materials, kept untouched (D-002) | Owner's copies |
| Local PostgreSQL databases (`supplylens`, `supplylens_test`, `supplylens_p0e2e`, `supplylens_load`) | Machine state | See "Run it" in root `NEXT_SESSION.md` and the CI workflow's database steps |
