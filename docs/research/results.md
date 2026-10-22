# SupplyLens research results (dissertation package)

All numbers are copied from `artifacts/experiments/*/metrics.json` (artifacts are git-ignored; rerun
commands below regenerate them). Simulated outcomes are labelled. Date of runs: 2026-10-21 (UTC).
Hardware: Apple M4 Pro, 24 GB, macOS 27; Python 3.12.13, LightGBM 4.7.0, PyTorch 2.14.1 (MPS).

## Research questions

1. **F1** — Do trained models (LightGBM quantile, compact quantile TCN) improve daily unit-sales forecasts over seasonal naive?
2. **S1** — Holding the inventory policy fixed, do better forecasts produce better simulated inventory outcomes?
3. **R2** — Does explicit effective-date and supersession logic change which supplier-terms version is cited?
4. **R1 / C1** — How do lexical, vector and hybrid retrieval compare on public expert-labelled contract corpora?
5. **IB** — How does SupplyLens' deterministic replenishment logic score on InventoryBench's official evaluator?
6. **AGT** — Does the stateful investigator end in the oracle's state across frozen business scenarios without unauthorised writes?

## F1 — forecasting (`F1-20261021T190101Z`)

Protocol frozen in `ml/configs/forecast_study_v1.json` before the test window was scored.
Cohort: 506 UCI products with at least 150 selling days in the year before 2011-09-15 (selection uses only
data up to that date). Validation origins 2011-09-15 and 2011-10-13; untouched test origin 2011-11-10
(window 2011-11-11 to 2011-12-08), horizon 28 days, quantiles 0.1/0.5/0.9. Selection rule: lowest mean
validation pinball. Each origin refits on labels available at that origin.

| Model | Val. pinball | Test MAE | MASE | Pinball q10 / q50 / q90 | 80% coverage | Width | Raw crossing |
|---|---|---|---|---|---|---|---|
| Seasonal naive | 8.251 | 21.41 | 1.050 | 6.085 / 10.702 / 8.040 | 76.8% | 32.7 | 0.00% |
| LightGBM quantile | 5.421 | 15.37 | 0.793 | 1.913 / 7.687 / 7.151 | 85.1% | 44.0 | 4.45% |
| Quantile TCN (seed 0) | **5.342** | 15.08 | 0.772 | 1.918 / 7.539 / 6.703 | 84.9% | 39.5 | 8.89% |

TCN over seeds 0/1/2: MAE 15.03 ± 0.04, pinball 5.380 ± 0.006. MASE was defined for all 506 series.

Paired per-product MAE differences (series-level bootstrap, 2,000 resamples):

| Comparison | Mean difference | 95% CI | First model better on |
|---|---|---|---|
| LightGBM − naive | −6.03 | −7.28 to −4.83 | 89.3% of products |
| TCN − naive | −6.33 | −7.51 to −5.26 | 88.5% |
| TCN − LightGBM | −0.30 | −0.75 to +0.04 | 39.7% |

**Finding.** Both trained models clearly beat the baseline. TCN vs LightGBM is not distinguishable (CI
includes zero; TCN is better on fewer than half of the products). The TCN is the registered champion only
because the frozen validation rule selected it. Trained models' raw quantiles cross (4–9%), corrected by
the declared rearrangement.

## S1 — inventory consequences (`S1-20261021T193239Z`, **simulated**)

Lost-sales simulation over the F1 test window, weekly review, lead time 3 days, z = 1.2816, holding 25%/year,
unit cost 55% of median selling price (assumptions). Same initial stock and demand path for every condition.

| Forecaster / policy | Fill rate | Stockout product-days | Lost margin + holding (£, 28 days) |
|---|---|---|---|
| Seasonal naive, median + safety | 85.9% | 1,044 | 37,072 |
| LightGBM, median + safety | 79.1% | 1,619 | 53,665 |
| TCN, median + safety | 79.5% | 1,656 | 52,915 |
| Seasonal naive, q90 order-up-to | 95.1% | 210 | 15,670 |
| LightGBM, q90 order-up-to | 95.1% | 236 | 16,395 |
| TCN, q90 order-up-to | 94.9% | 252 | 16,258 |
| Perfect-foresight reference | 89.4% | 1,961 | 27,229 |

**Finding (negative for the trained models).** Lower MAE/pinball did not produce better simulated stock
outcomes. Daily UCI sales are heavy-tailed; summed q50 of LightGBM/TCN covered about 50%/42% of test-window
volume versus 87% for seasonal naive, so median-based ordering under-stocks. Changing the *policy* to a q90
order-up-to target reduced simulated cost by about £21k for every forecaster, and differences between
forecasters became small (naive was cheapest by about £0.6k). The product's replenishment basis was changed to the
q90 sum on this evidence (DECISIONS D-024) and has since been replaced by the lead-time-demand model (L1 below, D-032). The perfect-foresight reference is not an upper
bound with lead times (it only covers each review window).

## R2 — time-aware supplier terms (`R2-20261021T191153Z`)

118 questions generated from the UCI workspace's simulated agreements (not human-reviewed): current terms,
amendment in force, amendment known but not yet in force, historical cutoff before the amendment was known,
future effective date, and 10 unknown products.

| Condition | Top-1 citation correct | Wrong version at top | Abstention on unknown |
|---|---|---|---|
| Knowledge cutoff only (temporal logic off), hybrid | 92.6% | 7.4% | 100% |
| Temporal logic on, lexical only | 100% | 0% | 100% |
| Temporal logic on, hybrid | 100% | 0% | 100% |

Cross-tenant probes from the Demo workspace: 0 leaked chunks in 60 queries. **Caveat:** questions come from
the same simulated records that generated the documents, so this measures the temporal mechanism, not
real-world contract understanding.

## R1 — ACORD clause retrieval (`R1-20261021T191153Z`)

3,931 clauses, 56 judged test queries (one excluded because its id does not match the qrels' quoting).
Relevant = grade ≥ 2.

| Retrieval | nDCG@10 | Recall@10 | MRR@10 | p95 latency |
|---|---|---|---|---|
| PostgreSQL full-text (lexical, not BM25) | 0.062 | 0.062 | 0.133 | 19 ms |
| bge-m3 vector | **0.107** | **0.117** | **0.237** | 68 ms |
| Hybrid RRF | 0.089 | 0.098 | 0.189 | 81 ms |

**Finding (negative for the hybrid).** On short clause-category queries, vector-only beats the hybrid; the
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

## AGT — investigator evaluation (`AGT-20261021T192432Z`)

57 frozen scenarios × 3 trials against the test database: 44 reference-case dates × budgets, 2 delayed-knowledge,
missing stock record, conflicting terms, two role denials, administrator approval, self-approval, stale terms,
timeout-after-commit, fail-before-commit retry, crash after submit, approved happy path. Expected outcomes come
from a brute-force oracle over hand-written ground truth (not CP-SAT).

Verified completion 100% (171/171 trials), unauthorised external writes 0, identical outcomes across trials,
median run 67 ms, 6.0 tool calls per run, 0 LLM tokens.

## Limitations

- Sales are a demand proxy; stockouts and lost sales are unobserved. Cost parameters in S1 are assumptions.
- One retailer (UCI); results may not transfer. M5 was not used (owner decision).
- F1 uses one test window (28 days before Christmas 2011), which is seasonally unusual.
- R2 questions are synthetic and not human-reviewed; no generative LLM was evaluated (owner decision).
- The investigator is deterministic, so "agent" results concern orchestration and controls, not model reasoning.

## Reproduce

```bash
uv run python evaluations/forecast_study.py
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
