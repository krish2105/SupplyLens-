# Phase 5 — AI/ML, retrieval, optimisation and MLOps

**Dates:** 2026-10-23/24 (UTC) · **Start:** `main` @ `36f4f9d` (after Phases 3, 4 and 4B in another account) ·
**Commits:** see `git log` after `36f4f9d` · **Owner brief:** Phase 5 (forecasting, decision-level evaluation, supplier-document
retrieval, MLOps). No generative model was introduced (D-041); purchasing stays deterministic and approval-gated.

Evidence IDs `P5-E..` → [`../EVIDENCE.md`](../EVIDENCE.md); issues → [`../ISSUES.md`](../ISSUES.md); product decisions
D-081 … D-087 → root [`DECISIONS.md`](../../../DECISIONS.md); research numbers → [`docs/research/results.md`](../../research/results.md).

**Evidence kinds used below** — *historical backtest* (real UCI sales, forecasts scored after the fact); *simulation*
(assumed terms, costs or demand); *offline evaluation* (generated question sets, labels by construction); *unit/integration
test* (code behaviour). There are **no real-world outcomes**: no pilot, no real purchase orders, no human-reviewed labels.

## 0. Context and environment (verified)
- `main` @ `36f4f9d`, clean; CI green on the last three pushes. Handoff records read; claims re-checked in code.
- Local data: the development database `supplylens` holds UCI Online Retail II (529,744 daily rows, 4,707 products) and
  the F1 2.0.0 registry; it was still at migration 0008 and was **backed up** (`pg_dump`, 67 MB, scratchpad) and migrated
  to 0010 (7,339 vectors moved). bge-m3 runs locally through Ollama. F1 2.0.0 artifacts (LightGBM files, TCN weights,
  TCN predictions, panel) were on disk.
- Compute: Apple M4 Pro, local only; the heaviest run (F1 2.1.0) took 19 minutes. No cloud spending.

## 1. Mission A — demand forecasting

### Findings
| ID | Sev. | Finding | Evidence kind | Status |
|---|---|---|---|---|
| ML-P5-01 | **P1** | Panel dates saved as raw integers (pandas 3: microseconds) were reloaded as nanoseconds, so every day landed in January 1970 with **the same weekday**. The TCN always runs in a child process that reloads the panel: its weekday channels were constant in F1 training and in production serving | Code + probe (`load_panel` dates; `tcn_inputs` weekday one-hot all `4`) | Fixed (`panel.py`: dates stored as days, legacy integer files read in their own unit); F1 re-run as 2.1.0 |
| ML-P5-02 | P2 | A product younger than the trained model's 56-day window was **dropped** from the forecast (no per-product fallback), so planning excluded it | Code | Fixed: baseline for that product, flagged |
| P2-ML-01 | P2 | Trained-model success path untested; a missing, tampered or failing artifact failed the whole run even where decision flows allow the baseline | Code | Fixed: fallback to seasonal naive (flag + existing high alert); tests for success, tamper, missing |
| P3-ML-02 | P3 | Model files hashed, then re-read by path (TOCTOU); S1 loaded models without a hash check | Code | Fixed: LightGBM built from verified bytes, TCN `torch.load(BytesIO(verified))`, S1 checks recorded hashes |
| ML-P5-03 | Info | 2.0.0 → 2.1.0: naive and LightGBM reproduce exactly (LightGBM files byte-identical); corrected TCN pooled MAE 14.32 (was 14.26), validation pinball 4.885 (was 4.892). **The 2.0.0 claim "TCN ahead of LightGBM, CI excludes 0" no longer holds**: −0.20 [−0.46, +0.03] | Historical backtest | Recorded; F1 2.0.0 superseded |
| ML-P5-04 | Info | Syntetos–Boylan segmentation at daily grain puts every cohort product in "lumpy" (94%) or "erratic" (6%); validation picks TCN in both, so a segment-wise choice changes nothing | Historical backtest (F2, exploratory) | Recorded |
| ML-P5-05 | P2 | Intervals cannot be calibrated by a symmetric scale: 39% of product-days are zero and q10 sits at 0 for them; scaling below 1 drops every zero day (coverage 61% at s = 0.9 vs 84% at 1.0). Trained intervals are asymmetric (≈5% below q10, ≈10% above q90; 80% interval covers 84–86%) | Historical backtest (F2) | Open: needs a zero-aware calibration (e.g. upper-tail-only conformal) under a new frozen protocol |
| ML-P5-06 | P2 | Trained models' medians sum to 42% (TCN) / 50% (LightGBM) of realised volume — medians of right-skewed daily sales | Historical backtest (F2) | Open: decision logic must not order medians (the product uses lead-time demand at 90%) |
| ML-P5-07 | Info | No untouched holdout exists for UCI: the data end on 2011-12-09 and both test windows have been seen by three protocol versions | Data | External: needs new data or another licensed dataset (EXT-09) |

