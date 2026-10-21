# SupplyLens project status

**Updated:** 2026-10-21 (UTC) · **Commit:** see `git log -1`
**Verified gate:** none complete. **P0 vertical slice implemented and verified locally.**
P0 as a whole is NOT passed: trained-model comparison, retrieval/agent evaluation sets,
clean containerised setup, backup/restore and several security suites remain (see TASKS.md).

## What works now (verified by commands in EVIDENCE_INDEX.md)

- Real data: UCI Online Retail II downloaded with receipt; 1,067,371 rows reconcile exactly
  (1,003,214 accepted + 21,335 returns + 42,822 quarantined). Raw SHA-256 unchanged after ingestion.
  Found and fixed a source defect: the two publisher sheets overlap (1–9 Dec 2010, 830 invoices,
  21,988 rows) — now quarantined as `cross_sheet_overlap` instead of double-counted.
- PostgreSQL 17 + pgvector schema with forced RLS on 28 tenant tables; app role is non-owner, no BYPASSRLS.
- Seasonal-naive forecast service (training-only intervals), persisted forecast runs, model registry.
- CP-SAT planner + independent validator + time-aware terms resolution (knowledge cutoff vs effective date,
  supersession, conflict detection, explained infeasibility). Spec reference case passes (A 30u/USD150 on
  19 Oct, B 30u/USD180 on 20 Oct), plus delayed-knowledge and conflict variants.
- Hybrid retrieval: Postgres full-text (lexical) + bge-m3 (Ollama) vectors, RRF, rule-based reranker,
  tenant/ACL/known-at/effective-date filters in SQL; lexical fallback when Ollama is down.
- Deterministic LangGraph investigator (ACCEPT→PLAN→GATHER_EVIDENCE→COMPUTE→CHECK→PREPARE_ACTION) with
  per-node Postgres checkpoints, resume without duplicate drafts, tool/time budgets.
- Actions: approval bound to payload hash + versions + expiry, separation of duties, optimistic concurrency,
  outbox in the approval transaction, sandbox ERP with idempotency keys and fault injection, UNKNOWN_OUTCOME
  reconciliation without blind resend, fenced leases.
- FastAPI /api/v1 with dev session cookie, CSRF header, Idempotency-Key replay/conflict, SSE run stream.
- Next.js web app: 10 screens, Light/Dark/System, dual-clock rail, linked 3D/2D/table selection, ECharts
  forecast lab with backtest panel, scenario studio, policies with amendment diff, approvals with evidence packet.
- Tests: 58 pytest (real Postgres) + 14 Playwright (journeys + axe on desktop/mobile) passing; `next build` passes.

## Current task
Session 1 complete through the P0 vertical slice.

## Exact next step
Phase 2 — forecasting research: freeze cohort and chronological splits on UCI (training cutoff, validation
origins, untouched final 28 days), implement LightGBM quantile and compact quantile TCN in `ml/`, run the
frozen protocol (MAE, MASE with undefined handling, pinball per quantile/horizon, 80% coverage/width,
crossing rate; 3 TCN seeds), register artifacts with hashes, and surface measured results in the Forecast lab.

## Open blockers / owner decisions
- M5 skipped by owner decision (academic-only; requires owner to accept Kaggle rules).
- No generative LLM by owner decision; adapter slot exists but is disabled.
- ContractNLI requires the owner to accept publisher terms manually.
- Enterprise identity (OIDC), real ERP sandbox credentials: not supplied → NOT_CONFIGURED / NOT_IMPLEMENTED.
- Docker (colima) has 2 CPU / 2 GB; full-stack compose run not yet verified.

## Data available but not yet admitted
The owner separately ran `download_datasets.py --profile core` inside `SupplyLens_Starter_Updated_Datasets/`
(receipts 2026-10-21 17:51–18:02 UTC): CUAD (115 MB), ACORD (20 MB), InventoryBench (1.9 GB),
World Bank IPF awards (295,058 rows, complete), TED (1 notice — query returned almost nothing; widen query).
These are not yet copied into this repo's `data/raw/` or ingested.

## Running processes (local dev, not durable)
- API: `uv run uvicorn supplylens.api.app:app --port 8000`
- Worker: `uv run python -m supplylens_worker.main`
- Web: `npm --prefix apps/web run dev` (port 3100; port 3000 is used by another project)

## Environment assumptions
macOS 27 arm64 (M4 Pro, 24 GB), Python 3.12 via uv 0.11.18, Node 26.10, Homebrew PostgreSQL 17.11 +
pgvector 0.8.6 on /tmp:5432, Ollama with bge-m3:567m. Timestamps are UTC; DB sessions forced to UTC.

## Last verified commands (2026-10-21 UTC)
```
uv run pytest -q                                   # 58 passed
npx --prefix apps/web tsc --noEmit                 # no errors
(cd apps/web && npx playwright test)               # 14 passed
(cd apps/web && NEXT_DIST_DIR=.next-build npx next build)   # 12 routes built
shasum -a 256 data/raw/core/online_retail_ii/online_retail_ii.zip   # 572e3627…7bfb (matches receipt)
```
