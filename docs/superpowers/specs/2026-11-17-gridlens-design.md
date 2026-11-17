# GridLens — design specification

**Date:** 2026-11-17 · **Status:** approved design, awaiting spec review · **Branch:** `gridlens`
**Brief:** Group 2, *Intelligent Microgrid Energy Dispatch & Demand Response for Smart Industrial Parks*
(Dr Sandip Kumar Roy, Session III final group project, slides 19, 20 and 22, 2026-11-17)
**Predecessor:** SupplyLens, preserved at git tag `archive/supplylens` (commit `1015b18`)

## 1. Goal

Repurpose the SupplyLens codebase into **GridLens**, an AI energy management system (EMS) for a semi-autonomous
industrial-park microgrid (rooftop PV, battery storage, backup diesel generators, grid connection). GridLens forecasts
supply and demand every 15 minutes, dispatches the battery, the grid and shiftable machine loads with deep
reinforcement learning and stochastic model predictive control, commits the diesel units with an operations-research
model, survives simulated disruptions in islanded mode, and shows it all on a live EMS dashboard. It must beat at least
two classical baselines, in both normal and disrupted conditions, and hold up to a live stress test.

Platform work from SupplyLens is kept: auth, multi-tenancy, approvals, audit trail, job worker, outbox, telemetry,
CI, Docker, hosting and the test harness. Supply-chain features with no energy counterpart are deleted (§11).

### Non-goals
- No real SCADA, PLC or inverter is connected. Dispatch commands go to a simulated plant adapter.
- No AC power flow or protection study. Frequency is a single-bus aggregate model (§5.3).
- No claim of real-world savings. Every result is labelled with how it was produced (observed, simulated or assumed).

## 2. Requirement traceability

| Source | Requirement | Where met |
|---|---|---|
| Slide 22 · Predictive Model | Multi-horizon forecast of net demand and renewable generation at 15-min intervals using irradiance, weather, smart-meter load, production schedules | §4 |
| Slide 22 · AI Optimization | DRL (PPO or SAC) or stochastic MPC for battery charge/discharge, grid import/export, shiftable loads under time-of-use pricing | §6.2, §6.3 (both PPO and SAC, and stochastic MPC) |
| Slide 22 · Disruption Simulation | Grid blackouts, sudden cloud-cover drops, heavy machinery start-ups; islanded resilience; frequency and load-shedding stability | §5.3, §5.4 |
| Slide 22 · System Dashboard | Real-time SoC, carbon footprint reduction, peak-shaving savings, automated load-dispatch actions | §8 |
| Slide 22 · Ethical Considerations | Cybersecurity risks; algorithmic transparency in load-shedding (which tenants lose power first); environmental justice of diesel emissions | §9 |
| Slide 22 · Topics | Time-series forecasting; sequential decision-making and DRL; operations research and unit commitment | §4; §6.2; §6.1, §6.3 |
| Slide 19 · Common | End-to-end pipeline: data ingestion → ML inference → optimization solver → simulation environment → REST API / UI | §3 |
| Slide 19 · Common | Baseline benchmarking against at least two classical baselines across normal and disrupted regimes | §6.4, §7 |
| Slide 19 · Common | Live demo and stress-test defence | §8.2, §12 |
| Slide 19 · Scope | Real-world challenge, AI solution, prototype, findings and implementation roadmap | whole spec; §12 |
| Slide 20 · Rubric | Research depth, innovation, application of techniques, presentation and reporting (30 marks) | §13 |
| Slide 20 · GenAI | Encircle GenAI-generated content and share prompts separately | §12.3 |

Slide 22 carries the footer "Reasoning and Decision Making under Uncertainty" while slides 19 and 20 carry "AI in
Operations". The submission is prepared for the MAIB unit *AI in Operations* (MAIB AI 218), as before; confirming the
unit with Dr Roy is listed in §15.

## 3. Architecture

