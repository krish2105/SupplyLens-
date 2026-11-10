# Course coverage: AI in Operations (MAIB AI 218) → SupplyLens

How the group project maps to the unit's weekly topics (unit outline, section 2.4). This is a map of the **group
project** only. It is not a lab report, an exercise answer or a quiz answer: the weekly labs and exercises are each
student's individual work and are not done here.

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
| 2 | Risk scoring and predictive maintenance (delays, breakdowns, fuel) | D1 delay risk (simulated); PM1 maintenance; fuel/CO2 from distance in routing | `evaluations/delay_risk_study.py`, `evaluations/maintenance_study.py` | Operations studies: D1; Running the warehouse: PM1 | Research | P7-E06, P7-E15 | A, B | partly (fuel in routing planned 8B WP3) |
| 3 | Demand forecasting (Prophet, XGBoost, LSTM; MAPE, RMSE; weather) | F1 LightGBM and quantile TCN vs seasonal naive; W1 Prophet, XGBoost, weather, RMSE/WAPE/MAPE | `evaluations/forecast_study.py`, `evaluations/weather_study.py`, `ml/supplylens_ml/` | Forecasting (F1); Operations studies: W1 | Forecast lab, Research | P7-E04 | A | partly (LSTM planned 8B WP4) |
| 4 | Inventory: ABC analysis, safety stock, service-level trade-off | ABC/XYZ classes, safety stock z·σ·√L, cost-of-service curve; IB benchmark; lead-time demand model (simulated) | `services/api/src/supplylens/planning/classes.py`, `evaluations/inventorybench_study.py`, `evaluations/leadtime_demand_study.py` | InventoryBench (IB) | Inventory (classes panel), Research | P7-E08 | A | done |
| 5 | Production planning and scheduling (job shop) | JS1 receiving-floor job shop, CP-SAT vs dispatch rules | `evaluations/scheduling_study.py` | Running the warehouse: JS1 | Research | P7-E15 | A | done |
| 6 | Quality control and predictive maintenance | QC1 visual inspection CNN; PM1 failure prediction and remaining life | `evaluations/vision_qc_study.py`, `evaluations/maintenance_study.py` | Running the warehouse: QC1, PM1 | Research | P7-E15 | A, B | done |
| 7 | Logistics: ETA prediction, last-mile routing | ETA and routing studies | — | — | — | — | B | planned 8B WP3 (blocked until the owner approves a dataset) |
| 8 | Process automation: document processing with AI, support chatbot with HubSpot | Document upload (plain text), clause retrieval C1, answer support R3; PDF intake and extraction (X1), status assistant and CRM hand-off | `services/api/src/supplylens/knowledge/`, `evaluations/retrieval_study.py`, `evaluations/answer_support_study.py` | C1, R3 | Policies & evidence | P7-E05 (G1 uses the same retrieval) | D | partly (WP6, WP7 planned 8B) |
| 9 | Case studies (Amazon forecasting, Toyota vision CNN) | F1 (forecasting), QC1 (CNN defect classifier) | as weeks 3 and 6 | F1, QC1 | Forecast lab, Research | P7-E15 | A, B | partly (case links planned 8C WP11) |
| 10 | Ethics: bias and fairness (SMOTE, re-weighting, adversarial debiasing) | FA1 reweighing of a binding allocation; imbalance and group parity on PM1/D1 | `evaluations/fairness_study.py` | Operations studies: FA1 | Research | P7-E03 | C | partly (SMOTE and parity, B1, planned 8B WP5) |
| 11 | Generative AI: RAG chatbot, agentic AI (n8n, Zapier) | G1 cited generated answers (local model, off in the demo); R2/R3 retrieval; n8n planner-only agent; AGT investigator | `services/api/src/supplylens/knowledge/generate.py`, `infra/n8n/`, `evaluations/generation_study.py`, `evaluations/agent_study.py` | Operations studies: G1; AGT | Policies & evidence (answer panel, local only) | P7-E05, P7-E07 | D, C | partly (red team and human-written questions planned 8B WP8) |
| 12 | Final group project, presentation and evaluation | Interim pack (8A), final pack (8C) | `docs/course/` | — | — | — | A–D | interim: draft (8A); final: planned 8C |

## What is simulated

Every planning study (E1, FA1, JS1 routes, D1, the PM1 fleet, QC1 images) runs on simulated or assumed operations data:
the UCI dataset records sales only. The kind of every number is stated in [`metrics.md`](metrics.md). No study measures
a real business outcome yet.

---

AI use: see [`ai-use-statement.md`](ai-use-statement.md) (draft awaiting the owner's approval).
