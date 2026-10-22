# SupplyLens research results (dissertation package)

All numbers are copied from `artifacts/experiments/*/metrics.json` (metrics, configs and cohorts are committed; weights
and per-run outputs are not). Simulated outcomes are labelled. Runs: 2026-10-21 and, after the session-4 audit fixes,
2026-10-22 (UTC). Status and reviewed headline of every run: `evaluations/study_registry.json`.
Hardware: Apple M4 Pro, 24 GB, macOS 27; Python 3.12.13, LightGBM 4.7.0, PyTorch 2.14.1 (MPS).

## Research questions

1. **F1** — Do trained models (LightGBM quantile, compact quantile TCN) improve daily unit-sales forecasts over seasonal naive?
2. **S1** — Holding the inventory policy fixed, do better forecasts produce better simulated inventory outcomes?
3. **R2** — Does explicit effective-date and supersession logic change which supplier-terms version is cited?
4. **R1 / C1** — How do lexical, vector and hybrid retrieval compare on public expert-labelled contract corpora?
5. **IB** — How does SupplyLens' deterministic replenishment logic score on InventoryBench's official evaluator?
6. **AGT** — Does the stateful investigator end in the oracle's state across frozen business scenarios without unauthorised writes?

## F1 — forecasting, protocol 2.0.0 (`F1-20261022T090206Z`, current)

**What changed.** Protocol 1.0.0 (`F1-20261021T190101Z`) is **superseded**: its seasonal-naive baseline repeated the
value from *k* seasons back for horizon days beyond the first week instead of the last observed week (audit F01), so
its baseline comparisons, champion selection and headline were invalid. Protocol 2.0.0
(`ml/configs/forecast_study_v2.json`, frozen 2026-10-22) uses the corrected baseline and **rolling test origins**
(2011-10-13 and 2011-11-10), each refitted on labels available at that origin; validation origins 2011-08-18 and
2011-09-15 precede both. Cohort: 503 products with at least 150 selling days in the year before
2011-08-18. **Not an untouched holdout:** protocol 1.0.0 had already looked at both windows; 2.0.0 keeps the same search
grid and selection rule and is reported as a corrected re-run, not a new confirmatory test (D-042).

Selection (mean validation pinball): naive 7.814, LightGBM
4.951, TCN 4.892 → champion **tcn**
(registered as 2.0.0; the 1.0.0 trained models are retired).

| Test origin | Model | MAE | MASE | Pinball (mean) | 80% coverage | Width | Raw crossing |
|---|---|---|---|---|---|---|---|
| 2011-10-13 | Seasonal naive | 20.57 | 1.042 | 8.105 | 81.0% | 33.2 | 0.00% |
| 2011-10-13 | LightGBM quantile | 13.99 | 0.679 | 5.138 | 86.3% | 37.0 | 7.13% |
| 2011-10-13 | Quantile TCN (seed 0) | 13.80 | 0.664 | 5.097 | 84.9% | 35.9 | 7.77% |
| 2011-11-10 | Seasonal naive | 22.12 | 1.135 | 8.591 | 75.5% | 34.1 | 0.00% |
| 2011-11-10 | LightGBM quantile | 15.06 | 0.783 | 5.513 | 84.2% | 42.9 | 7.80% |
| 2011-11-10 | Quantile TCN (seed 0) | 14.72 | 0.765 | 5.305 | 85.1% | 38.2 | 4.58% |

TCN over seeds 0/1/2 at the last origin: MAE 14.75 ± 0.05.

Paired comparison of per-product MAE averaged over both test origins (product-level bootstrap, 2,000 resamples):

| Comparison | Mean difference | 95% CI | First model better on | Reading |
|---|---|---|---|---|
| LightGBM − naive | -6.82 | -8.73 to -5.25 | 89.9% | difference detected |
| TCN − naive | -7.09 | -9.01 to -5.51 | 90.1% | difference detected |
| TCN − LightGBM | -0.27 | -0.52 to -0.06 | 43.7% | difference detected |

**Finding.** Both trained models cut daily absolute error by about a third against the corrected baseline (pooled MAE
naive 21.35, LightGBM 14.52, TCN 14.26).
TCN's mean advantage over LightGBM is small and its interval now excludes zero, but TCN is better on fewer than half of
the products: the average is carried by a minority of series. No equivalence test was run.

## S1 — inventory consequences (`S1-20261022T092040Z`, **simulated, exploratory**)

