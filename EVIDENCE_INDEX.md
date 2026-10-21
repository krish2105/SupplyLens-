# SupplyLens evidence index

Environment for all rows: macOS 27 arm64, Python 3.12 (uv 0.11.18), Node 26.10, PostgreSQL 17.11 + pgvector,
Ollama bge-m3:567m. Dates are UTC. Commits: see `git log` (rows recorded at commit 9dcdc9c or later).

| ID | Requirement / study | Artifact | Command | Dataset hash | Date | Outcome |
|---|---|---|---|---|---|---|
| E-01 | DAT-001, BUS-001, EXE-002 | data/download_receipts.jsonl | `python3 -I scripts/download_datasets.py --dataset online_retail_ii`; `shasum -a 256 …zip` | 572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb | 2026-10-21 | Downloaded 45,622,418 bytes; hash unchanged after ingest and later re-check |
| E-02 | DAT-003, BUS-002 | artifacts/reports/uci_qualification.json | `uv run python -m supplylens.bootstrap` | same | 2026-10-21 | 1,067,371 = 1,003,214 accepted + 21,335 returns + 42,822 quarantined (21,988 cross-sheet overlap, 12,051 exact duplicates, 6,093 non-merchandise, 2,690 zero price) |
| E-03 | ML-002/003 baseline | tests/test_seasonal_naive.py, tests/test_forecast_service.py | `uv run pytest -q` | synthetic test series | 2026-10-21 | pass (future spike does not change forecast; quantiles ordered; undefined MASE returned as None) |
| E-04 | ARC-05, EXE-003/004/005 | tests/test_planner_fixture.py | `uv run pytest -q` | fixtures/policy_change_case.json | 2026-10-21 | pass: JSON fixture and spec variant (A 30/USD150 → B 30/USD180), delayed knowledge, conflict, explained infeasibility, validator rejects below-MOQ |
| E-05 | BUS-005/006/007, EXE-007/008/009, AGT-02 (partial) | tests/test_actions.py | `uv run pytest -q` | demo fixtures | 2026-10-21 | 14 pass incl. one sandbox order per key, timeout-after-commit → UNKNOWN_OUTCOME → reconcile, fenced late write rejected, expired approval blocks dispatch |
| E-06 | Agent flow, EXE-005, EXE-011 | tests/test_agent_graph.py | `uv run pytest -q` | demo fixtures | 2026-10-21 | 6 pass incl. resume without duplicate drafts and prompt-injection containment |
| E-07 | UX-012 journeys, BUS-009/010, UX-010 (automated) | apps/web/e2e/*.spec.ts, artifacts/reports/e2e-results.json | `(cd apps/web && npx playwright test)` | live dev DB | 2026-10-21 | 14 pass: reference journey to RECONCILED, 19-Oct variant, theme persistence, linked selection, axe serious/critical = 0 and no horizontal scroll on 5 screens (desktop 1440 + Pixel 7) |
| E-08 | SEC-01 (partial), ARC-02 (partial) | tests/test_db_rls.py, tests/test_api.py | `uv run pytest -q` | — | 2026-10-21 | pass: non-owner role, cross-tenant read/write denied, context does not leak in pool, CSRF, idempotency replay/409, 404 on cross-tenant action |
| E-09 | Full backend suite | artifacts/reports/pytest-2026-10-21.txt | `uv run pytest -q` | — | 2026-10-21 | 58 passed |
| E-10 | Build | — | `NEXT_DIST_DIR=.next-build npx next build` | — | 2026-10-21 | 12 routes built |
| E-11 | Live UCI investigation (manual) | agent_events in dev DB | Investigations screen / `create_run` | E-01 hash | 2026-10-21 | 48 SKUs, forecast run, 96 applicable terms (8 excluded by date), OPTIMAL plan 22 lines within assumed £20,000 budget, 4 drafts. Simulated operations; not a business result |
| E-12 | Forecast lab replay (manual, one SKU) | UI | Forecast lab, 85123A, origin 2011-11-10 | E-01 hash | 2026-10-21 | Seasonal naive MAE 138.93 units/day, 68% of days inside 10–90% interval over 28 days. One SKU, one origin: illustrative only, not a model comparison |

Not yet evidenced (do not cite as done): LightGBM/TCN training and comparison, retrieval Recall@10 / citation
precision on a frozen set, 50-scenario agent evaluation, 50 cross-tenant cases, OIDC, Docker clean start,
backup/restore, performance targets, manual screen-reader review.
