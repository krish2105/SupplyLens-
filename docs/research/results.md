# SupplyLens research results (dissertation package)

All numbers are copied from `artifacts/experiments/*/metrics.json` (metrics, configs and cohorts are committed; weights
and per-run outputs are not). Simulated outcomes are labelled. Runs: 2026-10-21 and, after the session-4 audit fixes,
2026-10-22 (UTC); operations studies 2026-10-26/27 and 2026-10-30. Status and reviewed headline of every run:
`evaluations/study_registry.json`. Course documents quote numbers only from `docs/course/metrics.md`, generated from the
same files by `scripts/course_metrics.py`.
Hardware: Apple M4 Pro, 24 GB, macOS 27; Python 3.12.13, LightGBM 4.7.0, PyTorch 2.14.1 (MPS).

## Research questions

1. **F1** — Do trained models (LightGBM quantile, compact quantile TCN) improve daily unit-sales forecasts over seasonal naive?
2. **S1** — Holding the inventory policy fixed, do better forecasts produce better simulated inventory outcomes?
3. **R2** — Does explicit effective-date and supersession logic change which supplier-terms version is cited?
4. **R1 / C1** — How do lexical, vector and hybrid retrieval compare on public expert-labelled contract corpora?
5. **IB** — How does SupplyLens' deterministic replenishment logic score on InventoryBench's official evaluator?
6. **AGT** — Does the stateful investigator end in the oracle's state across frozen business scenarios without unauthorised writes?
7. **Operations studies (Phase 7)** — E1 CO2 trade-off, FA1 fair allocation, W1 error measures and weather, D1 delay
   risk, G1 generated answers, JS1 receiving-floor scheduling, PM1 predictive maintenance, QC1 visual inspection: see
   [Operations studies](#operations-studies-phase-7).

## F1 — forecasting, protocol 2.1.0 (`F1-20261023T180239Z`, current)

**What changed (Phase 5).** 2.1.0 is 2.0.0 with one defect fixed: panel dates were reloaded from disk in the wrong unit
(pandas 3 stores microseconds, the loader read nanoseconds), so every day in the TCN's input window had the same weekday.
The TCN, which always runs in a separate process that reloads the panel, never saw weekday information in training or in
serving (ML-P5-01). Seasonal naive and LightGBM run in-process and are reproduced exactly (the LightGBM model files are
byte-identical). `F1-20261022T090206Z` (2.0.0) is superseded; protocol 1.0.0 was superseded earlier (its baseline was wrong
beyond day 7, audit F01). Protocol unchanged: rolling test origins 2011-10-13 and 2011-11-10, validation origins
2011-08-18 and 2011-09-15, 503 products with ≥150 selling days in the year before 2011-08-18, same grid and selection rule.
**Not an untouched holdout** (D-042): both test windows have now been seen by three protocol versions.

Selection (mean validation pinball): naive 7.814, LightGBM
4.951, TCN 4.885 → champion **tcn** (registered as 2.1.0; 2.0.0 retired).

| Test origin | Model | MAE | MASE | Pinball (mean) | 80% coverage | Width | Raw crossing |
|---|---|---|---|---|---|---|---|
| 2011-10-13 | Seasonal naive | 20.57 | 1.042 | 8.105 | 81.0% | 33.2 | 0.00% |
| 2011-10-13 | LightGBM quantile | 13.99 | 0.679 | 5.138 | 86.3% | 37.0 | 7.13% |
| 2011-10-13 | Quantile TCN (seed 0) | 13.82 | 0.664 | 5.101 | 85.1% | 35.2 | 3.44% |
| 2011-11-10 | Seasonal naive | 22.12 | 1.135 | 8.591 | 75.5% | 34.1 | 0.00% |
| 2011-11-10 | LightGBM quantile | 15.06 | 0.783 | 5.513 | 84.2% | 42.9 | 7.80% |
| 2011-11-10 | Quantile TCN (seed 0) | 14.83 | 0.767 | 5.340 | 85.2% | 37.7 | 3.06% |

TCN over seeds 0/1/2 at the last origin: MAE 14.83 ± 0.02.

Paired comparison of per-product MAE averaged over both test origins (product-level bootstrap, 2,000 resamples):

| Comparison | Mean difference | 95% CI | First model better on | Reading |
|---|---|---|---|---|
| LightGBM − naive | -6.82 | -8.73 to -5.25 | 89.9% | difference detected |
| TCN − naive | -7.02 | -8.94 to -5.45 | 90.9% | difference detected |
| TCN − LightGBM | -0.20 | -0.46 to 0.03 | 42.3% | no clear difference detected |

**Finding.** Both trained models cut daily absolute error by about a third against seasonal naive (pooled MAE naive
21.35, LightGBM 14.52, TCN 14.32).
**Correction:** 2.0.0 reported TCN ahead of LightGBM with an interval excluding zero; with weekday inputs restored the
interval includes zero, so no difference between the two trained models is claimed. No equivalence test was run.

## S1 — inventory consequences (`S1-20261022T092040Z`, **superseded by S2**)

**Superseded (Phase 5):** its TCN rows used the weekday-blind TCN 2.0.0 and it sized orders with its own formula, not
the product's planner. Kept for the record; S2 below replays the product's actual decision logic.


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

600 instances scored: the benchmark's real-trajectory instances (3 lead-time settings × 200; `instances` in the run's
metrics.json), official `eval/evaluate_results.py` at pinned commit 62b1f11, mean normalised reward. The benchmark has
1,320 instances at that commit (counted from its file tree on 2026-11-10): the other 720 are synthetic trajectories
(3 × 240), one folder level deeper, which the study's file pattern (`benchmark/*/*/*/test.csv`) did not reach, so they
were never scored. Earlier text said the score covered all 1,320 (corrected, DOC-P8-01; the synthetic part is IB-P8-01).

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

