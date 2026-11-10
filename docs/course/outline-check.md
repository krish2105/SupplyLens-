# Unit outline check — AI in Operations (MAIB AI 218)

Checked on 2026-11-10 against the unit outline (kept privately as `private/unit-outline.docx`, never committed; summarised
here in our own words). Compared with: [`coverage.md`](coverage.md), [`metrics.md`](metrics.md), the interim deck, the
final-deck skeleton, the demo script, the marker guide, the AI-use statement, and the Phase 8 brief and planning context.
This is a map of the **group project**; it does not do or answer any lab, exercise or quiz.

## 1. Unit facts (outline section 1)

| Item | Outline | Where we use it | Check |
|---|---|---|---|
| Unit | AI in Operations, MAIB AI 218; core unit of the Master of Artificial Intelligence in Business | Decks, marker guide, CONTRIBUTIONS | matches |
| Coordinator | Sandip Roy | Phase 8 planning context | matches (not needed in course documents) |
| Workload | 12 weeks; 3 timetabled + 7 private hours a week (36 + 84) | Phase 8 planning context | matches |
| Prerequisites | Machine Learning; Operations Management | Phase 8 planning context | matches |
| Resources | Cloud lab access and open-source software | The project is built on open-source tools; the public demo runs on Vercel and Neon | consistent |
| Work-integrated learning | None | — | — |

## 2. Learning outcomes and alignment (outline 2.3, 2.6)

| Outcome | Outline wording (short) | Our wording | Check |
|---|---|---|---|
| A | Use (2.3) / apply (2.6) AI techniques to optimise operational processes | "Apply AI to optimise operations" | matches |
| B | Evaluate the impact of AI on supply chain and logistics | "Evaluate AI's impact on supply chain and logistics" | matches |
| C | Develop responsible AI-based solutions for operations problems | "Develop responsible AI-based solutions" | matches |
| D | Integrate generative AI tools to enhance operational efficiency | "Integrate generative AI for operational efficiency" | matches |

Alignment in the outline: A–D map to course outcome CLO2 (critical thinking, design and decision-making); C and D also
to CLO3 (communication and team performance); C to CLO4 (ethics and social responsibility). CLO1 and CLO5 are not
addressed by this unit. For the project this means: team collaboration evidence (CLO3) comes from the team's own record
of who did what (CONTRIBUTIONS.md, names only so far), and the responsible-AI document (8C) carries CLO4.

## 3. Assessments (outline 2.5 and section 3)

| Assessment | Weight | When | Outcomes | What the outline says it is | Project's part | Status |
|---|---|---|---|---|---|---|
| Problems and Exercises | 30 % | every session | A–D | theoretical questions and practical coding and data-analysis tasks on each session's topics | none: the owner's own work, not done here | not in scope |
| Group Project and Classroom Presentation | 10 % | Week 6 | A–D | groups apply AI-in-Operations techniques to a real-world problem and present the findings | interim deck, five-minute demo script, marker guide | draft (8A) |
| Laboratory Work | 30 % | Weeks 2, 4, 6, 8, 10 | A–D | practical sessions implementing models, experimenting, analysing performance; reports | none: not done here | not in scope |
| Final Group Project | 30 % | exam week | A–D | a comprehensive group project integrating the unit to solve a complex problem | final deck (skeleton), report, rubric map (8C) | planned 8C |

Not in the outline, so they stay questions for the owner and lecturer: whether exercises and labs are individual (the
Phase 8 brief says so; the outline does not state it), report length, template and file type, presentation time
limits and dates beyond the week, and how AI use must be acknowledged (8A.1b, 8A.1d).

## 4. Rubrics (outline 3.2 and 3.4) and where the project answers them

| Rubric | Criterion | Where it is answered | Gap |
|---|---|---|---|
| 3.2 interim | Content quality | Interim deck: problem, data and its limits, results with their data kind | — |
| 3.2 interim | Application of techniques | Architecture, the end-to-end spine, results S2 (exploratory), E1, QC1 | — |
| 3.2 interim | Presentation skills | Deck structure, five-minute demo script with fallbacks | spoken rehearsal against the time limit (limit unknown) |
| 3.2 interim | Team collaboration ("equal contribution from members") | Team slide; CONTRIBUTIONS.md | **who did what is not recorded yet** (names only): the team must agree and record it |
| 3.4 final | Research depth | results.md, metrics.md, negative results kept, references (8C) | references in APA 7, verified (8C) |
| 3.4 final | Innovation | Two clocks (known by / in force on), cite-or-withhold answers, approvals bound to the exact payload | — |
| 3.4 final | Application of techniques | One study or module per weekly topic (section 5) | weeks 7, 8, 10 partly or planned (8B) |
| 3.4 final | Presentation and reporting | Final deck and report (8C) | 8C |

Rubrics 3.1 (exercises) and 3.3 (labs) belong to the individual assessments and are not used by the project.

## 5. Weekly topics, labs and class activities (outline 2.4)

"Project" lists only what the group project contains; labs, quizzes and class activities are not done here.

