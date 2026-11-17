# GridLens implementation roadmap

**Spec:** `docs/superpowers/specs/2026-11-17-gridlens-design.md` · **Branch:** `gridlens` · **Deadline:** presentation
9 February 2027, 09:30; Blackboard submission by 23:59.

The spec covers five subsystems, so it is built as five plans. Each plan leaves the repository working and tested.
Plans 1 and 2 are written in full. Plans 3–5 build on the interfaces Plan 2 creates (`MicrogridEnv`, `Observation`,
`Action`, `Controller`, `run_episode`, `summarise`, `Forecaster`), so each one is written in full, with the same
format, when the plan before it is merged. Writing them earlier would mean guessing at code that does not exist yet.

| # | Plan | Milestone | Owner area (CONTRIBUTIONS.md) | File |
|---|---|---|---|---|
| 1 | Pivot foundation: rename, remove supply-chain-only features, GridLens documents | M0 · 2026-11-24 | everyone (pairing) | `2026-11-17-gridlens-01-pivot-foundation.md` |
| 2 | Energy core: data, forecasting (GF1), simulator, disruptions, frequency, baselines | M1 · 2026-12-08 | 1 data and forecasting, 2 simulator | `2026-11-17-gridlens-02-energy-core.md` |
| 3 | Optimisation and learning controllers | M2 · 2026-12-22 | 3 deep RL, 4 MPC and unit commitment | to be written after Plan 2 |
| 4 | Domain swap: database, API, worker and EMS dashboard | M4 · 2027-01-26 | 6 dashboard and API | to be written after Plan 3 |
| 5 | Studies, ethics and course deliverables | M3/M5 · 2027-01-12 to 2027-02-06 | 5 benchmarking, 7 ethics and report | to be written after Plan 3 (studies) and Plan 4 (screens) |

## Plan 3 — Optimisation and learning controllers (spec §6.1–§6.3)

Scope and tasks, in order:
1. **Day-ahead unit commitment** (`optimisation/gridlens_opt/unit_commitment.py`): OR-Tools MILP over 96 steps with
   on/off and start-up binaries, minimum up/down, minimum load, start-up and fuel cost, islanding reserve; input median
   net demand plus an upper-quantile margin; output a `(96, n_units)` bool array that `MicrogridEnv.reset(options=
   {"commitment": ...})` already accepts. Tests: constraints hold on random inputs; reserve met; solve time limit.
2. **Perfect-foresight oracle** (`optimisation/gridlens_opt/oracle.py`): the same MILP structure with battery,
   grid, deferral and shed variables on the realised day; implemented as a `Controller` that replays its plan.
   Test: its `operating_cost` ≤ every baseline on synthetic days.
3. **Stochastic MPC** (`control/gridlens_control/mpc.py`): scenario MILP (10 scenarios sampled from the forecast
   quantiles, non-anticipative first step, 24 h horizon, re-solved each step, time limit with best feasible solution
   logged). Implements `Controller`. Tests: feasible on disrupted synthetic days; beats `rule_tou` on a synthetic
   weekday; deterministic with a fixed seed.
4. **RL training** (`control/gridlens_control/rl.py`, `scripts/train_rl.py`): stable-baselines3 PPO and SAC on
   `MicrogridEnv` with a scenario sampler that mixes normal and disrupted days (Jan–Sep), validation on October,
   5 seeds each, reward exactly the env reward. Adds `stable-baselines3` (PyTorch runs in its own process, as the
   repository already does for the TCN, because of the LightGBM/PyTorch OpenMP clash).
5. **Policy export and serving** (`control/gridlens_control/policy.py`): export the actor MLP to `.npz`, hash-verify
   on load, NumPy forward pass implementing `Controller` (no PyTorch in the API). Test: NumPy output equals the
   PyTorch policy's deterministic action to 1e-5.
6. **Rule-based warm start** (spec §14 risk): optional behaviour-cloning of `rule_tou` before RL training; kept only
   if validation cost improves, and the attempt is reported either way.

Done when: UC, MPC, oracle, PPO and SAC all run through `run_episode` on real data; `scripts/run_baselines.py`
gains the new controllers.