### Results (historical backtest, F1 2.1.0, 503 products, two rolling 28-day origins)
| Model | Pooled MAE | Test 80% coverage (Oct / Nov) | vs naive (per-product MAE, 95% CI) |
|---|---|---|---|
| Seasonal naive | 21.35 | 81.0% / 75.5% | — |
| LightGBM quantile | 14.52 | 86.3% / 84.2% | −6.82 [−8.74, −5.25] |
| Quantile TCN 2.1.0 (seed 0) | 14.32 | 85.1% / 85.2% | −7.02 [−8.94, −5.45] |

TCN − LightGBM −0.20 [−0.46, +0.03]: **no clear difference**. Not confirmatory (D-042, ML-P5-07).

## 2. Mission B — decision-level evaluation (S2, simulation on historical sales, exploratory)
The product's own order-quantity code drove every policy: lead-time demand at 90% with one requirement per supplier lead
time, then the coverage-first CP-SAT planner with MOQ, pack multiples, two suppliers per product, budget and the
simulation's open orders. 503 products, four weekly reviews 2011-11-10 … 2011-12-01, outcomes 2011-11-11 … 2011-12-08,
terms and costs simulated (uci-sim-ops recipe, study seed 20111110), demand = recorded sales.

| Policy | No budget limit: fill / stock-out product-days / cost (£, 28 days) | Workspace-scaled budget |
|---|---|---|
| Product + seasonal naive | 97.2% / 145 / 12,957 | 77.5% / 2,547 / 78,442 |
| Product + LightGBM | 94.4% / 264 / 19,842 | 83.7% / 1,614 / 52,302 |
| Product + TCN | 96.0% / 224 / 13,673 | 96.0% / 224 / 13,673 |
| Simple base stock (no forecast) | 96.8% / 207 / 11,983 | 83.5% / 1,734 / 54,427 |
| Perfect-foresight reference | 92.0% / 731 / 19,421 | same |

Without a budget limit (per-product paired bootstrap): TCN − naive +1.42 [−1.64, +4.82] (no clear difference);
LightGBM − naive +13.69 [+4.67, +25.08] (**more expensive despite lower MAE**); naive − base stock +1.94 [−1.26, +5.48].
**Business implication:** on this evidence the trained forecasters do not lower simulated cost through the product's
ordering logic; a simple rule is as good. Under a binding budget the planner's rationing (units, not margin) dominates
the outcome (PLAN-P5-01). No business benefit is claimed; a pilot with real operational data is required (EXT-03).

## 3. Mission C — supplier-document retrieval
| ID | Sev. | Finding | Evidence | Status |
|---|---|---|---|---|
| P2-KNOW-01 | P2 | Abstention only for missing digit-bearing identifiers; otherwise the nearest passage was always the answer | Code | Partially fixed: answer-support rule (term coverage / similarity floor with all terms seen) + ambiguity flag; thresholds fitted on R3's development half |
| KNOW-P5-01 | P2 | An unscoped question two suppliers answer differently (e.g. "minimum order quantity DEMO-REF-SKU") was answered with one supplier's clause | Code + R3 | Fixed: flagged ambiguous with the candidate suppliers; scoped search answers |
| KNOW-P5-02 | P2 | Retrieval-only signals cannot separate out-of-scope from reworded in-scope questions (development half: out-of-scope similarity median 0.65 > reworded 0.58); the rule declines 10/26 out-of-scope test questions but no longer answers 51/172 reworded ones (listed as related passages) | Offline evaluation (R3) | Open: needs an evaluated reader model and human-reviewed questions (EXT-06) |
| KNOW-P5-03 | P2 | With lexical search only (hosted demo), questions naming a supplier are flagged ambiguous (0/4 on test) | Offline evaluation (R3) | Open: found on the test half, so not tuned away; needs a new frozen task set |
| — | — | Historical applicability, contradictory terms, cross-tenant isolation | Existing R2 (100% top-1 with both mechanisms), conflict tests, security matrix and Phase 2 leak scan; re-run in this phase's pytest | Unchanged, still passing |

