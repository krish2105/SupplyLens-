# Phase 8 planning context (from the owner's planning session, 10 Nov 2026)

Read after PHASE-08_COURSE_PROMPT_v4.md. This records how the brief was made, so a session with zero context does not
repeat old mistakes. Treat every statement as a lead to verify in the repository.

## 1. Course facts the brief is built on (from the unit outline, kept privately in private/unit-outline.docx)
- Unit: AI in Operations (MAIB AI 218), Master of AI in Business, S P Jain Dubai, Term 4; coordinator Sandip Roy.
- 12 weeks, 3 class hours + 7 study hours per week. Prerequisites: Machine Learning, Operations Management.
- Assessment: Problems and Exercises 30 % (every session); Group Project and Classroom Presentation 10 % (Week 6);
  Laboratory work 30 % (Weeks 2, 4, 6, 8, 10); Final Group Project 30 % (exam week).
- Outcomes: A optimise operations with AI; B evaluate AI's impact on supply chain and logistics; C responsible
  AI-based solutions; D integrate generative AI for operational efficiency.
- Weekly topics and labs: 1 intro and KPIs; 2 supply chain (multi-objective cost/service/sustainability; risk scoring
  and predictive maintenance: delays, breakdowns, fuel); 3 demand forecasting (Prophet, XGBoost, LSTM; MAPE, RMSE;
  weather); 4 inventory (ABC, safety stock, service-level trade-off); 5 production scheduling (job shop); 6 quality
  control and predictive maintenance; 7 logistics (ETA prediction, last-mile routing); 8 process automation (document
  processing with AI, support chatbot with HubSpot); 9 case studies (CNN defect classifier); 10 ethics (SMOTE,
  re-weighting, adversarial debiasing); 11 generative AI (RAG chatbot, agentic AI: n8n, Zapier); 12 final presentation.
- Rubrics: interim = content quality, application of techniques, presentation skills, team collaboration;
  final = research depth, innovation, application of techniques, presentation and reporting.

## 2. What the repository already had at 9f8da12 (verified by reading code and history, not the README)
An earlier gap list was made from the README alone and was WRONG: the README is stale. Phase 7 and the 30 Oct
warehouse studies already delivered ABC/XYZ and safety stock, CO2 cap and frontier (E1), fairness reweighing (FA1),
RMSE/WAPE/MAPE with Prophet, XGBoost and weather (W1), delay risk (D1, simulated), cited generated answers with a local
model (G1, off in the public demo), an n8n planner-only agent, job shop (JS1), predictive maintenance (PM1) and a
vision QC CNN (QC1). Real remaining course gaps: Week 7 logistics, LSTM, Week 8 support assistant and CRM hand-off,
Week 8 AI document processing (uploads are plain text only), classifier imbalance/parity (SMOTE), GenAI red team and
human-written questions, responsible-AI document and model cards, business case, presentation pack, stale docs.

## 3. Hosted demo defects seen by the owner (WP0)
Screenshot: docs/screenshots/phase8/owner-2026-11-10-overview-light.png (Overview, UCI Research, light theme).
- 3D warehouse rendered with dark tokens in light theme. Likely cause in code: warehouse3d.tsx reads token() in a
  useMemo keyed on resolvedTheme during render, before next-themes applies the html class; chart.tsx avoids this by
  applying the theme one animation frame later (S17).
- "What this data can answer": Stock positions and Supplier terms show green "available" while the API's basis is
  "simulated"; the UI drops `basis` from capability_matrix (routes_core.py).
- Legend overlay is translucent (bg-surface/90) and covers racks.
The planning session could not open the hosted site itself (tool limits); hosted checks must be run by the session.

## 4. Academic integrity (decisive)
S P Jain Academic Integrity Policy, version of 24 Feb 2026 (spjain.ae): generative-AI use in assessed work is
misconduct unless the assessment permits it and it is acknowledged; students must acknowledge AI tools in written
assessments and use APA; submitting one piece of work for more than one assignment needs explicit permission; group
work must be the group's. Hence the AI-use statement in docs/course/ and the lecturer questions in 8A.1. The older
repository preference "never mention any AI assistant" does not apply to submitted course documents.

## 5. Research facts used in the brief (checked 10 Nov 2026; re-check before relying on them)
- LaDe (Cainiao): Hugging Face card Apache-2.0 plus "research purposes, read terms"; LaDe-D about 4.5 M rows over five
  cities (Jilin about 31 k rows, Yantai 206 k, Shanghai 1.48 M, Hangzhou 1.86 M); KDD 2024, doi 10.1145/3637528.3671548.
- Amazon Last Mile Routing Research Challenge 2021: 9,184 real routes (2018, five US metros) with actual driver
  sequences; CC BY-NC 4.0; free S3 download without an AWS account; doi 10.1287/trsc.2022.1173.
- HubSpot 2026: legacy developer accounts merged into standard accounts (9 Mar 2026); legacy private apps no longer
  creatable (reported 23 Jun 2026); single-account access by Service Key (beta) or static-auth private app on the new
  developer platform; developer test accounts free (up to 10, 90-day trial, expire after 90 days without API calls);
  ticket create works on the free tier; scopes crm.objects.tickets.read/write.
- Image models: transparent-background support differs by model; the image prompt file has a fallback.
- Local generation model in the repo: Ollama qwen2.5:7b, temperature 0 (keep for G2 comparability).

## 6. Design decisions taken in planning
- Phase 8 is split 8A (before Week 6: WP0 fixes, truth in docs, metrics source, interim pack), 8B (Weeks 6–10:
  studies and new UI), 8C (Weeks 10–12: responsible AI, business case, final pack).
- Illustrations follow the existing clay style and docs/design/illustrations.md rules (art only in empty states,
  never data). The agent never generates images; the owner makes them with docs/design/image-prompts-phase8.md.
- Presentation numbers only from docs/course/metrics.md; references verified; 48-hour push freeze before presentations.
