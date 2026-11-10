# Unit outline check — AI in Operations (MAIB AI 218)

Checked on 2026-11-10 (second pass the same day, after the coverage studies) against the unit outline (kept privately as `private/unit-outline.docx`, never committed; summarised
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
of who did what (CONTRIBUTIONS.md: a table and a meeting log for the team to fill in and agree), and
[`responsible-ai.md`](responsible-ai.md) (draft: each control with its risk, code, test and evidence) carries CLO4.

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
| 3.2 interim | Team collaboration ("equal contribution from members") | Team slide; CONTRIBUTIONS.md (who-did-what table and meeting log) | **the team must fill in and agree the table**; nothing is filled in on anyone's behalf |
| 3.4 final | Research depth | results.md, metrics.md, negative results kept, [`references.md`](references.md) (35 entries looked up: 31 verified, 4 partly), [`case-links.md`](case-links.md) | — |
| 3.4 final | Innovation | Two clocks (known by / in force on), cite-or-withhold answers, approvals bound to the exact payload | — |
| 3.4 final | Application of techniques | One study or module per weekly lab topic (section 5) | — (weeks 2, 7 and the logistics half of 2 on generated data; real data needs approval) |
| 3.4 final | Presentation and reporting | Final deck and report (8C) | 8C |

Rubrics 3.1 (exercises) and 3.3 (labs) belong to the individual assessments and are not used by the project.

## 5. Weekly topics, labs and class activities (outline 2.4)

"Project" lists only what the group project contains; labs, quizzes and class activities are not done here.

| Week | Topic | Labs in the outline | Class activities, cases, readings | Project | Gap or note |
|---|---|---|---|---|---|
| 1 | Introduction; operations management and the role of AI | Set up; load an operational dataset and explore KPIs | Map a familiar process and find AI opportunities; AI-Tutor quiz; Dattana & Rao (2024) ch. 1–2; Ng (2021) | Overview KPIs (at risk, excess, awaiting approval, policy changes) | — |
| 2 | AI in supply chain management | (1) multi-objective optimisation of cost, service level and sustainability; (2) risk scoring and predictive maintenance: delays, equipment breakdowns, fuel inefficiency | AI in SCM demo (Dubai RTA); quiz; Abaku et al. (2024) | E1 (cost, coverage, CO2 frontier); D1 (late deliveries, simulated); PM1 (breakdowns); FE1 (fuel-inefficient trips, simulated) | covered; FE1 runs on generated telemetry |
| 3 | Predictive analytics for demand forecasting | Prophet, XGBoost, LSTM on sales plus weather; MAPE, RMSE | Seyedan & Mafakheri (2020); Hemachandran et al. (2023) ch. 4 | F1 (LightGBM, TCN vs seasonal naive); W1 (Prophet, XGBoost, weather; MAE, RMSE, WAPE, MAPE); W2 (LSTM on W1's protocol) | covered; W2 has no weather input (the weather file is not stored) |
| 4 | Inventory management and optimisation | ABC analysis and a safety-stock calculator; service-level trade-offs | Inventory demo; case: mobile-clinic inventory (SMU024); quiz; Foya (2021); Hemachandran ch. 6 | ABC/XYZ classes, safety stock, cost-of-service curve; IB benchmark | covered; case linked in case-links.md |
| 5 | Production planning and scheduling | Job-shop scheduling across machines | AI-scheduler demo; case: Gupta Furniture aggregate planning (W30149); Nwasuka & Nwaiwu (2023); Hemachandran ch. 13 | JS1 (CP-SAT vs dispatch rules, ft06 check) | covered; case linked in case-links.md |
| 6 | Quality control and predictive maintenance | Predictive maintenance; deep learning for time-series maintenance | Discussion: inspection vs prediction; **group project presentation**; final-project discussion; Thomke et al. (2025) | QC1 (inspection CNN and policy); PM1 (failure model; 1D-CNN remaining life, a negative result) | — |
| 7 | AI in logistics and transportation | ETA prediction; route planning with last-mile constraints | Fleet predictive-maintenance demo; case: Paack (IES914); Chung (2021) | ET1 (arrival times with intervals); RT1 (OR-Tools routes with capacity and windows) | covered on generated data; LaDe / Amazon Last Mile need the owner's approval |
| 8 | Process automation with AI | AI chatbot for customer support with HubSpot integration | Document-processing demo; case H08SHM; Hofmann et al. (2020) | Document upload (plain text), clause retrieval C1, answer support R3; X1 (contract-term extraction on CUAD labels, Policies › Extracted terms); AS1 (status assistant with a HubSpot ticket hand-off, dry run unless switched on) | covered; PDF intake stays open (plain text only, D-076); the HubSpot call needs a test account and the owner's flag |
| 9 | Case studies in operational AI | Defect vs non-defect CNN (Toyota-style vision QC) | Amazon demand-forecasting demo; Duolingo and HealthPlix cases | QC1 (the CNN); F1 (forecasting) | covered; cases linked in case-links.md |
| 10 | Ethics: bias and fairness | Re-sampling (SMOTE), re-weighting **or** adversarial debiasing | Strategy video; Blackman (2022, two articles) | FA1 (reweighing an allocation); B1 (SMOTE, re-weighting, threshold moving and adversarial debiasing on a failure classifier, with group parity) | covered (all three of the outline's techniques) |
| 11 | Generative AI in operations | RAG chatbot; agentic AI such as n8n or Zapier | GenAI demo; Farri & Rosani (2025); Edelman & Abraham (2023); Alavi & Westerman (2023) | G1 (cited generated answers, local model, off in the public demo); R2/R3 retrieval; n8n planner-only agent and the hand-off workflow; AGT investigator; RED1 (red team) | covered; n8n stands for "n8n or Zapier"; human-written questions (G2) must come from people and stay open |
| 12 | Final group project, presentation and evaluation | — | Final presentation | Final pack (8C) | 8C |

## 6. Prescribed and recommended reading (outline 2.7) — for the 8C reference list

The brief's 8C reference list already names: Unhelkar & Gonsalves (2021); Kersten (2019); Hemachandran et al. (2023);
Abaku et al. (2024); Seyedan & Mafakheri (2020); Foya (2021); Nwasuka & Nwaiwu (2023); Thomke et al. (2025); Chung
(2021); Hofmann et al. (2020); Blackman (2022, two articles); Edelman & Abraham (2023); Alavi & Westerman (2023).

All of these, and the items below, are now looked up in [`references.md`](references.md). In the outline but **not in
the brief's list** (now verified too): Ng (2021, HBR, week 1);
Dattana & Rao (2024, week 1 reading); Farri & Rosani (2025, HBR Guide; already in owner-answers-8C); the cases Zeller et
al. (2022, mobile clinic), Sharma (2024, Gupta Furniture), Zamora et al. (2022, Paack), Catalini et al. (2025, "What
gets measured, AI will automate"), Rayport et al. (2025, Duolingo), Shao et al. (2022, HealthPlix).

The outline names the week 5 review two ways: "Nwasuka & Uchechukwu (2023)" in the weekly table and "Nwasuka & Nwaiwu
(2023)" in the reading list. The DOI (10.1016/j.jer.2023.09.027) resolves to Nnamdi Cyprian Nwasuka and Uchechukwu
Nwaiwu: "Uchechukwu" is the second author's first name. The article went online in 2023 and its issue is 2024 (12(1),
275–280), so APA 7 gives Nwasuka & Nwaiwu (2024).

Found while verifying, for the lecturer: the outline's chapter numbers for Hemachandran & Rodriguez (ch. 4 for
forecasting, ch. 6 for inventory) do not match the book's contents (only ch. 13, supply chain, matches); Kersten (2019)
is an edited conference volume (Kersten, Blecker & Ringle, Eds.); Blackman's "3 conversations" is co-written with Beena
Ammanath; "What gets measured, AI will automate" (H08SHM) is an HBR article, not a case.

## 7. What this check changed

- `coverage.md`: no longer says the outline makes labs and exercises individual (the brief and the owner do); adds the
  week 2 fuel-inefficiency gap, the week 10 choice among SMOTE, re-weighting and adversarial debiasing, and n8n for
  "n8n or Zapier" in week 11.
- Facts in the Phase 8 planning context (unit, weeks, assessments, outcomes, topics, rubrics, coordinator) match the
  outline; the only difference is the word "individual", which the outline does not use.
- Course documents: unit name and code, outcome wording and the assessment timing (Week 6, exam week) match.
- Gaps for 8B and 8C are unchanged and listed above; nothing in the outline is claimed as done when it is not.

Second pass (2026-11-10, after the coverage studies):
- Every weekly lab topic now has a project study or module: FE1 (week 2 fuel), W2 (week 3 LSTM), ET1 and RT1 (week 7),
  X1 and AS1 (week 8), B1 (week 10, all three techniques), RED1 (week 11). Numbers are in `metrics.md`.
- Readings and cases: every item looked up ([`references.md`](references.md)); each case tied to the parts it connects to
  ([`case-links.md`](case-links.md)).
- Team collaboration: CONTRIBUTIONS.md has the who-did-what table and a meeting log for the team to fill in.
- Still open, and not for the project to invent: the team's contribution record, the lecturer's answers (format, time
  limit, how AI use is acknowledged), human-written questions (G2), and approval for real logistics data.

---

AI use: see [`ai-use-statement.md`](ai-use-statement.md) (draft awaiting the owner's approval).
