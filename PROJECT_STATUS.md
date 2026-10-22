# SupplyLens project status

**Updated:** 2026-10-22 (UTC) · **Commit:** see `git log -1`
**Verified gate:** P0 demonstrated locally and in CI for everything that can be run without outside parties — 58 of 80
acceptance items passed locally, 13 partial, 5 not run (pilot users, support, pricing, production workload), 4 blocked on
external systems (`docs/acceptance/acceptance_register.csv`). P0 is not claimed complete: the load targets are met at 4 and
missed at 5 retrieval requests/s on the 4 vCPU machine available (the declared profile is 8 vCPU), mobile LCP is above its
field target, the manual screen-reader pass and the human review of retrieval questions are undone, and the two models
added in session 3 (lead-time demand, cross-encoder) are not validated on real data. P1/P2 items needing a real identity
provider, ERP sandbox or pilot users are blocked.

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
- **Forecasting research (F1):** frozen protocol, 506 products. Seasonal naive MAE 21.41 → LightGBM 15.37 → TCN 15.08
  (3 seeds 15.03 ± 0.04). Both trained models beat the baseline (CI excludes 0); TCN vs LightGBM tied (CI includes 0).
  TCN is champion by the frozen validation rule and serves forecasts with hash-verified artifacts and a replay guard.
- **Decision research (S1, simulated):** lower forecast error did not lower simulated cost; the ordering policy
  dominated. The product first switched to a summed-q90 basis, then (session 3) to the lead-time-demand model (L1, D-032).
- **Retrieval (R1/R2/C1):** temporal logic removes wrong-version citations (92.6% → 100% top-1 on 118 generated
  questions); hybrid wins inside real contracts (hit@3 76.7%) but loses to vector-only on ACORD (negative result kept).
- **InventoryBench (official evaluator):** SupplyLens policy 0.482 vs base-stock 0.433 vs last-value 0.453.
- **Agent (AGT):** 57 scenarios × 3, 100% oracle-verified, 0 unapproved external writes.
- **Security:** forced RLS on 30 tenant tables; 64-case cross-tenant/role matrix + RLS tests pass.
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

## Current task
Session 3 complete: closed the engineering gaps that needed no outside party (TASKS.md "Done in session 3").

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
