# SupplyLens project status

**Updated:** 2026-10-21 (UTC) · **Commit:** see `git log -1`
**Verified gate:** P0 *largely* demonstrated locally — 46 of 80 acceptance items passed locally, 18 partial,
12 not run, 4 blocked on external systems (`docs/acceptance/acceptance_register.csv`). P0 is not claimed complete:
load testing, WebGL-failure automation, manual screen-reader review, a full container run and CI execution remain.
P1/P2 items needing a real identity provider, ERP sandbox or pilot users are blocked.

## What works (all verified by commands in EVIDENCE_INDEX.md)

- **Data:** UCI Online Retail II (reconciled to the row), plus ACORD, CUAD (73 supply agreements, 2,176 expert labels),
  World Bank IPF awards (295,058), InventoryBench (pinned). Raw files immutable and hashed; provenance per dataset.
- **Forecasting research (F1):** frozen protocol, 506 products. Seasonal naive MAE 21.41 → LightGBM 15.37 → TCN 15.08
  (3 seeds 15.03 ± 0.04). Both trained models beat the baseline (CI excludes 0); TCN vs LightGBM tied (CI includes 0).
  TCN is champion by the frozen validation rule and serves forecasts with hash-verified artifacts and a replay guard.
- **Decision research (S1, simulated):** lower forecast error did not lower simulated cost; the ordering policy
  dominated. Product switched to a q90 order-up-to basis on this evidence.
- **Retrieval (R1/R2/C1):** temporal logic removes wrong-version citations (92.6% → 100% top-1 on 118 generated
  questions); hybrid wins inside real contracts (hit@3 76.7%) but loses to vector-only on ACORD (negative result kept).
- **InventoryBench (official evaluator):** SupplyLens policy 0.482 vs base-stock 0.433 vs last-value 0.453.
- **Agent (AGT):** 57 scenarios × 3, 100% oracle-verified, 0 unapproved external writes.
- **Security:** forced RLS on 30 tenant tables; 64-case cross-tenant/role matrix + RLS tests pass.
- **Ops:** OpenAPI + generated TS types with drift check; rate limits; backup/restore drill passed (6.2 s / 6.6 s);
  Dockerfiles, Compose stack and CI workflow written.
- **Product UI:** 15 screens (Overview, Exceptions, Inventory with linked 3D/2D/table, Forecast lab with model
  comparison, Scenario studio, Investigations with live stream, Approvals with evidence packets, Policies with
  amendment diff and expert clause labels, Supplier market, Research, Value, Data admission, Administration,
  Settings, sign-in), ⌘K command palette, Light/Dark/System, 3 workspaces.
- **Tests:** 131 pytest (real PostgreSQL) · 37 Playwright (journeys + axe in light/dark, desktop/mobile) · `next build`.

## Current task
Session 2 complete. API container image build: see EVIDENCE_INDEX E-27.

## Exact next steps
1. Run `docker compose up --build` end to end (needs a larger colima VM: `colima start --cpu 4 --memory 8`).
2. Push to a GitHub remote so `.github/workflows/ci.yml` actually runs (needs owner approval to create/push).
3. Train a lead-time-demand model (aggregate target) to replace the summed-q90 heuristic (S1 follow-up).
4. Human review of a sample of the R2 questions; add a cross-encoder reranker condition (R1b).
5. Manual screen-reader pass; automate the WebGL-failure path; Web Vitals measurement (UX-011).

## Open blockers / owner decisions
- No generative LLM (owner decision) → LLM agent ablations (ML-006 adaptive agent) not run.
- M5 not admitted (owner must accept Kaggle rules). ContractNLI needs manual terms acceptance.
- Enterprise identity, ERP sandbox, pilot users: not available → BUS-012/013/022, EXE-013 blocked.

## Running processes (local, not durable)
API `uvicorn supplylens.api.app:app` :8000 · worker `python -m supplylens_worker.main` · web `npm --prefix apps/web run dev` :3100.

## Environment
macOS 27 arm64 (M4 Pro, 24 GB), Python 3.12.13 (uv 0.11.18), Node 26.10, PostgreSQL 17.11 + pgvector 0.8.6,
Ollama bge-m3:567m, PyTorch 2.14.1 (MPS), LightGBM 4.7.0, OR-Tools 9.15, Next.js 16.4.2.

## Last verified commands (2026-10-21 UTC)
```
uv run pytest -q                                            # 131 passed
./scripts/check_contracts.sh                                # contracts match
npx --prefix apps/web tsc --noEmit -p apps/web              # ok
(cd apps/web && NEXT_DIST_DIR=.next-build npx next build)   # 16 routes
(cd apps/web && npx playwright test)                        # 37 passed
./scripts/backup_restore_drill.sh                           # all_ok true
```