Rerun on the F1 2.0.0 models (`S1-20261021T193239Z` is superseded). Lost-sales simulation over 2011-11-11 → 2011-12-08,
weekly review, lead time 3 days, z = 1.2816, holding 25%/year, unit cost 55% of median selling price (assumptions).

| Forecaster / policy | Fill rate | Stockout product-days | Lost margin + holding (£, 28 days) |
|---|---|---|---|
| Seasonal naive, median + safety | 85.6% | 1,016 | 35,261 |
| LightGBM, median + safety | 78.4% | 1,542 | 51,478 |
| TCN, median + safety | 78.8% | 1,609 | 50,903 |
| Seasonal naive, q90 order-up-to | 94.9% | 201 | 14,709 |
| LightGBM, q90 order-up-to | 94.8% | 242 | 16,583 |
| TCN, q90 order-up-to | 94.6% | 258 | 16,264 |
| Perfect-foresight reference | 89.3% | 1,902 | 25,436 |

**Finding (unchanged in direction).** Lower forecast error did not produce better simulated stock outcomes under a
median-based policy: summed q50 covered 99% (naive), 52% (LightGBM) and
49% (TCN) of review-window volume, so the trained models' medians under-stock heavy-tailed daily sales.
A q90 order-up-to policy brings all three to about 95% fill. **Exploratory:** that policy was picked after seeing the
first S1 test results (audit S20), so the policy comparison is not confirmatory. The product now uses the
lead-time-demand model (D-032).

## R2 — time-aware supplier terms, 2×2 factorial (`R2-20261022T045503Z`, current)

The first R2 (`R2-20261021T191153Z`, superseded) compared "temporal logic off" with "on" while also switching
supersession reranking, so it confounded two factors (audit S13). The rerun crosses effective-date filtering
{off, on} with supersession reranking {off, on}, holding channels (hybrid), queries, permissions and candidate depth
fixed. 118 synthetic questions (not human-reviewed); query-level outcomes in `artifacts/reports/r2_query_level.jsonl`.

| Effective-date filter | Rerank | Top-1 citation correct | Wrong version at top |
|---|---|---|---|
| off | off | 92.6% | 7.4% |
| off | on | 96.3% | 3.7% |
| on | off | 95.4% | 4.6% |
| on | on | 100.0% | 0.0% |
| on (lexical only) | on | 100.0% | 0.0% |

Main effect of effective-date filtering +3.2 points, of reranking
+4.2 points, interaction +0.9 points. Both mechanisms contribute; neither alone
removes every wrong-version citation. Abstention on unknown products 100% in every condition; cross-tenant probes:
0 leaked chunks in 60 queries. The questions come from the same
simulated records that generated the documents, so this measures the mechanism, not contract understanding.

## R1 — ACORD clause retrieval (`R1-20261022T161030Z`, current)

3,931 clauses, all 57 judged test queries (the first run, `R1-20261021T191153Z`, excluded one because the judgement file's
CSV quoting was parsed by stripping quote characters: DEF-04, fixed). Search is restricted to the ACORD clause document,
because the same workspace now also holds the CUAD contracts. Relevant = grade ≥ 2.

| Retrieval | nDCG@10 | Recall@10 | MRR@10 | p95 latency |
|---|---|---|---|---|
| PostgreSQL full-text (lexical, not BM25) | 0.061 | 0.061 | 0.131 | 17 ms |
| bge-m3 vector | **0.108** | **0.118** | **0.238** | 78 ms |
| Hybrid RRF | 0.089 | 0.100 | 0.187 | 147 ms |

**Finding (negative for the hybrid, unchanged).** On short clause-category queries, vector-only beats the hybrid; the
weak lexical channel dilutes RRF. Absolute scores are low and were not compared with published ACORD baselines.

## C1 — clause localisation in CUAD (`C1-20261021T191800Z`)

73 real supply/distribution/manufacturing agreements, 485 (contract, category) items over 15
procurement-relevant CUAD categories; query = CUAD category description; hit = a top-k chunk overlaps the
expert span.

| Retrieval | Hit@1 | Hit@3 | Hit@5 |
|---|---|---|---|
| Lexical | 44.1% | 66.8% | 75.9% |
| Vector | 52.4% | 72.2% | 79.2% |
| Hybrid RRF | **53.8%** | **76.7%** | **83.9%** |

Within a single long contract, the hybrid wins. Together with R1 and R2, the evidence is that hybrid helps
for identifier-heavy and within-document search and hurts on short semantic queries over many similar clauses.

## IB — InventoryBench (`IB-20261021T192006Z`)

1,320 instances, official `eval/evaluate_results.py` at pinned commit 62b1f11, mean normalised reward.

