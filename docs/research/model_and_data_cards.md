# Model and data cards

## Data card — UCI Online Retail II (admitted)

| Field | Value |
|---|---|
| Source | UCI Machine Learning Repository, dataset 502, DOI 10.24432/C5CG6D |
| Licence | CC BY 4.0 (attribution required) |
| File | `data/raw/core/online_retail_ii/online_retail_ii.zip`, SHA-256 `572e3627…7bfb`, 45,622,418 bytes |
| Coverage | 2009-12-01 to 2011-12-09 (last day partial); one UK online retailer |
| Rows | 1,067,371 = 1,003,214 accepted + 21,335 returns + 42,822 quarantined |
| Quarantine | 21,988 cross-sheet overlap (1–9 Dec 2010 in both sheets), 12,051 exact duplicates, 6,093 non-merchandise codes, 2,690 zero-price lines |
| Target | Daily fulfilled positive units per StockCode (unit-sales, not unconstrained demand) |
| Not available | Stock, purchase cost, suppliers, lead times, stockouts, warehouse layout (all simulated and labelled where used) |
| Caveats | Country = customer residence, not a warehouse. Returns are kept separate. Saturdays are near-closed. |

## Other admitted sources

| Source | Licence | Use | Rows |
|---|---|---|---|
| ACORD (Atticus) | CC BY 4.0 | Retrieval benchmark R1 | 3,931 clauses, 114 queries |
| CUAD v1 (Atticus) | CC BY 4.0 | 73 supply/distribution contracts + 2,176 expert labels; study C1 | 73 documents |
| World Bank IPF awards | CC BY 4.0 | Supplier market module | 295,058 awards, FY2020–FY2027 |
| InventoryBench @62b1f11 | MIT code; H&M-derived data, terms unreviewed | Policy benchmark IB | 1,320 instances |
| Execution-pack fixtures | Fictional | Demo workspace, tests | — |

## Model card — quantile TCN (`tcn_quantile` 1.0.0, champion by validation)

- **Task:** 28-day daily unit-sales quantiles (0.1/0.5/0.9) per product, UCI Online Retail II.
- **Architecture:** 1×1 input projection to 32 channels, 5 causal dilated residual blocks (dilations 1–16, kernel 3,
  GELU, dropout 0.1, receptive field 125 days ≥ 56-day window), direct 28×3 head with origin weekday; 39,380 parameters.
- **Inputs:** last 56 days scaled by their mean (floor 0.1), log scale, weekday one-hots. No future covariates.
- **Training:** pinball loss, AdamW lr 2e-3, cosine schedule, 12 epochs, batch 512, origins every 2 days with labels ≤ cutoff
  (2011-11-10), MPS. Seeds 0/1/2; seed 0 served.
- **Evaluation:** see `docs/research/results.md` F1. Statistically tied with LightGBM; under-forecasts aggregate volume
  on heavy-tailed series (S1).
- **Serving:** separate process (OpenMP conflict with LightGBM), artifact SHA-256 verified before load; refuses origins
  before 2011-11-10 to prevent replay leakage.
- **Not for:** other retailers without re-evaluation; unconstrained demand; lead-time aggregate quantiles.

## Model card — LightGBM quantile (`lightgbm_quantile` 1.0.0, evaluated)

Three global boosters (α = 0.1/0.5/0.9), 31 leaves, 400 rounds, feature fraction 0.8, bagging 0.8, L2 1.0. Features:
horizon, target weekday/month/day, days to Christmas, log scale, product age, lags 1–7, rolling means 7/14/28/56,
std/zero share/max over 28 days, days since last sale, same-weekday means, 14-day trend, all computed from data up to
the origin and scaled. Training rows: 1,066,968 at the last validation origin. Same serving guards as the TCN.

## Model card — seasonal naive (`seasonal_naive` 1.0.0, baseline)

Point = same weekday in the last observed week; interval = empirical 10/90% of k-week-lag errors from the training
history only. No training artifact.
