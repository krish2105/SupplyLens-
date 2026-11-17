# GridLens implementation roadmap

**Spec:** `docs/superpowers/specs/2026-11-17-gridlens-design.md` · **Branch:** `gridlens` · **Deadline:** presentation
9 February 2027, 09:30 (40 minutes + peer Q&A); Blackboard submission by 23:59 the same day.

Five plans, each leaving the repository working and tested. All five are written in full; execute them in order.
Nothing has been executed yet (owner's instruction on 2026-11-17: save the plans only).

| # | Plan | Milestone | Owner area (CONTRIBUTIONS.md) | File |
|---|---|---|---|---|
| 1 | Pivot foundation: rename to GridLens, remove supply-chain-only features, documents and team record | M0 · 2026-11-24 | everyone (pairing) | `2026-11-17-gridlens-01-pivot-foundation.md` |
| 2 | Energy core: tariffs and sites, UCI steel + Open-Meteo + pvlib, tenants, safety-layer dispatch, disruptions, frequency/UFLS, `MicrogridEnv`, baselines, GF1 | M1 · 2026-12-08 | 1 data and forecasting, 2 simulator | `2026-11-17-gridlens-02-energy-core.md` |
| 3 | Controllers: demand-response events, power factor / VAR support, battery ageing, shared LP, stochastic MPC, oracle, unit commitment, cached forecasts, PPO/SAC with NumPy serving and warm start, decision explanations | M2 · 2026-12-22 | 3 deep RL, 4 MPC and UC | `2026-11-17-gridlens-03-controllers.md` |
| 4 | Platform and dashboard: migration 0012, supply-chain core removed, energy service layer (replays with stress-test forks, what-if sizing, tenant bills, daily report, energy alerts), energy API, approval-bound dispatch requests with signed plant commands, EMS screens, 3D park, browser journeys, hosted + offline demo | M4 · 2027-01-26 | 6 dashboard and API | `2026-11-17-gridlens-04-platform-and-dashboard.md` |
| 5 | Studies, ethics and course pack: statistics, MB1/MB2, GF1 extension (TCN, LSTM, conformal), FS1 shed policies, CY1 spoofing + guard + STRIDE, UC1, DR1, EJ1, report, deck, demo script, stress-test runbook, GenAI disclosure | M3/M5 · 2027-01-12 to 2027-02-06 | 5 benchmarking, 7 ethics and report | `2026-11-17-gridlens-05-studies-ethics-course.md` |

## Features beyond the minimum brief (added 2026-11-17 at the owner's request)

| Feature | Why it belongs | Plan |
|---|---|---|
| Demand-response programme events (committed reduction vs customer baseline, credit and penalty) | "Demand Response" is in the project title | 3, 5 (DR1) |
| Power factor and battery VAR support from observed reactive power | the scenario names "power quality instability"; the steel data includes reactive energy | 3 |
| Battery ageing (rainflow) KPI | dispatch that wears out the battery is not a saving | 3 |
| Plain-language explanation of every 15-minute decision | "algorithmic transparency" (slide 22) | 3, 4 |
| Stress-test forks: a peer presses Blackout at any step and the day re-runs from there | "live demo & stress-test defense" (slide 19) | 4 |
| What-if asset sizing (battery hours, PV ratio) | decision support for the implementation roadmap | 4 |
| Tenant bill allocation with shed compensation and DR credit | fairness of "which factory tenants lose power first" | 4, 5 (FS1) |
| Approval-bound non-emergency shedding with signed plant commands | human oversight and cybersecurity | 4 |
| Daily EMS report and energy alerts | operations use, not just a demo | 4 |
| Sensor-spoofing attacks with a plausibility guard and a STRIDE threat model | "cybersecurity risks" (slide 22) | 5 (CY1) |
| Diesel running-hour cap with NOx/PM accounting | "environmental justice regarding backup diesel generator emissions" (slide 22) | 5 (EJ1) |
| Conformal calibration of forecast intervals | research depth: stochastic MPC relies on calibrated quantiles | 5 |

## Before executing

- macOS hides the venv's editable-install `.pth` file and Python 3.12.14 then cannot import the project: run
  `chflags nohidden .venv/lib/python3.12/site-packages/*.pth` after every `uv sync` (Plan 1, Task 1).
- Plan 2 Task 11 downloads public data (UCI, Open-Meteo): ask the owner first.
- Plan 3 Task 9 and Plan 5 Task 2 are long-running (RL training, benchmark): run them in the background.
- Four team member names are still missing from `CONTRIBUTIONS.md`.