```
 ingestion                 ML inference              optimisation                simulation              API / UI
┌────────────────┐   ┌───────────────────────┐   ┌──────────────────────┐   ┌──────────────────┐   ┌──────────────┐
│ UCI steel load │   │ load, PV, net-demand  │   │ day-ahead unit       │   │ Gymnasium        │   │ FastAPI REST │
│ Open-Meteo     │──▶│ quantile forecasts    │──▶│ commitment (MILP)    │──▶│ MicrogridEnv     │──▶│ + SSE stream │
│ tariffs, CO2   │   │ (15 min, 96 steps)    │   │ controllers: PPO,    │   │ (15-min step,    │   │ Next.js EMS  │
│ tenants (sim.) │   │ LightGBM, TCN, LSTM   │   │ SAC, stoch. MPC,     │   │ disruptions,     │   │ dashboard    │
└────────────────┘   └───────────────────────┘   │ baselines, oracle    │   │ frequency, UFLS) │   └──────────────┘
                                                 └──────────────────────┘   └──────────────────┘
```

Each stage is a separate Python package with a typed interface, so it can be tested and owned by one team member:

| Package (after rename) | Purpose | Main interface |
|---|---|---|
| `ml/gridlens_ml` | data adapters, feature building, forecasting models, metrics | `forecast(site, issue_time) -> QuantileForecast` |
| `optimisation/gridlens_opt` | unit commitment, stochastic MPC, oracle, validator | `commit(day) -> Commitment`, `MPCController.act(obs)` |
| `sim/gridlens_sim` (new) | Gymnasium environment, plant components, disruptions, frequency model | `MicrogridEnv.reset/step`, `Scenario` |
| `control/gridlens_control` (new) | controller protocol, baselines, PPO/SAC wrappers, safety layer, policy export | `Controller.act(obs) -> Action` |
| `services/api/src/gridlens` | REST API, replay sessions, approvals, audit, assistant | OpenAPI document in `packages/contracts` |
| `services/worker/src/gridlens_worker` | jobs: training, benchmark runs, replay ticks, outbox to plant adapter | job queue |
| `apps/web` | EMS dashboard | typed client from `packages/contracts` |
| `evaluations/` | frozen studies, result registry | `artifacts/experiments/<ID>/metrics.json` |

Renames: `supplylens` → `gridlens`, `supplylens_ml` → `gridlens_ml`, `supplylens_opt` → `gridlens_opt`,
`supplylens_worker` → `gridlens_worker`, environment prefix `SUPPLYLENS_` → `GRIDLENS_`, project name in
`pyproject.toml`, `package.json`, Docker, Render, Vercel and CI files.

## 4. Data and forecasting

### 4.1 Sources

| Data | Source | Licence | Label |
|---|---|---|---|
| Industrial load, 15-min kWh, 2018-01-01 to 2018-12-31, 35,040 rows; reactive power, power factor, CO2, load type, week status | UCI Steel Industry Energy Consumption, id 851, doi:10.24432/C52G8C (DAEWOO Steel, Gwangyang, South Korea) | CC BY 4.0 | Observed |
| Weather and irradiance (GHI, DNI, DHI, temperature, cloud cover, wind) for Gwangyang 2018 and for the UAE site | Open-Meteo historical archive (hourly; satellite radiation at native 15-min where the archive covers the period) | CC BY 4.0 | Observed |
| PV output | pvlib model from irradiance and temperature: fixed-tilt rooftop array, inverter efficiency 96 % | — | Simulated from observed weather |
| Korea tariff | KEPCO Industrial (B) high-voltage time-of-use table in force in 2018, copied with its source URL into `config/tariffs/kr_industrial_b_2018.yaml` | public tariff | Observed if copied from KEPCO; otherwise each value marked `assumed: true` |
| UAE tariff | ADDC 2025 industrial: 36.6 fils/kWh peak, 27.0 fils/kWh off-peak; peak 10:00–22:00 from 1 June to 30 September | public tariff | Observed |
| Grid carbon intensity | national average factors per site in `config/carbon.yaml`, each with a source | — | Observed or assumed, per value |
| Diesel fuel curve and emissions (CO2, NOx, PM) | manufacturer-style linear fuel curve and emission factors in `config/diesel.yaml` | — | Assumed |
| Tenants (5) and production schedules | generated: the observed load is split across five tenant factories with fixed shares and priority classes; shift calendars follow the dataset's `WeekStatus` and `Load_Type` | — | Simulated |
| Shiftable machine load | each tenant has a flexible share of its load; the controller may postpone it, and every postponed kWh must be served within 4 h and by the end of the day (an aggregate of machine jobs with deadlines) | — | Simulated |