## F2 — segments, calibration and bias (`F2-20261023T182141Z`, **exploratory**)

Frozen config `ml/configs/forecast_study_f2.json`. On F1 2.1.0's cohort and artifacts, two rules were fitted on the
validation origins only and applied once to the (already seen) test origins: a per-segment model choice
(Syntetos–Boylan classes from the 365 days up to each origin) and a per-family interval scale. The run first reproduced
F1's recorded test MAE for every model and origin exactly.

| Model | Test 80% coverage (Oct / Nov) | Below q10 | Above q90 | Sum of medians ÷ volume |
|---|---|---|---|---|
| Seasonal naive | 81.0% / 75.5% | 8.5% / 12.3% | 10.5% / 12.2% | 96% / 106% |
| LightGBM | 86.3% / 84.2% | 5.5% / 5.6% | 8.2% / 10.2% | 50% / 50% |
| TCN | 85.1% / 85.2% | 6.2% / 4.6% | 8.8% / 10.3% | 42% / 42% |

**Findings.**
1. **Segmentation does not discriminate this cohort at daily grain:** every product is "lumpy" (94%) or "erratic" (6%);
   TCN won both segments on validation, so the segment composite equals TCN. On the test windows LightGBM was ahead in the
   small erratic segment (MAE 45.2 vs TCN 47.0, 58 product-origins) — a
   post-hoc observation, not a selection.
2. **Intervals are not symmetric-calibratable:** 39% of product-days are zero and the lower quantile sits at
   zero for them; any scale below 1 lifts the lower bound and drops every zero day, so validation coverage jumps from
   about 61% to about 85% between s = 0.9 and 1.0 and the rule stays at 1.0. The trained models' intervals are
   asymmetric: too few observations fall below q10 (about 5%), about the nominal 10% above q90.
3. **Volume bias:** the trained models' medians sum to 50% / 50% (LightGBM) and 42% / 42% (TCN) of realised volume —
   medians of right-skewed daily sales, as S1 found. Any policy that orders medians under-stocks.

## S2 — decisions through the product's own logic (`S2-20261023T183015Z`, **simulated, exploratory**)

Frozen config `ml/configs/decision_study_s2.json`. Every policy runs the shipped order-quantity code: lead-time demand at
a 90% service level with one requirement per supplier lead time (`supplylens_opt.replenishment.assess`) and the
coverage-first CP-SAT planner with MOQ, pack multiples, two suppliers per product, budget and the simulation's own open
orders. Terms follow the uci-sim-ops recipe with a study-only seed (median unit cost £1.01, median margin
£0.81); demand is recorded daily sales (lost-sales simulation); 503 products, four weekly reviews
2011-11-10 … 2011-12-01, results over 2011-11-11 … 2011-12-08. Forecast MAE over the review windows: naive
21.1, LightGBM 15.4, TCN 14.9.

