# Phase 7 — Operations decision studies: classes, CO2, fairness, generated answers, agent

**Dates:** 2026-10-26/27 (UTC) · **Start:** `main` @ `09f463a` · **Commits:** see `git log` after `09f463a` ·
**Owner brief:** inventory classes and the cost of service; cost, service and CO2 trade-off with an evolutionary
comparison; a fairness audit with a remedy; error measures, Prophet and XGBoost baselines and a weather experiment;
supplier delay risk (simulated); generated answers that cite or refuse (owner changed D-041 for local use, PD-022); an
n8n agent. Purchasing stays deterministic and approval-gated.

Evidence `P7-E..` → [`../EVIDENCE.md`](../EVIDENCE.md); issues → [`../ISSUES.md`](../ISSUES.md); decisions D-094 … D-099 →
root [`DECISIONS.md`](../../../DECISIONS.md), PD-022 → [`../DECISIONS.md`](../DECISIONS.md).

## 1. What changed
| Area | Change | Where |
|---|---|---|
| Inventory classes | ABC (365-day value, cuts 80/95 %), XYZ (52-week CV, cuts 0.5/1.0), safety stock z·σ·√L, holding 25 %/year; cost-of-service curve and class policy point | `planning/classes.py`, `GET /api/v1/inventory/classes`, Inventory page panel |
| CO2 trade-off | Optional `co2_cap_grams` (ε-constraint) and per-offer `co2_grams_per_unit` from lanes assumed from lead time; CO2 explain probe; frontier endpoint (21 caps, parallel, no explanations) | `supplylens_opt/planner.py`, `emissions.py`, `planning/scenario.py`, `POST /scenarios/emissions-frontier`, Scenarios panel |
| Solve policy | Deterministic first (1 worker, 2 s), then the parallel portfolio if not proven optimal; probes in parallel (5 s). Real UCI scope: UNKNOWN after 16 s → OPTIMAL in about 4.5 s with explanation; frontier 78 s → 3.2 s | D-096; `SolverInfo.deterministic` |
| Fair allocation | Optional `Need.shortage_weight` in the coverage objective; study-only | D-097; FA1 |
| Forecast metrics | `rmse`, `wape` (None when Σ|y| = 0), `mape` over non-zero actuals | `ml/supplylens_ml/metrics.py` |
| Generated answers | `POST /evidence/answer` (20/min): local Ollama model, JSON reply, every sentence cites, every figure in a cited passage, ≤ 4 sentences; refuses before calling the model when nothing is in force, or when the question names no product and the top passages cover several; demo profile refuses to start with generation on | `knowledge/generate.py`, `routes_decisions.py`, `config.py`, Policies panel (supplier scope added) |
| Agent | n8n 2.43.4 workflow, planner rights, idempotency key per hour and product set, skips products with an open draft | `infra/n8n/` |
| Studies | E1, FA1, W1, D1, G1 registered; first G1 run superseded (ambiguity) | `evaluations/*_study.py`, `study_registry.json`, Research page "Operations studies" |

Plan hashes are unchanged for requests that do not use the new fields (CO2 and weights are added to the hash only when
set), so approvals bound to existing hashes stay valid (D-095).

## 2. Results (all from saved metrics; see the registry for limits)
| Study | Headline | Data |
|---|---|---|
| E1 | Under the £20k budget a 5 % CO2 cut costs 9 of 23,980 units; halving CO2 costs 13.8 coverage points. NSGA-II: 98.1–98.5 % of exact hypervolume, 35–43 of ~116 points dominated by exact | Real scope; assumed lane factors; simulated terms |
| FA1 | Coverage UK 82.5 %, Europe 74.0 %, rest of world 50.8 %; α 0.4 cuts the gap 31.7 → 12.2 points for 1.4 points of total coverage; α 1 over-corrects | Real country shares; simulated stock and budget |
| W1 | Total daily units: XGBoost WAPE 24.6 % vs Prophet 28.0 % and seasonal naive 29.7 %; weather no clear effect (95 % intervals span zero); product level WAPE > 100 % for every model | Real sales; Open-Meteo weather |
| D1 | AUC logistic 0.77, LightGBM 0.75, supplier late-rate baseline 0.69 | Simulated order history: method check only |
| G1 | 196 answers shown, figures and citations 196/196; 1 of 67 must-refuse questions answered (3 before the product check); named-supplier questions 0/8 answered (KNOW-P7-01) | Generated questions over simulated and fictional agreements |
| n8n | Run 1 drafted 3 products (WAITING_FOR_APPROVAL); run 2 drafted the next 3, no duplicates | Local CI-equivalent stack |

## 3. Not done or blocked
- No real stock, supplier terms, delivery history or unit weights exist; every planning result above is on simulated
  operations. CO2 factors are rounded and assumed.
- G1 questions are generated, not written by buyers; the figure check would pass a right figure next to a wrong one.
- Generation is not deployed anywhere: the hosted demo keeps it off (D-041 for the demo).
- n8n was not deployed; it signs in through the local development sign-in.
- Shortage weights are not used by the product (owner decision on the rationing objective, PLAN-P5-01, still open).

## 4. Verification
P7-E08: pytest 505 passed / 6 skipped; ruff, contracts (79 paths), hosted digest re-pinned; web lint, types, 19 unit tests,
build; Playwright 42/42 screenshots (no baseline changed), 185 passed / 7 skipped on four projects, 18/18 lab vitals.
Three Inventory tests were scoped to the warehouse canvas and the stock table because the new classes panel adds a chart
canvas and a table.