The load series is used as the aggregate park load. Datasets are not joined across sites: the Korea case uses only
Korean data. The UAE case is a labelled what-if that reuses the Korean load profile on its local wall clock (the UAE weekend has been
Saturday–Sunday since 2022, as in the Korean data, so no shift is needed), with UAE weather and tariff.

### 4.2 Sites

`config/sites/kr_gwangyang.yaml` (primary, 60 Hz) and `config/sites/ae_industrial.yaml` (what-if, 50 Hz). Asset sizes
are ratios of the observed peak load `P_peak` (largest 15-min usage × 4):

| Asset | Size |
|---|---|
| Rooftop PV | 0.8 × `P_peak` kWp |
| Battery (BESS) | power 0.5 × `P_peak` kW, energy 2 h at that power; SoC limits 10–95 %; round-trip efficiency 90 %; degradation cost per kWh throughput in config |
| Diesel generators | 2 units, each 0.3 × `P_peak` kW; minimum load 30 %; minimum up 1 h, minimum down 1 h; start-up cost and fuel curve in config |
| Grid connection | import limit 1.1 × `P_peak`; export limit 0.3 × `P_peak`; export price in tariff config; monthly peak-demand charge |

### 4.3 Forecasting

- Targets: park load, PV output and net demand (load − PV), per 15-min step, horizons 1–96 steps (24 h).
- Features: lagged load (1 step, 1 day, 1 week), calendar, `WeekStatus`, production schedule, weather forecast
  variables (in the backtest, observed weather stands in for the forecast; this is stated as an optimistic assumption),
  clear-sky irradiance from pvlib.
- Models: seasonal naive (same step last week for load, yesterday for PV) as the baseline; LightGBM quantile and
  quantile TCN reused from SupplyLens; LSTM as a comparison.
- Quantiles: 0.1, 0.25, 0.5, 0.75, 0.9.
- Split (chronological, no shuffling): train 2018-01-01 to 2018-09-30, validation October, test 2018-11-01 to
  2018-12-31. The SupplyLens leakage test is adapted so no feature can use data after the issue time.
- Metrics: MAE, WAPE, pinball loss, 80 % interval coverage, by horizon band (1 h, 6 h, 24 h). Study ID `GF1`.

## 5. Simulation environment

### 5.1 `MicrogridEnv` (Gymnasium)
- Step: 15 minutes. Episode: one day (96 steps) for training and benchmarking; longer replays for the dashboard.
- Observation: time features, current load and PV, forecast quantiles for the next 96 steps (load, PV), battery SoC,
  tariff now and next 24 h, grid status (connected/islanded), committed diesel units, pending shiftable jobs, frequency
  deviation, month-to-date peak import.
- Action (continuous, in [−1, 1]²): battery power set-point (fraction of rated power, negative = charge) and
  flexible-load deferral fraction (share of deferrable job energy to postpone this step).
- Diesel commitment comes from the day-ahead unit commitment (§6.1). In islanded mode the safety layer may start an
  idle unit (emergency start).

### 5.2 Energy balance and safety layer
Every step must satisfy
`PV_used + grid_import + battery_discharge + diesel = load_served + battery_charge + grid_export`,
with `load_served = load − deferred − shed`. A deterministic safety layer projects each controller action into the
feasible set (SoC limits, power limits, grid limits, diesel minimum load, job deadlines) before it is applied, and logs
every correction. When supply is short in islanded mode the shed rule (§9.2) decides who loses power.

### 5.3 Frequency model (islanded mode only)
Single-bus aggregate swing equation per 1-second sub-step inside each 15-min step:
`df/dt = f0 / (2 H S) · (P_gen − P_load − D · Δf)`, with inertia `H` from running diesel units, a battery droop
response limited by its rated power, and load damping `D`. Under-frequency load shedding (UFLS) in three stages at
−1.0 %, −1.5 % and −2.0 % of nominal frequency sheds tenants in published priority order (§9.2). Outputs per event:
frequency nadir, rate of change of frequency, time to recover, energy shed per tenant. Parameters live in the site
config; they are representative values and are labelled as assumed.