| Policy | No budget limit: fill / stock-out product-days / cost £ | Workspace-scaled budget: fill / stock-out days / cost £ |
|---|---|---|
| product_seasonal_naive | 97.2% / 145 / 12,957 | 77.5% / 2547 / 78,442 |
| product_lightgbm | 94.4% / 264 / 19,842 | 83.7% / 1614 / 52,302 |
| product_tcn | 96.0% / 224 / 13,673 | 96.0% / 224 / 13,673 |
| simple_base_stock | 96.8% / 207 / 11,983 | 83.5% / 1734 / 54,427 |
| perfect_foresight_reference | 92.0% / 731 / 19,421 | 92.0% / 731 / 19,421 |

Cost = lost margin + holding over 28 days (simulated). Paired per-product differences (bootstrap 95% CI), no budget limit:
TCN − naive +1.42 [-1.64, 4.82];
LightGBM − naive +13.69 [4.67, 25.08];
naive − simple base stock +1.94 [-1.26, 5.48].

**Findings.**
1. **Lower MAE did not mean lower simulated cost.** Without a budget limit the no-forecast base-stock rule was cheapest,
   naive and TCN were not clearly different, and LightGBM — more accurate than naive — was clearly *more* expensive: its
   smaller medians feed smaller lead-time-demand requirements and more stock-outs.
2. **Under a binding budget the planner's allocation dominates.** With the workspace-scaled budget the policies whose
   requirements exceed the budget are rationed; coverage-first maximises units covered regardless of margin, so naive and
   LightGBM lost far more margin. TCN's smaller requirements fitted the budget. That is an interaction with budget
   allocation, not evidence of forecast value — and it exposes a planner issue (PLAN-P5-01: rationing ignores margin).
3. The perfect-foresight reference is not an upper bound here (it orders exactly the truncated window's sales after lead
   time, so early-window stock-outs remain).

**Limits.** Simulation with assumed terms and costs, one 28-day pre-Christmas window already seen by earlier studies,
recorded sales as demand. Business benefit is **not** shown; a pilot with real operational data is needed (EXT-03).

## R3 — answer support: abstention and ambiguity (`R3-20261023T181121Z`, current)

`evaluations/answer_support_study.py`, frozen task set `evaluations/tasksets/r3_answer_support_v1.jsonl` (535 questions,
labels by construction from simulated and fictional documents, **not human-reviewed**). Thresholds were grid-searched on
the development half (macro accuracy over categories) and scored once on the test half; the chosen values are the
constants in `knowledge/retrieve.py`. Correct = answered with the expected passage (answerable, paraphrase, named
supplier) or not answered (unknown product, out of scope) or flagged/not answered (ambiguous).

| Category (test n) | Before Phase 5 | Hybrid, new rule | Lexical only (hosted demo), new rule |
|---|---|---|---|
| ambiguous (4) | 0 | 3 | 4 |
| answerable (45) | 45 | 45 | 45 |
| named_supplier (4) | 4 | 3 | 0 |
| out_of_scope (26) | 0 | 10 | 10 |
| paraphrase (172) | 172 | 121 | 121 |
| unknown_product (5) | 5 | 5 | 5 |