| Week | Topic | Labs in the outline | Class activities, cases, readings | Project | Gap or note |
|---|---|---|---|---|---|
| 1 | Introduction; operations management and the role of AI | Set up; load an operational dataset and explore KPIs | Map a familiar process and find AI opportunities; AI-Tutor quiz; Dattana & Rao (2024) ch. 1–2; Ng (2021) | Overview KPIs (at risk, excess, awaiting approval, policy changes) | — |
| 2 | AI in supply chain management | (1) multi-objective optimisation of cost, service level and sustainability; (2) risk scoring and predictive maintenance: delays, equipment breakdowns, fuel inefficiency | AI in SCM demo (Dubai RTA); quiz; Abaku et al. (2024) | E1 (cost, coverage, CO2 frontier); D1 (late deliveries, simulated); PM1 (breakdowns) | **fuel inefficiency** has no model; 8B L2 only estimates fuel and CO2 from route distance with assumed factors |
| 3 | Predictive analytics for demand forecasting | Prophet, XGBoost, LSTM on sales plus weather; MAPE, RMSE | Seyedan & Mafakheri (2020); Hemachandran et al. (2023) ch. 4 | F1 (LightGBM, TCN vs seasonal naive); W1 (Prophet, XGBoost, weather; MAE, RMSE, WAPE, MAPE) | **LSTM** planned 8B WP4 |
| 4 | Inventory management and optimisation | ABC analysis and a safety-stock calculator; service-level trade-offs | Inventory demo; case: mobile-clinic inventory (SMU024); quiz; Foya (2021); Hemachandran ch. 6 | ABC/XYZ classes, safety stock, cost-of-service curve; IB benchmark | case links in 8C |
| 5 | Production planning and scheduling | Job-shop scheduling across machines | AI-scheduler demo; case: Gupta Furniture aggregate planning (W30149); Nwasuka & Nwaiwu (2023); Hemachandran ch. 13 | JS1 (CP-SAT vs dispatch rules, ft06 check) | case links in 8C |
| 6 | Quality control and predictive maintenance | Predictive maintenance; deep learning for time-series maintenance | Discussion: inspection vs prediction; **group project presentation**; final-project discussion; Thomke et al. (2025) | QC1 (inspection CNN and policy); PM1 (failure model; 1D-CNN remaining life, a negative result) | — |
| 7 | AI in logistics and transportation | ETA prediction; route planning with last-mile constraints | Fleet predictive-maintenance demo; case: Paack (IES914); Chung (2021) | — | **planned 8B WP3** (dataset approval needed) |
| 8 | Process automation with AI | AI chatbot for customer support with HubSpot integration | Document-processing demo; case H08SHM; Hofmann et al. (2020) | Document upload (plain text), clause retrieval C1, answer support R3 | **PDF extraction and the support assistant with HubSpot hand-off planned 8B** (WP6, WP7) |
| 9 | Case studies in operational AI | Defect vs non-defect CNN (Toyota-style vision QC) | Amazon demand-forecasting demo; Duolingo and HealthPlix cases | QC1 (the CNN); F1 (forecasting) | case links in 8C |
| 10 | Ethics: bias and fairness | Re-sampling (SMOTE), re-weighting **or** adversarial debiasing | Strategy video; Blackman (2022, two articles) | FA1 (reweighing an allocation) | classifier SMOTE / class weights / parity planned 8B WP5; adversarial debiasing is not planned (the outline asks for one of the three) |
| 11 | Generative AI in operations | RAG chatbot; agentic AI such as n8n or Zapier | GenAI demo; Farri & Rosani (2025); Edelman & Abraham (2023); Alavi & Westerman (2023) | G1 (cited generated answers, local model, off in the public demo); R2/R3 retrieval; n8n planner-only agent; AGT investigator | red team and human-written questions planned 8B WP8; n8n stands for "n8n or Zapier" |
| 12 | Final group project, presentation and evaluation | — | Final presentation | Final pack (8C) | 8C |

## 6. Prescribed and recommended reading (outline 2.7) — for the 8C reference list

The brief's 8C reference list already names: Unhelkar & Gonsalves (2021); Kersten (2019); Hemachandran et al. (2023);
Abaku et al. (2024); Seyedan & Mafakheri (2020); Foya (2021); Nwasuka & Nwaiwu (2023); Thomke et al. (2025); Chung
(2021); Hofmann et al. (2020); Blackman (2022, two articles); Edelman & Abraham (2023); Alavi & Westerman (2023).

In the outline but **not yet in the brief's list** (add in 8C if cited, each verified first): Ng (2021, HBR, week 1);
Dattana & Rao (2024, week 1 reading); Farri & Rosani (2025, HBR Guide; already in owner-answers-8C); the cases Zeller et
al. (2022, mobile clinic), Sharma (2024, Gupta Furniture), Zamora et al. (2022, Paack), Catalini et al. (2025, "What
gets measured, AI will automate"), Rayport et al. (2025, Duolingo), Shao et al. (2022, HealthPlix).

The outline names the week 5 review two ways: "Nwasuka & Uchechukwu (2023)" in the weekly table and "Nwasuka & Nwaiwu
(2023)" in the reading list (with DOI 10.1016/j.jer.2023.09.027). Verify the authors from the DOI before citing it.

## 7. What this check changed

- `coverage.md`: no longer says the outline makes labs and exercises individual (the brief and the owner do); adds the
  week 2 fuel-inefficiency gap, the week 10 choice among SMOTE, re-weighting and adversarial debiasing, and n8n for
  "n8n or Zapier" in week 11.
- Facts in the Phase 8 planning context (unit, weeks, assessments, outcomes, topics, rubrics, coordinator) match the
  outline; the only difference is the word "individual", which the outline does not use.
- Course documents: unit name and code, outcome wording and the assessment timing (Week 6, exam week) match.
- Gaps for 8B and 8C are unchanged and listed above; nothing in the outline is claimed as done when it is not.

---

AI use: see [`ai-use-statement.md`](ai-use-statement.md) (draft awaiting the owner's approval).