### 5.4 Disruptions
| Event | Model | Parameters (sampled per seeded scenario) |
|---|---|---|
| Grid blackout | grid unavailable; park islands | start time, duration 15 min – 4 h |
| Cloud-cover drop | PV falls to 30 % of forecast within one step | start, duration 30 min – 3 h |
| Heavy machinery start-up | step load increase (inrush) for one sub-step window, then sustained extra load | size 0.15–0.35 × `P_peak`, duration |
| Combined | blackout with cloud drop and/or start-up | — |
| Forecast-feed attack (for §9.1) | spoofed irradiance or meter values sent to the controller | bias, duration |

Scenarios are generated from a seed and stored as JSON so every benchmark and every live-demo trigger is reproducible.

## 6. Controllers and optimisation

All controllers implement one protocol, `Controller.act(observation) -> Action`, and pass through the same safety layer.

### 6.1 Day-ahead unit commitment (operations research)
MILP over 96 steps using OR-Tools (SCIP backend, already a dependency): binary on/off and start-up variables per diesel
unit, minimum up/down, minimum load, start-up cost, fuel cost, and a reserve requirement sized for an islanding event
(spinning reserve ≥ the largest single tenant's critical load not covered by battery energy). Inputs: median net-demand
forecast plus an upper-quantile reserve margin. Output: commitment schedule shown as a Gantt chart. Study ID `UC1`
compares it with a rule "run one unit whenever forecast net demand exceeds grid limit".

### 6.2 Deep reinforcement learning: PPO and SAC
- Library: stable-baselines3 with Gymnasium; MLP policies (2 × 64).
- Reward per step: −(energy cost + increase in the month's peak-demand charge + diesel fuel cost + battery degradation
  cost + carbon price × CO2 + value-of-lost-load × unserved energy weighted by tenant priority + safety-correction
  penalty).
- Training on January–September days with randomised disruptions; model selection on October; 5 seeds each.
- Serving: the trained policy network is exported to a NumPy forward pass (weights as `.npz`) so the hosted API needs no
  PyTorch. Weights are hash-verified before use, as SupplyLens did for forecast artifacts.

### 6.3 Stochastic MPC
Scenario-based receding-horizon MILP (OR-Tools): horizon 24 h at 15-min resolution, 10 scenarios sampled from the
forecast quantiles, non-anticipative first-step decisions, re-solved every step. Variables: battery charge/discharge,
grid import/export, deferral, shed; diesel commitment fixed by §6.1. Objective matches the RL reward in expectation.
A solve-time limit applies; if it is hit, the best feasible solution is used and the event is logged.

### 6.4 Baselines and bounds
| Name | Rule |
|---|---|
| `rule_tou` (classical baseline 1) | charge from the grid in the cheapest period up to 95 % SoC; discharge in the peak period down to 10 %; no deferral |
| `greedy_self` (classical baseline 2) | charge from PV surplus, discharge to cover any deficit; no grid charging; no deferral |
| `no_battery` | battery idle; reference for savings |
| `oracle` | perfect-foresight MILP on the realised day (upper bound; not a deployable controller) |

## 7. Benchmark protocol (study `MB1`)

- Test days: 2018-11-01 to 2018-12-31 (61 days), Korea site; repeated for the UAE what-if as study `MB2`.
- Regimes: **normal** (no injected events) and **disrupted** (each day gets a seeded scenario drawn from §5.4:
  blackout, cloud drop, start-up, combined). 5 scenario seeds; RL controllers also over their 5 training seeds.
- Metrics per controller and regime: total cost, peak-shaving saving vs `no_battery`, peak import, CO2, diesel hours and
  NOx/PM, unserved energy, critical-load served %, frequency nadir, number of shed events, shed-burden inequality across
  tenants (Gini of energy shed per kWh of demand), battery equivalent full cycles, safety corrections, decision time.
- Statistics: paired bootstrap over days, 95 % confidence intervals. A controller "beats" a baseline only when the
  interval of the difference excludes zero. Regret against `oracle` is reported for every controller.
- Negative results are kept and reported, following the SupplyLens practice.
- Outputs follow the existing registry: `artifacts/experiments/MB1-<timestamp>/metrics.json` and an entry in
  `evaluations/study_registry.json`. Presentation numbers are generated only from these files (`docs/course/metrics.md`).

## 8. API and EMS dashboard

### 8.1 API (FastAPI, contract in `packages/contracts/openapi.json`)
- `GET /sites`, `GET /sites/{id}` — assets, tariff, carbon factors.
- `GET /forecasts?site&issue_time` — quantile forecasts.
- `GET /commitment?site&day` — unit commitment schedule.
- `POST /replays` — start a replay session (site, start day, controller, speed, scenario); `GET /replays/{id}/stream`
  — server-sent events with each step's state, action, safety corrections and dispatch actions.
- `POST /replays/{id}/events` — inject a disruption (stress test).
- `GET /benchmarks`, `GET /benchmarks/{study}` — study results.
- `GET /tenants`, `GET /shed-log` — tenant priorities and every shed decision with its reason.
- `POST /dispatch-actions/{id}/approve|reject` — approvals for non-emergency shedding and manual overrides.
- `POST /assistant` — EMS assistant answers about the replay, citing records.
Existing auth, CSRF, idempotency keys, rate limits, audit and row-level security are kept, with the workspace
representing an industrial park.

### 8.2 Screens (Next.js)
| Screen (route) | Built from | Content |
|---|---|---|
| Overview (`/`) | overview page | live SoC gauge, power-flow diagram, price band, grid status, frequency, latest dispatch actions, KPIs (cost today, peak shaved, CO2 avoided) |
| Forecast lab (`/forecast`) | forecast page | load/PV/net-demand quantile fans, model comparison by horizon |
| Dispatch (`/dispatch`) | runs page | controller picker, side-by-side replay of two controllers, action timeline |
| Stress test (`/stress-test`) | scenarios page | buttons: blackout, cloud drop, machine start-up, combined, forecast spoofing; live frequency trace and UFLS stages |
| Unit commitment (`/commitment`) | new | diesel Gantt, reserve margin, emissions |
| Tenants & fairness (`/tenants`) | inventory page | priority classes, shed log with reasons, burden-equity chart |
| Savings & carbon (`/impact`) | value page + emissions frontier | peak-shaving savings, CO2 and NOx/PM, cost–carbon frontier |
| Benchmarks (`/research`) | research page | MB1/MB2/GF1/UC1/fairness/red-team results with confidence intervals |
| Approvals (`/approvals`) | approvals page | pending shed and override approvals |
| 3D park (overview panel) | `warehouse3d.tsx` | five tenant buildings, PV roofs, battery, diesel yard, animated power flows; colour shows shed state |
| Policies (`/policies`) | policies page | tariff tables, load-shed priority policy, grid-code notes, with citations |
| Settings, Admin | kept | site switcher (Korea / UAE what-if), theme, users |

A visible label on every number states whether it is observed, simulated or assumed.

## 9. Ethics, security and fairness

### 9.1 Cybersecurity
- Threat model (STRIDE) for the EMS: forecast-feed spoofing, meter false-data injection, command tampering between API
  and plant adapter, denial of service, insider override.
- Controls kept from SupplyLens: approvals bound to payload hash and expiry, separation of duties, append-only audit,
  signed webhooks, rate limits, row-level security.
- New: plausibility checks on incoming forecasts and meter values (physical bounds, clear-sky limit for PV, rate-of-change
  limits) that fall back to the seasonal-naive forecast; command signing to the plant adapter.
- Study `CY1`: red-team scenarios from §5.4 (spoofed irradiance, spoofed meter) with and without the checks; metrics:
  cost increase, unserved energy, detection rate.

### 9.2 Transparent load-shedding
- Published priority policy: tenants are ranked by class (critical, essential, flexible). Within a class the shed order
  rotates so the same tenant is not always first. The policy text is shown on the Policies screen and versioned.
- Every shed decision records time, trigger (UFLS stage, supply shortfall, approved demand response), tenant, kW, and
  the rule that selected it. Tenants can see their own log.
- Non-emergency demand response needs human approval; emergency UFLS acts automatically and is reviewed afterwards.
- Study `FS1`: shed-burden equity under strict priority vs priority with rotation vs proportional shedding; reuses the
  SupplyLens fair-allocation code (FA1) and reports the trade-off between equity and critical-load served.

### 9.3 Environmental justice
- Diesel CO2, NOx and PM are counted per hour; a configurable cap on diesel running hours and a carbon price enter every
  controller's objective.
- The Impact screen shows local-pollutant hours alongside cost, and the report discusses who lives and works near the
  generator yard.

## 10. Testing

- Unit: energy-balance invariant at every step (absolute error < 1e-6 kWh), SoC and power limits, diesel minimum
  load and up/down times, deferred jobs meet deadlines, UFLS sheds in policy order, frequency recovers after shedding.
- Controllers: every controller's actions are feasible after the safety layer on all test scenarios; MPC and UC solve
  within their time limits on the test days; oracle cost ≤ every controller's cost on the same day.
- ML: no-leakage test on forecast features; forecast artifacts hash-verified.
- Reproducibility: the same seed gives identical benchmark metrics.
- API: contract drift check (existing script), auth and approval tests kept.
- Browser (Playwright): overview loads with live replay; trigger a blackout and see islanding, frequency trace and
  shed log; approve a non-emergency shed; compare two controllers; switch Korea/UAE site; theme and accessibility
  checks kept.
- Existing SupplyLens tests for deleted features are deleted with the features.

## 11. Keep, repurpose, delete

| Area | Decision |
|---|---|
| Auth, sessions, OIDC, CSRF, rate limits, admission, idempotency, RLS, audit, telemetry, metrics, backup/PITR drills | keep (rename) |
| Job worker and outbox | keep; outbox now sends dispatch commands to a sandbox plant adapter |
| `integrations/sandbox_erp.py`, connector, sync | repurpose as sandbox plant adapter; delete ERP-specific parts |
| `actions/service.py` (approvals for purchase orders) | repurpose for dispatch overrides and non-emergency shedding |
| `forecasting/` service, `ml/` LightGBM, TCN, metrics | keep, retarget to load/PV |
| `optimisation/planner.py`, `validator.py`, `emissions.py` | repurpose: CP-SAT/MILP patterns into UC and MPC; emissions into carbon accounting |
| Fair allocation (FA1) and bias study code (B1) | repurpose for FS1 |
| Red-team study (RED1) | repurpose for CY1 |
| `assistant/` | repurpose as EMS assistant citing replay records |
| `knowledge/` retrieval | keep, reduced to the tariff, policy and grid-code library |
| `warehouse3d.tsx`, `floorplan.tsx`, `emissions-frontier.tsx`, charts, command palette, onboarding | repurpose |
| `ingest/acord.py`, `cuad.py`, `world_bank.py`, `uci.py` (retail) | delete |
| `planning/` (positions, terms, replenishment, scenario), `optimisation/replenishment.py`, `leadtime_demand.py`, `terms.py`, `demand_sim.py` | delete |
| `agent/graph.py` (procurement investigator), n8n workflow, HubSpot hand-off | delete |
| Market screen, inventory classes, extracted terms | delete |
| Studies (the LSTM model code from W2 is first moved into `ml/gridlens_ml`): F1/F2, S2, IB, R1–R3, C1, X1, AS1, G1, D1, ET1, RT1, FE1, QC1, PM1, JS1, W1, W2, E1, LT, inventorybench and their tests, configs and artifacts | delete (kept in `archive/supplylens`) |
| `data/synthetic/operations`, `fixtures/reference_case`, `fixtures/policy_change_case.json` | delete; new fixtures for the energy demo |
| Alembic migrations 0001–0011 | replaced by a new baseline migration with platform tables plus energy tables (sites, assets, tenants, replays, dispatch actions, shed log, studies) |
| `execution_pack/`, SupplyLens course docs and decks, `DECISIONS.md`, `EVIDENCE_INDEX.md`, `PROJECT_STATUS.md`, `TASKS.md`, `NEXT_SESSION.md` | rewrite for GridLens; old content stays in the tag |

## 12. Deliverables and delivery

### 12.1 Presentation day (9 Feb 2027)
- 09:30 classroom presentation, 40 minutes per group, then peer Q&A (10 marks for participation).
- Live demo: hosted GridLens; a peer picks a disruption on the Stress test screen and the team explains the response.
- Fallback: `docker compose up` on the presenting laptop with pre-trained policies and cached data, rehearsed offline.
- Blackboard submission by 23:59: report, deck, repository link, GenAI prompt log, contribution record.

### 12.2 Documents
- `docs/course/final-deck.md` and exported slides: problem, data, forecasting, UC, PPO/SAC/MPC, benchmark results with
  confidence intervals, live demo, ethics, implementation roadmap (pilot → shadow mode → supervised control).
- Final report with research depth (literature on DRL vs MPC for microgrids, unit commitment, UFLS), methods, results,
  limitations, roadmap.
- `docs/course/demo-script.md` and `docs/course/stress-test-runbook.md` (likely peer challenges and the screen that
  answers each).

### 12.3 GenAI disclosure
- `docs/course/genai-prompts.md` logs every prompt used to generate content (code, text, figures) with date and tool.
- In the deck and report, GenAI-generated content is encircled (a visible outline style) as Dr Roy requires;
  `docs/course/ai-use-statement.md` is rewritten for GridLens.

### 12.4 Team (7 members)
`CONTRIBUTIONS.md` lists all seven members (names to be supplied by the owner) and this ownership split, editable by
the team:

| # | Area | Packages / documents |
|---|---|---|
| 1 | Data and forecasting | `ml/`, ingestion, GF1 |
| 2 | Simulator and disruptions | `sim/`, frequency and UFLS |
| 3 | Deep RL (PPO, SAC) | `control/` RL, training jobs |
| 4 | Stochastic MPC and unit commitment | `optimisation/`, UC1 |
| 5 | Benchmarking and statistics | `evaluations/`, MB1, MB2 |
| 6 | EMS dashboard and API | `apps/web`, `services/api` |
| 7 | Ethics, cybersecurity, report | FS1, CY1, report, GenAI log |

### 12.5 Milestones
| By | Milestone |
|---|---|
| 2026-11-24 | M0: rename, deletions, new baseline migration, CI green |
| 2026-12-08 | M1: data ingestion, forecasting (GF1), simulator with baselines and disruptions |
| 2026-12-22 | M2: unit commitment, stochastic MPC, oracle; first PPO and SAC training |
| 2027-01-12 | M3: benchmark studies MB1/MB2, FS1, CY1 |
| 2027-01-26 | M4: dashboard complete, hosted deploy renamed, local fallback |
| 2027-02-06 | M5: report, deck, GenAI log, contribution record, two full rehearsals |
| 2027-02-09 | Presentation 09:30; Blackboard submission by 23:59 |

## 13. Rubric mapping (slide 20, 30 marks)

| Criterion | Evidence |
|---|---|
| Research depth | literature review; real 15-min industrial data; three forecasting models with intervals; MB1/MB2 with confidence intervals and oracle regret; negative results kept |
| Innovation | PPO, SAC and stochastic MPC under one protocol; safety layer shared by all controllers; fairness-aware rotating UFLS; cyber false-data study; live peer-triggered stress test |
| Application of techniques | time-series forecasting, DRL, MILP unit commitment, scenario MPC, frequency simulation, fairness metrics |
| Presentation and reporting | live EMS dashboard, generated metrics only, demo script, runbook, GenAI disclosure |

## 14. Risks

| Risk | Mitigation |
|---|---|
| RL does not beat MPC or the baselines | report honestly; reward shaping and rule-based warm start (demonstrations) as a documented attempt; MPC remains the deployable controller |
| MPC solve time too long for live replay | time limit with best feasible solution; smaller scenario count in the live demo, full count in the study |
| Hosted runtime too small for training | training runs offline; hosted API only serves NumPy policies and cached studies |
| Exact KEPCO 2018 band rates cannot be verified | values marked assumed in config and on screen |
| Venue network fails | rehearsed local Docker fallback |
| Hosting rename needs the owner's Vercel/Neon accounts | owner renames the projects; code reads names from configuration |

## 15. Open items for the owner
- The seven member names for `CONTRIBUTIONS.md`.
- Confirm with Dr Roy which unit the submission counts for (slide 22 footer differs from slides 19 and 20) and what
  contribution evidence is expected.
- Rename the Vercel and Neon projects (account access is the owner's).