**Findings.** Ambiguity detection works (unscoped questions several suppliers answer equally are no longer answered with
one supplier's clause), and about 40% of out-of-scope questions are now declined. But retrieval-only signals cannot tell
an out-of-scope question from a reworded in-scope one: on the development half, out-of-scope questions naming a supplier
had *higher* embedding similarity (median 0.65) than reworded answerable ones (0.58), and nearly all of both contained
words no document uses. So 51 of 172 reworded test questions are now listed as related passages instead of answered,
and with lexical search alone (the hosted demo) questions that name a supplier are wrongly flagged as ambiguous (0/4).
Closing this needs an evaluated reader model and human-reviewed questions (EXT-06), not threshold tuning.

## Operations studies (Phase 7)

Eight studies added on 2026-10-26/27 (E1, FA1, W1, D1, G1) and 2026-10-30 (JS1, PM1, QC1). Each number below is copied
from the run's `metrics.json` (the source path is in a comment beside it); the kind of each number is stated. None is a
real business outcome. Course documents quote the same values from `docs/course/metrics.md`.

### E1 — cost, service and CO2 trade-off (`E1-20261026T200641Z`, simulation)

**Question.** What does cutting the plan's CO2 cost in service and spend, and does an evolutionary search find the same
trade-off as the exact solver?
**Data.** Real UCI scope: 40 products, two offers each, 23,980 units required, £20,000 weekly budget
<!-- source: artifacts/experiments/E1-20261026T200641Z/metrics.json scope -->. Terms and stock are simulated; lanes are
assumed from the quoted lead time; CO2 factors are rounded UK DESNZ freight factors (road 0.1, sea 0.016 kg CO2e per
tonne-km); unit weight 0.5 kg is assumed (the data records no weights).
**Method.** Exact ε-constraint with CP-SAT at 21 CO2 caps against NSGA-II (pymoo, 3 seeds); hypervolume against a
common reference point.
**Result.** Without a cap the plan leaves 4,565 units short and emits 1,550,646 g CO2e; capping CO2 at 95 % costs 9 more
units (4,574) <!-- source: exact.points[0..1] -->. The registry's reviewed headline: halving CO2 costs 13.8 points of
coverage. NSGA-II reaches 98.07–98.49 % of the exact front's hypervolume, but 35–43 of its about 116 front points are
dominated by exact points <!-- source: nsga2.per_seed -->; the exact solve took 3.1 s <!-- source: exact.seconds -->.
**Limits.** Simulated terms and stock; assumed lanes, factors and weights; the exact front is sampled at 21 caps, so its
hypervolume is a lower bound.

### FA1 — fair allocation under a binding budget (`FA1-20261026T200912Z`, simulation)

**Question.** When the budget binds, are customers in every country group served equally, and what does reweighing
change?
**Data.** Real UCI scope and recorded country purchase shares over 365 days; stock, terms and budget simulated; demand is
the champion forecast.
**Method.** A product's shortfall is attributed to its customers by past purchase share; the coverage objective is
reweighed by a group weight with strength α; the chosen α is the highest overall coverage among weightings whose
worst-to-best ratio is at least 0.8 (the four-fifths screen).
**Result.** Without reweighing the best group gets 82.5 % coverage and the worst 50.8 % (gap 31.69 points, ratio 0.6159)
<!-- source: baseline.summary -->. α 0.4 cuts the gap to 12.24 points (ratio 0.8484) for 1.39 points of total coverage
<!-- source: recommended -->. Full reweighing (α 1) over-corrects: overall coverage 73.94 % <!-- source: reweighed.overall_coverage -->.
**Limits.** One scope, one date, deterministic allocation; the attribution rule is an assumption; shortage weights are
study-only (D-097, PLAN-P5-01).

### W1 — error measures, Prophet, XGBoost and weather (`W1-20261027T055557Z`, historical backtest)

**Question.** How do Prophet and XGBoost compare on MAE, RMSE, WAPE and MAPE, and does London weather improve the
forecasts?
**Data.** UCI daily units; Open-Meteo historical weather for London (CC BY 4.0); 13 weekly origins from 2011-09-05 to
2011-11-28, 7 days ahead; 91 total-level points and 4,550 product-day points (50 products) <!-- source: results.*.points -->.
**Method.** Refit at each origin; bootstrap of origins (2,000 resamples) for the weather effect.
**Result.** On total daily units: WAPE seasonal naive 29.74 %, Prophet 28.04 %, XGBoost 24.55 % <!-- source: results.total.models -->.
Adding weather made no clear difference to either model (95 % intervals span zero) <!-- source: results.total.weather_effect -->.
At product level daily demand is intermittent and WAPE is above 100 % for every model (registry notes).
**Limits.** One retailer, one city's weather, one autumn; observed weather stands in for a forecast (an upper bound);
MAPE leaves out zero-sales days; Prophet on the total only.

### D1 — supplier delay risk (`D1-20261027T053410Z`, simulation; method check)

**Question.** Can a model trained on past orders flag late deliveries ahead of time?
**Data.** A generated order history (supplier reliability, sea lanes, December peak, order size): 8,112 training and
2,392 test orders, temporal split at 2011-07-01 <!-- source: data -->.
**Result.** AUC: each supplier's past late rate 0.692, logistic regression 0.7674, LightGBM 0.7549
<!-- source: models.*.auc -->. The models recover the effects that were put into the generator (sea lane and supplier).
**Limits.** The history is generated, so this checks the method only; real receipts from the ERP receipt feed would
replace the generator.

### G1 — generated answers that cite or withhold (`G1-20261027T061059Z`, offline evaluation with generated labels)

**Question.** Are generated answers correct and cited, and is nothing generated where no passage answers?
**Data.** 271 generated questions over simulated and fictional agreements; labels by construction, not human-reviewed
<!-- source: tasks -->. Local model qwen2.5:7b at temperature 0 (D-094; off in the hosted demo, D-041).
**Result.** Answerable 108 of 108 and reworded 88 of 88 answered with every asked figure in a cited passage and correct
citations; out-of-scope 0 of 48 and unknown product 0 of 10 answered; ambiguous 1 of 9 answered; questions naming only a
supplier 0 of 8 answered (an over-refusal, KNOW-P7-01) <!-- source: categories -->. Latency p50 2.81 s, p95 4.01 s
<!-- source: latency_seconds -->.
**Limits.** Generated labels; the figure check would pass a correct figure next to a wrong one; one local model.

### JS1 — receiving-floor scheduling (`JS1-20261030T191602Z`, simulation)

**Question.** How much shorter is an optimal receiving-floor schedule than the dispatch rules a floor lead would use?
**Data.** Nine instances (10, 20 and 40 orders × 3) on four stations; order volumes from real UCI weekly sales; routes,
handling minutes and due slots assumed.
**Method.** CP-SAT (8 workers, 20 s) against FIFO, SPT, EDD and most-work-remaining list schedules; check on the published
Fisher–Thompson ft06 instance (CP-SAT 55 = known optimum 55) <!-- source: check_ft06 -->.
**Result.** Average makespan gap against CP-SAT: FIFO 11.91 %, SPT 11.11 %, EDD 13.0 %, most work remaining 11.38 %
<!-- source: summary.makespan_gap_vs_cp_sat -->; CP-SAT proved 7 of 9 makespans optimal <!-- source: summary -->.
No single rule is best at every size.
**Limits.** Static one-shift job shop with no breakdowns or arrivals; assumed routes and times.

### PM1 — predictive maintenance (`PM1-20261030T192104Z`, published synthetic dataset and simulation)

**Question.** Can failures and remaining life be predicted early enough to replace run-to-failure and fixed-interval
maintenance?
**Data.** (a) UCI AI4I 2020 (CC BY 4.0; synthetic data modelled on a milling process), 10,000 cycles, 71 failures in the
test split; (b) a simulated motor fleet <!-- source: ai4i_2020, fleet_rul -->.
**Result.** (a) LightGBM AUC 0.9795 against logistic regression 0.9283; at a threshold chosen on validation with assumed
costs it catches 61 of 71 test failures with 135 inspections, £40,250 against £142,000 for running to failure
<!-- source: ai4i_2020.models, run_to_failure_cost_gbp -->. (b) Remaining-life RMSE: ridge 18.9, 1D-CNN 19.25 cycles: the
CNN does not beat the simple baseline (a negative result kept) <!-- source: fleet_rul.accuracy -->.
**Limits.** AI4I 2020 is itself synthetic; the fleet, its degradation and all costs are assumed; one split, one fleet.

### QC1 — visual inspection at goods-in (`QC1-20261030T193358Z`, simulation)

**Question.** Can a small CNN flag surface defects at goods-in well enough to replace inspecting every item by hand?
**Data.** Images generated from stated rules: 6,000 training, 1,500 validation, 3,000 test, 862 test defects
<!-- source: data -->.
**Result.** AUC: CNN 0.9972, hand-made features 0.9462 <!-- source: models.*.auc -->. Checking only what the CNN flags
catches 98.72 % of defects (11 escapes) at £419.40 against £900 for inspecting everything, with assumed costs
<!-- source: models.cnn.policy, inspect_everything_cost_gbp -->.
**Limits.** Generated images are easier than photographs; one defect per image; assumed costs: a method check.

## Course coverage studies (Phase 8)

Added on 2026-11-10 so that every weekly lab topic of the unit has a project study (see `docs/course/coverage.md`). As
above, each number is copied from the run's `metrics.json` (source path in a comment) and its kind is stated; none is a
real business outcome. Real logistics data (LaDe, Amazon Last Mile) needs the owner's approval, so FE1, ET1 and RT1 run on
generated data.

### FE1 — fuel-inefficient trips (`FE1-20261110T120111Z`, simulation; method check)

**Question.** Can trip telemetry flag fuel-inefficient trips, and predict litres per 100 km, better than a fleet-average rule?
**Data.** 15,965 generated trips (60 vehicles in three classes, 72 drivers, 12 months); train months 1-8, validation 9-10,
test 11-12 (2,662 trips) <!-- source: data -->. Inefficient = measured L/100 km above 1.15 x the class-and-payload reference.
**Result.** L/100 km MAE: class average 2.05, ridge 0.91, LightGBM 0.85 <!-- source: models.regression_test -->. Flagging:
AUC fleet-average rule 0.886, logistic regression 0.956, LightGBM 0.953; F1 0.62, 0.76, 0.76; share of the test months'
excess fuel on flagged trips 46 %, 38 %, 40 % <!-- source: models.classification_test -->. Excess fuel 7,301.6 L, or
18,253.9 kg CO2 at an assumed 2.5 kg per litre <!-- source: data.test_excess -->.
**Limits.** Generated data recovers only the effects put in (idle time, driver, speed, stops, cold); LightGBM does not
beat logistic regression; the rule captures more excess litres because it sees the measured fuel and long heavy trips
carry most of the excess. No real telematics or fuel-card data.

### W2 — LSTM forecasting (`W2-20261110T120750Z`, historical backtest)

**Question.** Does a small LSTM forecast total daily units better than XGBoost, Prophet and seasonal naive?
**Data.** UCI Online Retail II (same file as F1 and W1), W1's protocol: 13 Monday origins 2011-09-05 to 2011-11-28, 7 days
ahead, refitted at each origin, 91 points; no weather <!-- source: protocol -->. Seasonal naive reproduces W1's values
exactly <!-- source: results.seasonal_naive_reproduced.check -->.
**Result.** WAPE: LSTM 0.2651 +/- 0.0132 (5 seeds), XGBoost 0.2455 and Prophet 0.2804 (from W1, without weather),
seasonal naive 0.2974; RMSE 7,666.7, 7,498.4, 7,617.4 and 8,909.4 <!-- source: results -->. No seed beat XGBoost on WAPE;
the LSTM's gain over seasonal naive has a 95 % interval of -1,555.8 to 63.5 units, so it is not clear
<!-- source: results.lstm_vs_seasonal_naive -->.
**Limits.** One target series and 91 points; only the loss (Huber) was chosen, on 9 earlier validation origins; W1 stored no
per-day forecasts, so the comparison with XGBoost and Prophet is not paired.

### B1 — bias mitigation for a failure classifier (`B1-20261110T120717Z`, published synthetic dataset)

**Question.** Do re-weighting, SMOTE, threshold moving and adversarial debiasing lower cost and narrow the gap in recall
between machine types?
**Data.** UCI AI4I 2020 with PM1's split and assumed costs (missed failure GBP 2,000, inspection GBP 150); 71 test failures:
Type L 46, M 18, H 7 <!-- source: data -->. PM1's logistic result is reproduced exactly <!-- source: split_check -->.
**Result.** Logistic regression, expected cost: no correction GBP 118,550; class weights 65,350; group-and-class weights
70,100 (recall gap 0.036); SMOTE 70,000 (recall gap 0.814); threshold moving 74,700 <!-- source: methods.logistic_regression -->.
Adversarial debiasing (Zhang et al., 2018; 5 seeds, strength 0.03 chosen on validation): recall gap 0.1133 +/- 0.0188
against 0.2205 with the adversary off, at GBP 72,540 against 65,110 <!-- source: adversarial -->.
**Limits.** Type H has 7 test failures, so one failure moves its recall by 14 points; SMOTE made 28 of 5,602 synthetic
failures Type H <!-- source: smote -->; debiasing narrows the gaps mainly by raising false alarms; for LightGBM the methods
differ within noise. Type is a product variant, not a protected human attribute.

### ET1 — delivery arrival times (`ET1-20261110T120540Z`, simulation)

**Question.** How close can a model get to the delivery time, and how honest are its intervals for new couriers?
**Data.** A generated delivery history (couriers, regions, hour, distance, stops ahead, weekday); January-April train,
May-June test (66,197-67,296 test parcels per seed, 3 seeds); 4 couriers join in the test period <!-- source: data -->.
**Result.** MAE: region-by-hour average 30.59 min, LightGBM 12.37, the generator's own expected time 10.39 (the floor);
within 30 minutes 59 % and 92 % <!-- source: results.summary_over_seeds -->. New couriers: LightGBM MAE 27.13 min. The
80 % quantile interval covers 74 % overall, 78 % for known couriers and 34 % for new ones (mean width 31.8 min).
**Limits.** Generated data and straight-line distances; the cold start is where the method fails.

### RT1 — last-mile routes with windows and capacity (`RT1-20261110T120815Z`, simulation)

**Question.** How much shorter and more punctual is an OR-Tools plan than simple heuristics?
**Data.** 15 generated delivery days (20, 40, 80 stops x 5 seeds) with van capacity and time windows <!-- source: data -->.
**Result.** Late stops: OR-Tools 0, window-aware nearest neighbour 4, nearest neighbour ignoring windows 225, fixed angle
order 240 <!-- source: results.summary -->. Distance saving against the window-aware nearest neighbour: 30.5 %, 34.4 %,
39.4 % at 20, 40, 80 stops; against the fixed order 2.1 %, 8.6 %, 28.2 %; the nearest neighbour that ignores windows is
12.0 % and 9.5 % shorter at 20 and 40 stops and level at 80. Vans at 80 stops: 4 against 5.8.
**Limits.** Straight-line distances; the fixed order is a stand-in, not a real driver's sequence; fuel (9 L/100 km) and
CO2 (E1's 0.1 kg per tonne-km, 0.5 t payload) are assumed, so van CO2 is probably understated; wall-clock solver limit.

### X1 — contract-term extraction (`X1-20261110T121508Z`, human-labelled)

**Question.** How many of the clauses and fields CUAD's experts labelled does a rule-based extractor find, and how does it
compare with picking the top BM25 paragraphs for each field?
**Data.** CUAD v1 (CC BY 4.0): the 73 supply, distribution and manufacturing contracts, 805 expert labels in the nine
scored categories (parties, agreement and effective dates, expiry, renewal, termination for convenience, exclusivity,
minimum commitment, price restrictions) <!-- source: data, mapping -->.
**Result.** Micro overlap F1: rules 0.5086 (precision 0.4765, recall 0.5453), top BM25 paragraph 0.1948, top three
0.173; exact-span F1: rules 0.3542 <!-- source: overall -->. On 437 other CUAD contracts (4,456 labels) the rules score
overlap F1 0.505 <!-- source: held_out_check -->. The top three paragraphs recall more expiry (0.84 vs 0.69), renewal
(0.91 vs 0.74) and minimum-commitment (0.42 vs 0.28) labels, at about a quarter of the precision <!-- source: per_field -->.
**Limits.** In-sample rules (written after reading about ten labels per category); price is scored against Price
Restrictions (13 labels); MOQ and lead time have no CUAD category; plain text only. In the product the fields are a draft
in Policies › Extracted terms and never feed planning; confirming a field is not built.

### AS1 — the status assistant (`AS1-20261110T121815Z`, offline evaluation with generated labels)

**Question.** Does the read-only assistant answer stock, order and terms questions from cited records, ask which product
when several match, and withhold change requests, unknown ids and out-of-scope questions?
**Data.** 57 questions generated from the synthetic e2e fixture (36 products, 2 suppliers, orders in three states): stock
10, terms 8, order 6, ambiguous 5, change requests 12, unknown ids 8, out of scope 8 <!-- source: categories -->.
**Result.** Answered correctly 24 of 24 answerable, product choice offered on 5 of 5 ambiguous, withheld 28 of 28 that
must be withheld; 61 sentences, none without a citation; no wrong answer <!-- source: overall -->. The first run
(`AS1-20261110T121733Z`, superseded) withheld 1 of 6 order questions as a change request.
**Limits.** Templates written by the rules' author (an upper bound for real wording; human-written questions G2 are open);
called in-process (the HTTP layer is covered by `tests/test_assistant.py`); one workspace and location.

### RED1 — red team on generated answers (`RED1-20261110T120752Z`, offline evaluation)

**Question.** Do adversarial questions and poisoned documents make the answer layer state planted figures, leak its
instructions or other workspaces' records, claim actions, or break its limits?
**Data.** 17 attacks on the simulated UCI Research workspace through `POST /api/v1/evidence/answer` with the local model
(qwen2.5:7b, temperature 0): 13 questions and 4 agreements poisoned through the upload endpoint; 2 control questions
<!-- source: cases, by_kind, controls -->. Pass rules were written before the run (`evaluations/redteam_cases.py`).
**Result.** The first run (`RED1-20261110T120450Z`, superseded) held 15 of 17: a poisoned agreement's payment link and a
planted supplier name were repeated in cited answers, and in one more case the model stated planted figures that a
citation check then withheld. Two defences followed (`generate.py`: text addressed to a model is not shown to it; answers
with a link or address are withheld). The rerun held 17 of 17: 7 by the extractive layer (nothing generated), 3 by the
generation checks, 7 answered within the rules; both controls answered correctly <!-- source: held_by, controls -->.
**Limits.** 17 hand-written attacks and one model: a screen, not a proof; pattern rules could miss a reworded leak; the
screen recognises text addressed to a model, not a false claim written as ordinary contract text.

## Limitations

- Sales are a demand proxy; stockouts and lost sales are unobserved. Cost and term parameters in S1/S2 are assumptions.
- One retailer (UCI); results may not transfer. M5 was not used (owner decision).
- F1 2.1.0 uses two rolling test windows (Oct–Dec 2011), seen by protocols 1.0.0 and 2.0.0 and both pre-Christmas; a
  confirmatory test needs data no protocol has looked at (UCI ends on 2011-12-09; new data or another licensed dataset).
- F2 and S2 are exploratory for the same reason; S2's terms and costs are simulated.
- R2 and R3 questions are generated and not human-reviewed (the R2 review sheet is still open: EXT-06).
- R2 questions are synthetic and not human-reviewed; no generative LLM was evaluated (owner decision).
- The investigator is deterministic, so "agent" results concern orchestration and controls, not model reasoning.

## Reproduce

```bash
uv run python evaluations/forecast_study.py --config ml/configs/forecast_study_v2_1.json   # F1 2.1.0 (~20 min, M4 Pro)
uv run python evaluations/forecast_segments_study.py                                     # F2 (needs F1 2.1.0 artifacts)
uv run python evaluations/decision_study.py                                              # S2 (needs F1 2.1.0 artifacts)
uv run python evaluations/answer_support_study.py                                        # R3 (needs bge-m3 via Ollama)
uv run python evaluations/retrieval_study.py
uv run python evaluations/inventorybench_study.py
uv run python evaluations/agent_study.py
uv run --with pymoo==0.6.2 python evaluations/emissions_study.py                       # E1
uv run python evaluations/fairness_study.py                                             # FA1
uv run --with prophet==1.5.0 --with xgboost==3.0.2 python evaluations/weather_study.py  # W1 (Open-Meteo archive)
uv run python evaluations/delay_risk_study.py                                           # D1
SUPPLYLENS_GENERATION_ENABLED=true uv run python evaluations/generation_study.py        # G1 (local Ollama model, API running)
uv run python evaluations/scheduling_study.py                                           # JS1
python3 -I scripts/download_datasets.py --dataset ai4i_2020 && uv run python evaluations/maintenance_study.py  # PM1
uv run python evaluations/vision_qc_study.py                                            # QC1
uv run python evaluations/fuel_study.py                                                 # FE1
uv run python evaluations/lstm_study.py                                                 # W2 (PyTorch in a child process)
uv run --with scikit-learn==1.7.2 --with imbalanced-learn==0.14.0 python evaluations/imbalance_study.py  # B1
uv run python evaluations/eta_study.py && uv run python evaluations/routing_study.py   # ET1, RT1
SUPPLYLENS_GENERATION_ENABLED=true uv run python evaluations/redteam_study.py           # RED1 (bootstrapped *_test database)
uv run python evaluations/extraction_study.py                                           # X1 (CUAD downloaded)
uv run python evaluations/assistant_study.py                                            # AS1 (*_test database with the e2e fixture)
uv run python scripts/course_metrics.py             # docs/course/metrics.md from the registry
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