| Policy | Score |
|---|---|
| Last value × (L+1) | 0.453 |
| Normal base-stock (promised lead time) | 0.433 |
| SupplyLens (smoothed level, empirical residual quantile at critical ratio, lead time learned from arrivals) | **0.482** |

No LLM is used. Real trajectories derive from H&M data whose upstream terms were not reviewed for redistribution.

## AGT — investigator evaluation (`AGT-20261022T045832Z`; rerun on the session-4 code, same outcome as `AGT-20261021T192432Z`)

57 frozen scenarios × 3 trials against the test database: 44 reference-case dates × budgets, 2 delayed-knowledge,
missing stock record, conflicting terms, two role denials, administrator approval, self-approval, stale terms,
timeout-after-commit, fail-before-commit retry, crash after submit, approved happy path. Expected outcomes come
from a brute-force oracle over hand-written ground truth (not CP-SAT).

Verified completion 100% (171/171 trials), unauthorised external writes 0, identical outcomes across trials,
median run 67 ms, 6.0 tool calls per run, 0 LLM tokens.

## Limitations

- Sales are a demand proxy; stockouts and lost sales are unobserved. Cost parameters in S1 are assumptions.
- One retailer (UCI); results may not transfer. M5 was not used (owner decision).
- F1 2.0.0 uses two rolling test windows (Oct–Dec 2011), both seen by protocol 1.0.0 and both pre-Christmas; a confirmatory
  test needs data no protocol has looked at.
- R2 questions are synthetic and not human-reviewed; no generative LLM was evaluated (owner decision).
- The investigator is deterministic, so "agent" results concern orchestration and controls, not model reasoning.

## Reproduce

```bash
uv run python evaluations/forecast_study.py --config ml/configs/forecast_study_v2.json
uv run python evaluations/simulation_study.py
uv run python evaluations/retrieval_study.py
uv run python evaluations/inventorybench_study.py
uv run python evaluations/agent_study.py
```


## L1 — lead-time demand model (simulated; `evaluations/leadtime_demand_study.py`, `artifacts/reports/leadtime_demand_study.json`)

**Question.** The summed-daily-q90 heuristic is not a window quantile. Does a model that combines the forecast's daily
quantiles with the measured day-to-day dependence of the SKU's sales order up to the service level it is asked for, and at
what stock?

**Method.** Simulated demand with *known* dependence: negative-binomial daily demand around a weekday pattern and an AR(1)
latent level (persistence 0, 0.5, 0.9). 150 series × about 30 windows per setting; a daily-calibrated but state-blind
forecaster supplies q10/q50/q90; 28-day protection interval (7 days lead time + 21 days coverage). Dependence is measured
from each series' first 180 days (model "estimated") or taken as the declared fallback AR(1) 0.3 ("default").
"Coverage" is the share of windows whose realised demand stayed at or below the order-up-to level.

| Persistence | Target | Model, dependence estimated: coverage / mean stock | Summed q90: coverage / stock | Summed q50: coverage / stock |
|---|---:|---|---|---|
| 0.0 | 90 % | 88.2 % / 554 | 100 % / 895 | 14 % / 404 |
| 0.5 | 90 % | 86.9 % / 539 | 100 % / 852 | 18 % / 383 |
| 0.9 | 90 % | 84.6 % / 560 | 99.7 % / 835 | 32 % / 375 |

**Findings.**
1. The summed-q90 heuristic covers essentially every window (99.7–100 %) at 49–61 % more stock than the model's 90 % level:
   it is over-conservative, not calibrated. Summed medians cover 14–32 %.
2. The model lands 2–5 points *under* its target at 90 % (and similarly at 80 % and 95 %), worse with persistent demand.
   The remaining gap is partly the skew of the daily distribution and partly the gamma approximation; an oracle that knew
   the true dependence still sat about 3 points under. It is a calibration shortfall to be corrected on real data.
3. Without history the declared default dependence (0.3) over-covers independent demand (92.6 %) and under-covers
   persistent demand (80.9 %); the output labels which one was used.
4. An earlier version that fitted only lag-1 autocorrelation (AR(1)) under-covered persistent demand by more; measuring
   the autocorrelation curve over 14 lags with an initial-positive-sequence cut-off fixed part of that.

**Limits.** Simulation, one data-generating process, an idealised forecaster. **Not validated on real retail history**
(the licensed UCI/M5 files are needed for the equivalent study on real windows, which has not been run). The product
labels every need with `calibration: "simulation-checked, not validated on real data"`.
