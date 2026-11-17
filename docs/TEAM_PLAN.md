# GridLens — Group 2 team plan (7 members)

Project: *Intelligent Microgrid Energy Dispatch & Demand Response for Smart Industrial Parks* (Dr Sandip Kumar Roy,
final group project). Presentation **9 February 2027, 09:30** (40 minutes + peer Q&A); Blackboard submission by
**23:59** the same day. Plans: [`docs/superpowers/plans/`](superpowers/plans/) · Design:
[`docs/superpowers/specs/2026-11-17-gridlens-design.md`](superpowers/specs/2026-11-17-gridlens-design.md).

This split is a proposal by Krishna; each member confirms (or swaps) their row at the first meeting, and the agreed
version is copied into `CONTRIBUTIONS.md` with the date. Members 4–7: replace "Member N" with your name in a pull request.

## Who does what

| # | Member | Role | Plan tasks owned | Report sections | Deck (≈5 min each) |
|---|---|---|---|---|---|
| 1 | **Krishna Mathur** | Project lead · platform and integration | Plan 1 (all 7 tasks); Plan 4 Tasks 1–6 (migration, supply-chain removal, energy service layer, what-if/bills/report/alerts, energy API, approvals and signed plant commands) and Task 11 (hosting, precomputed replays, offline Docker); reviews and merges every pull request | 1 Executive summary, 10 The product, 12 Roadmap (co) | Title, problem framing, architecture; drives the live demo |
| 2 | **Atharva Soundankar** | Data and forecasting | Plan 2 Tasks 1–3 (tariffs/sites, steel reader, weather + PV), 11 (data download + park factory), 12 (LightGBM forecaster + GF1); Plan 3 Task 7 (cached forecasts); Plan 5 Task 3 (TCN, LSTM, conformal calibration) | 4 Data and provenance, 5 Forecasting | Data, forecasting results |
| 3 | **Yash Petkar** | Simulator and resilience | Plan 2 Tasks 4–9 (tenants and series, dispatch safety layer, disruptions, frequency/UFLS, forecasters, `MicrogridEnv`); Plan 3 Tasks 1–3 (demand-response events, power factor, battery ageing); Plan 5 Task 4 (shed policies + FS1 fairness study) | 6 Simulator, 9 Resilience and fairness (FS1 part) | Simulator, disruptions, frequency and load-shedding |
| 4 | **Member 4** | Deep reinforcement learning | Plan 3 Task 8 (NumPy policy serving + SB3 export), Task 9 (PPO/SAC training, 5 seeds each, warm start); runs the RL arms of MB1/MB2 with Member 7 | 3 Related work (DRL), 7 Optimisation and learning (RL part) | PPO and SAC: training, validation, results |
| 5 | **Member 5** | Optimisation (MPC and unit commitment) | Plan 2 Task 10 (controller protocol, baselines, runner); Plan 3 Tasks 4–6 (shared LP, stochastic MPC + oracle, unit commitment) and Task 11 (controller comparison); Plan 5 Task 6 (UC1, DR1, EJ1 studies) | 3 Related work (MPC, UC), 7 Optimisation and learning (MPC/UC part), 9 (DR1, EJ1, UC1) | Unit commitment and stochastic MPC; demand response |
| 6 | **Member 6** | EMS dashboard and user experience | Plan 3 Task 10 (decision explanations → "Why" panel); Plan 4 Tasks 7–10 (replay player, power-flow, SoC gauge, all screens, stress-test screen, 3D park, browser journeys and accessibility) | 10 The product (screens), appendix screenshots | The dashboard tour; hands the keyboard to peers for the stress test |
| 7 | **Member 7** | Evaluation, ethics and report lead | Plan 2 Task 13 (baseline comparison script); Plan 5 Tasks 1–2 (statistics, MB1/MB2 benchmark), Task 5 (spoofing, plausibility guard, STRIDE threat model, CY1), Task 7 (course pack: report editor, deck assembly, demo script and stress-test runbook with Member 6, GenAI prompt log, AI-use statement, rubric map, references, submission checklist) | 2 The challenge, 8 Benchmark, 9 Cybersecurity, 11 Ethical considerations, 13 Limitations; final edit of the whole report | Benchmark results with confidence intervals; ethics; roadmap and limitations |

Everyone: keep `docs/course/genai-prompts.md` up to date for anything GenAI helped with (slide 20 rule: encircle
GenAI content and share prompts separately), attend both rehearsals, and answer peer questions on their own area.

## Order of work and hand-offs

```
Week of        Krishna (1)        Atharva (2)         Yash (3)            M4 RL            M5 MPC/UC          M6 UI               M7 Eval/Report
17 Nov         Plan 1             Plan 2 T1–T3        read Plan 2         SB3 tutorial     read Plan 2/3      UI sketches         literature list
24 Nov         review, merge      Plan 2 T11          Plan 2 T4–T6        —                Plan 2 T10*        —                   report skeleton
1 Dec          Plan 4 T1–T2       Plan 2 T12 (GF1)    Plan 2 T7–T9        —                —                  —                   Plan 2 T13
8 Dec          Plan 4 T3          Plan 3 T7           Plan 3 T1–T3        Plan 3 T8        Plan 3 T4–T5       Plan 3 T10          Plan 5 T1
15 Dec         Plan 4 T4–T5       Plan 5 T3           Plan 5 T4 (FS1)     Plan 3 T9 (train) Plan 3 T6, T11    Plan 4 T7           threat model
22 Dec – 4 Jan (holidays: long runs in the background — RL training, benchmark smoke runs)
5 Jan          Plan 4 T6          GF1 write-up        FS1 write-up        RL write-up      Plan 5 T6          Plan 4 T8           Plan 5 T2 (MB1/MB2)
12 Jan         Plan 4 T11         report §4–5         report §6           report §7 RL     report §7, §9      Plan 4 T9–T10       Plan 5 T5 (CY1)
19–26 Jan      integration, hosted demo, offline Docker; everyone: report sections final, deck slides drafted
2 Feb          Rehearsal 1 (timed, full)            · fixes
6 Feb          Rehearsal 2 (timed, fully offline)   · submission pack frozen (tag v1.0-final)
9 Feb          09:30 presentation · 23:59 Blackboard submission (Member 7 uploads, Krishna checks)
```
\* Plan 2 Task 10 needs Plan 2 Task 9 (`MicrogridEnv`) from Yash; Member 5 starts on the interfaces from the plan and
merges after Yash.

Critical hand-offs: Atharva → Yash (site config and data, Plan 2 T1–T3 before T4); Yash → Members 4, 5 (environment,
Plan 2 T9); Atharva → Member 5 (cached forecasts, Plan 3 T7, before MPC runs on real data); Members 4, 5 → Member 7
(controllers before MB1/MB2); Krishna → Member 6 (energy API, Plan 4 T5, before screens beyond the replay player).

## How we work

- Branch per task: `<name>/<plan>-<task>-<short-title>` (for example `atharva/p2-t12-gf1`), pull request to `main`,
  one reviewer from another area plus Krishna; CI must be green before merge.
- Every task in the plans is test-first: write the failing test, make it pass, commit.
- Numbers in the report and deck come only from `docs/course/metrics.md` (generated from study results).
- Weekly 30-minute check-in (decisions and actions go in the meeting log in `CONTRIBUTIONS.md`).
- Before running anything that downloads data or trains for hours, say so in the group chat.

## Open items

- Names of Members 4–7.
- Confirm with Dr Roy which unit the submission counts for (slide 22 footer differs from slides 19–20) and what
  contribution evidence he expects.
- Krishna renames the Vercel and Neon projects to GridLens.