## Plan 4 — Domain swap: database, API, worker and EMS dashboard (spec §8, §11)

Scope and tasks, in order:
1. **New baseline migration**: platform tables (tenants/workspaces as industrial parks, users, memberships, sessions,
   approvals, audit, jobs, outbox, idempotency, rate limits, alerts, settings, exports, deletions, vitals, documents,
   chunks, vectors, model versions) plus energy tables (sites, assets, park tenants, replays, replay steps, dispatch
   actions, shed log, studies). Old migrations 0001–0011 removed; forced row-level security kept on every tenant table.
2. **Remove the remaining supply-chain core**: products, sales, suppliers, terms, inventory, purchase orders, planning,
   UCI retail ingest, onboarding CSV templates, sandbox ERP schema, the procurement investigator (`agent/graph.py`,
   `agent_runs`), and their tests and screens.
3. **Repurpose actions and outbox**: dispatch overrides and non-emergency load-shed requests become approval-bound
   actions; the outbox sends signed commands to a sandbox plant adapter (replacing the sandbox ERP), with the same
   unknown-outcome reconciliation.
4. **API** (spec §8.1): sites, forecasts, commitment, replays with SSE stream and event injection, benchmarks, tenants
   and shed log, dispatch-action approvals, EMS assistant citing replay records; contract regenerated and drift-checked.
5. **Worker jobs**: replay ticks, benchmark runs, forecast refresh.
6. **Screens** (spec §8.2): Overview with SoC, power flows, price band, grid status, frequency and dispatch feed;
   Forecast lab; Dispatch comparison; Stress test panel; Unit commitment Gantt; Tenants and fairness; Savings and
   carbon; Benchmarks; Approvals; Policies (tariffs, shed policy, grid code); 3D park from the existing 3D warehouse;
   Korea / UAE site switcher; observed/simulated/assumed labels on every number. Playwright journeys, axe checks and
   both themes kept.
7. **Hosting**: hosted demo serves NumPy policies and cached studies; `docker compose up` local fallback with cached
   data and trained policies; keep-warm URL updated after the owner renames the Vercel project.

Done when: a peer can open the hosted demo, start a replay, press "Blackout" and watch islanding, the frequency trace,
UFLS stages and the shed log with reasons; the same works offline with Docker.

## Plan 5 — Studies, ethics and course deliverables (spec §7, §9, §12)

Scope and tasks, in order:
1. **MB1/MB2 benchmark**: every controller × normal and disrupted regimes × 5 scenario seeds (RL also × 5 training
   seeds) on 2018-11-01..12-31; paired bootstrap 95 % confidence intervals over days; regret against the oracle;
   registered results; UAE what-if as MB2.
2. **GF1 extension**: add the quantile TCN and LSTM (code kept from SupplyLens) to the forecasting comparison.
3. **UC1**: unit commitment vs "run one unit when forecast net demand exceeds the grid limit".
4. **FS1 fairness**: strict priority vs rotating priority (current) vs proportional shedding; shed-burden Gini and
   critical-load served; reuses the FA1/B1 code.
5. **CY1 cybersecurity**: STRIDE threat model; spoofed irradiance and meter injection events (adds `spoof_pv` and
   `spoof_load` event kinds that alter only what controllers observe); plausibility checks with fallback to the
   seasonal-naive forecast; cost, unserved energy and detection rate with and without checks; reuses RED1 structure.
6. **Environmental justice**: diesel running-hour cap and NOx/PM accounting in every controller's objective; Impact
   screen and report section.
7. **Course pack**: final report (literature review on DRL vs MPC for microgrids, unit commitment, UFLS; methods;
   results; limitations; implementation roadmap pilot → shadow mode → supervised control), 40-minute deck, demo script,
   stress-test runbook, GenAI prompt log with encircled AI content, AI-use statement, seven-member contribution record,
   two full rehearsals.

Done when: every number in the deck and report comes from `docs/course/metrics.md`; the GenAI log and contribution
record are complete; two rehearsals are done, including the offline fallback.