R3 test half (labels by construction, **not human-reviewed**): answerable 45/45 kept; ambiguous 0/4 → 3/4 (hybrid),
4/4 (lexical); out of scope 0/26 → 10/26; unknown products 5/5; reworded 172/172 → 121/172; named supplier 4/4 → 3/4
(hybrid), 0/4 (lexical). Expert-labelled CUAD (C1) and ACORD (R1) ranking results are unaffected: ranking did not change.

## 4. Mission D — MLOps and safeguards
- **Promotion gate** (`forecasting/governance.py`, enforced by `POST /models/{id}/status`): validation pinball must beat
  the same experiment's seasonal-naive baseline; recorded 80% coverage 0.65–0.95; raw crossing ≤ 20%; no smoke run;
  every artifact present with its registered hash. Never reads test results.
- **Fallback policy:** missing/untrusted/failing artifact → baseline (flag + high alert); too-young product → baseline per
  product; origin before training cutoff → baseline (existing).
- **Monitoring / shadow testing / drift** (`forecasting/monitor.py`, `GET /api/v1/models/monitoring`): realised MAE and
  coverage per model from stored forecasts, seasonal naive recomputed on the same products, origins and days (shadow),
  bias (median ÷ volume), PSI demand drift against the champion's training year; recommendations only (≥200 points).
- **Rollback:** the audited promotion path (runbook "Model retraining and promotion").
- **Lineage and reproducibility:** every study writes config (with SHA-256 of the frozen config and the commit), metrics
  and the dataset hash; F2 reproduces F1's recorded test MAE exactly before applying its rules; F1 2.1.0 reproduces 2.0.0's
  LightGBM files byte for byte. Superseded runs are listed with reasons in `evaluations/study_registry.json`.
- **Not done (justified):** automatic retraining or automatic rollback (financial decisions stay human-approved);
  alerting on drift (needs an alert kind and a migration; the report is the first step).

## 5. Also fixed
P3-PLAN-06 (part): a size error in the infeasibility explainer is contained; a solver timeout no longer triggers up to five
extra time-limited solves. Remaining P3-PLAN-06 items (weekly budget vs 21-day plan, docstrings) open.
New: PLAN-P5-01 (P2) — when the budget binds, coverage-first rationing maximises units covered without regard to margin
(S2). Owner decision needed on the rationing objective.
FE-P5-01 / QA-P5-01 (found while reviewing the Research page): on a phone, cards holding tables and the Forecast lab
columns were wider than the screen (grid items grew to their tables), and the overflow tests could not catch it because a
phone browser widens `innerWidth` to fit the content. Fixed with `min-w-0`; the tests now compare with the configured
viewport width.

**Research page.** S1 replaced by S2 (chart: simulated cost per policy with and without the workspace budget) and a new
R3 table (before / hybrid / lexical-only per question type). Headlines come from `evaluations/study_registry.json`.

## 6. Tests executed
See EVIDENCE P5-E01…E15 for commands and results. New: `tests/test_phase5_ml.py` (26 tests). Changed: `tests/test_api.py`,
`tests/test_contract_responses.py` (ambiguity behaviour), `tests/test_forecast_service.py` (`artifact_missing`),
`apps/web/e2e/layout.spec.ts` and `a11y.spec.ts` (overflow against the configured viewport).

| Suite | Result |
|---|---|
| Backend (`uv run pytest -q`) | **447 passed, 6 skipped** (Keycloak) |
| Web lint / unit / types / build | clean / 19 passed / ok / ok |
| Browser, four local projects | **191 passed, 7 skipped** (rerun after the layout fix) |
| Screenshot regression (macOS) | 42 passed after reviewing and accepting the four Research baselines |
| CI | see EVIDENCE P5-E15 |

## 7. Research that needs external data or human judgement
- An untouched forecasting holdout (new UCI-era data do not exist; another licensed retail dataset or a pilot's history).
- Real decision outcomes (pilot with real stock, orders, costs: EXT-03); S2 is simulation only.
- Human-reviewed retrieval questions and answers (R2 sheet, a new R3 sheet: EXT-06); a reader model to judge answer
  support, evaluated on those labels.
- Real supplier terms and lead-time variability (ERP sandbox / pilot: EXT-02).
