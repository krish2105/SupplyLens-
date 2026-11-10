# Course coverage: AI in Operations (MAIB AI 218) → SupplyLens

How the group project maps to the unit's weekly topics (unit outline, section 2.4). This is a map of the **group
project** only. It is not a lab report, an exercise answer or a quiz answer: Laboratory Work and Problems and Exercises
are separate assessments in the outline (the Phase 8 brief and the owner treat them as individual work) and are not
done here. The full check of the outline, including class activities, cases and readings, is
[`outline-check.md`](outline-check.md).

Numbers are not repeated here; they are in [`metrics.md`](metrics.md) (generated from the study registry). Evidence ids
point to [`docs/agent-handoff/EVIDENCE.md`](../agent-handoff/EVIDENCE.md). Unit outcomes: A apply AI to optimise
operations; B evaluate AI's impact on supply chain and logistics; C responsible AI-based solutions; D integrate
generative AI for operational efficiency.

Status: **done** = built, tested and on the Research page or a product screen; **partly** = some of the week's topics
are covered, the rest is planned; **planned 8B / 8C** = scheduled in the Phase 8 brief, not built yet; **blocked** =
needs an owner decision or approval first.

| Week | Topic (unit outline) | Study id / module | Main files | Research card | Screen | Evidence | Outcome | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | Introduction: operations management, role of AI, KPIs | Product framing; overview KPIs (at risk, excess, awaiting approval, policy changes ahead) | `apps/web/app/(app)/page.tsx`, `README.md` | — | Overview | P8-E01 (baseline) | A | done |
| 2 | Supply chain optimisation (multi-objective cost, service, sustainability) | E1 CO2 trade-off; deterministic CP-SAT planner | `evaluations/emissions_study.py`, `optimisation/supplylens_opt/planner.py`, `emissions.py` | Operations studies: E1 | Scenario studio (CO2 panel), Research | P7-E02 | A, B | done |
| 2 | Risk scoring and predictive maintenance (delays, breakdowns, fuel) | D1 delay risk (simulated); PM1 maintenance; FE1 fuel-inefficient trips (simulated) | `evaluations/delay_risk_study.py`, `evaluations/maintenance_study.py`, `evaluations/fuel_study.py` | Operations studies: D1; Running the warehouse: PM1; Moving goods: FE1 | Research | P7-E06, P7-E15, P8-E20 | A, B | done (FE1 on generated telemetry) |
| 3 | Demand forecasting (Prophet, XGBoost, LSTM; MAPE, RMSE; weather) | F1 LightGBM and quantile TCN vs seasonal naive; W1 Prophet, XGBoost, weather, RMSE/WAPE/MAPE; W2 LSTM on W1's protocol | `evaluations/forecast_study.py`, `evaluations/weather_study.py`, `evaluations/lstm_study.py`, `ml/supplylens_ml/` | Forecasting (F1); Operations studies: W1, W2 | Forecast lab, Research | P7-E04, P8-E20 | A | done |
| 4 | Inventory: ABC analysis, safety stock, service-level trade-off | ABC/XYZ classes, safety stock z·σ·√L, cost-of-service curve; IB benchmark; lead-time demand model (simulated) | `services/api/src/supplylens/planning/classes.py`, `evaluations/inventorybench_study.py`, `evaluations/leadtime_demand_study.py` | InventoryBench (IB) | Inventory (classes panel), Research | P7-E08 | A | done |
| 5 | Production planning and scheduling (job shop) | JS1 receiving-floor job shop, CP-SAT vs dispatch rules | `evaluations/scheduling_study.py` | Running the warehouse: JS1 | Research | P7-E15 | A | done |
| 6 | Quality control and predictive maintenance | QC1 visual inspection CNN; PM1 failure prediction and remaining life | `evaluations/vision_qc_study.py`, `evaluations/maintenance_study.py` | Running the warehouse: QC1, PM1 | Research | P7-E15 | A, B | done |
| 7 | Logistics: ETA prediction, last-mile routing | ET1 arrival times with intervals; RT1 OR-Tools routes with capacity and windows | `evaluations/eta_study.py`, `evaluations/routing_study.py` | Moving goods: ET1, RT1 | Research | P8-E20 | B | done on generated data (real LaDe / Amazon data needs the owner's approval) |
| 8 | Process automation: document processing with AI, support chatbot with HubSpot | Document upload (plain text), clause retrieval C1, answer support R3; X1 contract-term extraction (Policies › Extracted terms, draft only); AS1 status assistant with a HubSpot ticket hand-off (dry run unless switched on) and an n8n hand-off workflow | `services/api/src/supplylens/knowledge/extract.py`, `services/api/src/supplylens/assistant/`, `infra/n8n/`, `evaluations/extraction_study.py`, `evaluations/assistant_study.py` | C1, R3; Documents and answers: X1, AS1 | Policies & evidence (Extracted terms tab); header assistant | P7-E05, P8-E22, P8-E23 | D | done (PDF intake open: plain text only, D-076) |
| 9 | Case studies (Amazon forecasting, Toyota vision CNN) | F1 (forecasting), QC1 (CNN defect classifier); cases tied to studies in [`case-links.md`](case-links.md) | as weeks 3 and 6 | F1, QC1 | Forecast lab, Research | P7-E15, P8-E24 | A, B | done |
| 10 | Ethics: bias and fairness (SMOTE, re-weighting, adversarial debiasing) | FA1 reweighing of a binding allocation; B1 SMOTE, re-weighting, threshold moving and adversarial debiasing with group parity; [`responsible-ai.md`](responsible-ai.md) (draft) | `evaluations/fairness_study.py`, `evaluations/imbalance_study.py`, `evaluations/adversarial_child.py` | Operations studies: FA1, B1 | Research | P7-E03, P8-E20 | C | done |
| 11 | Generative AI: RAG chatbot, agentic AI (n8n, Zapier) | G1 cited generated answers (local model, off in the demo); R2/R3 retrieval; RED1 red team and the two defences it led to; n8n planner-only agent and hand-off workflow; AGT investigator | `services/api/src/supplylens/knowledge/generate.py`, `infra/n8n/`, `evaluations/generation_study.py`, `evaluations/redteam_study.py`, `evaluations/agent_study.py` | Operations studies: G1; AGT; Documents and answers: RED1 | Policies & evidence (answer panel, local only) | P7-E05, P7-E07, P8-E21 | D, C | done (human-written questions G2 must come from people: open) |
| 12 | Final group project, presentation and evaluation | Interim pack (8A), final pack (8C) | `docs/course/` | — | — | — | A–D | interim: draft (8A); final: planned 8C |

## What is simulated

Every planning study (E1, FA1, JS1 routes, D1, the PM1 fleet, QC1 images, FE1 trips, ET1 deliveries, RT1 delivery days)
runs on simulated or assumed operations data: the UCI dataset records sales only. B1 uses AI4I 2020, a published
synthetic dataset. The kind of every number is stated in [`metrics.md`](metrics.md). No study measures
a real business outcome yet.

---

AI use: see [`ai-use-statement.md`](ai-use-statement.md) (draft awaiting the owner's approval).
