# Prompt for the next working sessions: Phase 8 (course brief), version 4

Phase 8 is split into three sessions so the Week 6 deadline is met first. Paste one fenced block per session, in order:
**8A** (before Week 6), **8B** (Weeks 6–10), **8C** (Weeks 10–12). Each session stops at its end.
Suggested place in the repo: `docs/agent-handoff/NEXT_SESSION_PROMPT.md` (replace the stale Phase 7 prompt).

Changes in version 4: WP0 fixes defects seen on the hosted demo on 2026-11-10 (3D view stays dark in light mode;
simulated data shown as plain green "available"; legend overlay), plus a read-only hosted light/dark sweep.

Changes in version 3: UI requirements for every new screen (placement, states, themes, widths, accessibility,
screenshot baselines, new journeys); owner-supplied illustrations A02, A13, A16 and new A17–A18 integrated only after
approval (prompts in SupplyLens_image_prompts_phase8.md); deck visuals rules.

Changes from version 1: academic-integrity rule made explicit (S P Jain policy, 24 Feb 2026); sessions split around the
Week 6 deadline; new AI document-extraction study on CUAD (Week 8); prompt-injection suite for generated answers;
fuel/CO2 in routing; business case and value ledger; APA references; marker guide; release tags and a deploy freeze
before presentations; HubSpot 2026 platform changes.

---

## Common header (paste this at the top of every session)

```text
SUPPLYLENS — PHASE 8 (OWNER BRIEF): COURSE COVERAGE, RESPONSIBLE AI AND THE PRESENTATION PACK
Repository: https://github.com/krish2105/SupplyLens-  (branch main)
Phase 7 hand-over: 9f8da12 (2026-10-30). Check git log and the latest CI run before trusting anything below.

CONTEXT
SupplyLens is the owner's project for the MAIB unit "AI in Operations" (MAIB AI 218, S P Jain Dubai, Term 4).
Assessment: Problems and Exercises 30 % (every session, individual), Group Project and Classroom Presentation 10 %
(Week 6), Laboratory work 30 % (Weeks 2, 4, 6, 8, 10, individual), Final Group Project 30 % (exam week).
Unit outcomes: A apply AI to optimise operations; B evaluate AI's impact on supply chain and logistics; C develop
responsible AI-based solutions; D integrate generative AI tools for operational efficiency.
Final-project rubric: research depth, innovation, application of AI-in-operations techniques, presentation and reporting.
Interim rubric: content quality, application of techniques, presentation skills, team collaboration.
This phase closes the remaining course gaps with small honest studies, makes the documents tell the truth, and builds
the presentation pack. It is not a production-readiness phase; identity/SaaS moves to Phase 9.

Act as a Principal ML Engineer and technical writer. The repository is the only source of truth.

ACADEMIC INTEGRITY (overrides older repository preferences for everything under docs/course/)
- S P Jain's Academic Integrity Policy (version of 24 February 2026) treats generative-AI use in assessed work as
  misconduct unless the assessment allows it and the use is acknowledged; students must acknowledge AI tools in written
  assessments and reference in APA style. It also restricts submitting one piece of work for more than one assignment
  without permission, and requires group work to be the group's.
- Therefore every submitted artefact (report, decks) carries docs/course/ai-use-statement.md: which AI tools were used,
  for which parts (code, analysis, writing), and how a person checked the output. Never remove, soften or hide it.
- Root NEXT_SESSION.md says "never mention any AI assistant in commits or files". That preference may continue for
  commit metadata only if the owner confirms it; it does not apply to docs/course/. Record the owner's decision as a
  D-id. If the owner refuses the statement, STOP and ask them to obtain the lecturer's written guidance first.
- Never invent team members, contributions, references or results.

RULES THAT CARRY OVER (section 3 of the previous NEXT_SESSION_PROMPT.md still applies; the key ones:)
- A push to main deploys the public demo. Push only code that passed ruff, pytest, the contract check, tsc and the web
  build. After API, worker, ML, optimiser or uv.lock changes: python3 scripts/vercel/build_api.py --pin.
- Never weaken authentication, RLS, audit, approvals, CSRF, rate limits or the demo lockdown. Purchasing stays
  deterministic and approval-gated; the n8n agent keeps planner rights only (D-099).
- Generation: D-094 locally (cite-or-withhold, off unless SUPPLYLENS_GENERATION_ENABLED); the public demo keeps D-041.
- Never import torch in the pytest process (D-023); keep LightGBM/XGBoost and PyTorch in separate processes.
- Research: label every number by kind (historical backtest, simulation, offline evaluation with generated labels,
  published benchmark, human-labelled, real outcome). Frozen protocols stay frozen; a new model means a new study id.
  Superseded runs go to study_registry.json with a reason. Negative results are kept.
- New studies follow the pattern: evaluations/<name>_study.py, artifacts/experiments/<ID>-<timestamp>/{config,metrics}.json,
  a registry entry with a reviewed headline, a Research page card from the registry, a test that can fail.
- Presentation numbers come only from docs/course/metrics.md (WP2). No estimates or rounding up.
- Datasets are never joined across domains; download nothing without the owner's approval; record licence and hash.
- External services (HubSpot, any model API) are touched only with test accounts and an explicit env flag.

PRESENTATION SAFETY
- Pushes to main deploy production. From 48 hours before each presentation until it ends, do not push to main.
  Tag the graded version (course-interim, course-final) and record the commit and deploy id in EVIDENCE.md.
```

---

## Session 8A — before Week 6 (truth, numbers, interim pack)

```text
[paste the common header first]

8A.0 RESTORE CONTEXT (no code changes yet)
- git rev-parse HEAD; git status; git log --oneline -15; gh run list --workflow ci.yml --branch main --limit 3.
- Read: docs/agent-handoff/STATUS.md, PROGRESS.md, ISSUES.md, DECISIONS.md, EVIDENCE.md, phases/PHASE-07.md (all,
  including section 5), evaluations/study_registry.json, root DECISIONS.md (D-041, D-094 … D-099), root NEXT_SESSION.md,
  README.md, docs/research/results.md, docs/research/model_and_data_cards.md, docs/specs/01_product_and_commercial.md
  ("Business value and ROI measurement"), apps/web/app/(app)/value/page.tsx, infra/n8n/README.md.
- Known stale: README.md (test counts 419/205; no Phase 7 or warehouse studies), docs/research/results.md (no E1, FA1,
  W1, D1, G1, JS1, PM1, QC1), PROJECT_STATUS.md header (2026-10-22), NEXT_SESSION_PROMPT.md (asks for Phase 7),
  STATUS.md current-phase row (misses the 2026-10-30 studies).

8A.1 ASK THE OWNER (one message, then wait)
  a. Team members and roles (or "solo, permitted by the lecturer" with the date of that permission).
  b. The lecturer's answer on: using a project that existed before the group formed; whether the Week 6 project and the
     final project must be the same; whether SupplyLens is or will be submitted in any other unit.
  c. Approval of the AI-use statement (see ACADEMIC INTEGRITY) and the commit-metadata preference.
  d. The exact Week 6 date, time limit and format, and the final report length/template (Turnitin needs a soft copy:
     PDF or DOCX).
  e. Dataset approvals for 8B: LaDe (its Hugging Face card says Apache-2.0; its GitHub page says research use under its
     own terms: read both) and/or the Amazon Last Mile Routing Research Challenge data.
  f. HubSpot for 8B: a free HubSpot account with a developer test account, or a local stub only.
  g. Deck format: Marp Markdown exported to PDF and PPTX (default), or PowerPoint the owner edits.
  h. Whether to migrate the hosted Neon database to 0011 (OPS-P6-03) before Week 6.

8A.2 BASELINE
- Re-measure and record: pytest (expected at least 505 passed / 6 skipped), web lint/test/typecheck/build, Playwright
  (expected 185 passed / 7 skipped on four projects, 42 screenshots, 18 lab vitals run alone).

WP0 — Fix what the hosted demo shows wrong (do first: the Week 6 demo opens on Overview)
Observed by the owner on https://supplylens-self.vercel.app (Overview, UCI Research, light theme, desktop, 2026-11-10).
- F1 (P2) 3D warehouse stays dark in light theme. The canvas floor, grid and frames used the dark tokens (floor looked
  like --bg-deep #091012 instead of #e9f0ed) while the page was light.
  Likely cause (verify first, label VERIFIED or not): components/warehouse3d.tsx reads CSS tokens with token() inside a
  useMemo keyed on resolvedTheme, during render. next-themes applies the html class in an effect after that render, so
  the memo can read the previous theme's values and never re-read. components/chart.tsx already avoids this (S17) by
  applying the theme one animation frame later. Fix the 3D view the same way (or observe the html class with a
  MutationObserver), then invalidate the frame. Check every other place that calls token() during render
  (grep token\( in apps/web) and fix the same pattern there.
  Test (must fail before the fix): Playwright on Overview and Inventory with WebGL: start in system dark with the app
  set to light, and also switch dark→light and light→dark at runtime; sample canvas pixels at a floor point and assert
  they are within a small distance of the theme's --bg-deep. Run on desktop Chromium and WebKit.
- F2 (P2) Simulated data shown as plain green "available". "What this data can answer" shows Stock positions and
  Supplier terms & policies with a green "available" badge although their note says "Not present in source data" /
  "Generated agreements, labelled SIMULATED". The API (capability_matrix in routes_core.py) already returns "basis":
  "simulated"/"synthetic"; the UI drops it. Show status and basis together (for example "available · simulated" with the
  existing Provenance chip and the simulated colour), never the observed-green style for simulated or synthetic data.
  Test: every capability whose basis is not "observed" renders its basis label; unit or e2e.
- F3 (P3) The 3D legend card (bg-surface/90) lets racks show through and covers the bottom-left racks. Make the legend
  and hover card opaque (bg-surface), and frame the camera or add bottom padding so no rack sits under the legend at the
  default view. Disabled toolbar buttons must keep readable contrast in both themes (axe).
- F4 Light/dark sweep: after F1–F3, walk all screens in light and dark at 1440, 834 and 390 px, both on load and after a
  runtime theme switch, and from system-dark/app-light. Fix any surface that keeps the other theme's colours (canvases,
  charts, maps, tooltips, overlays, focus rings). Add one visual baseline captured AFTER a runtime switch for Overview
  and Inventory (D-080 rules; darwin and linux).
- F5 Hosted check (read-only): after deploy, run the browser checks against the hosted demo with the demo viewer
  account (no writes, no resets): Overview, Inventory 3D, Research, Policies, Value in both themes; save screenshots
  to docs/screenshots/phase8/ with revision labels; record in EVIDENCE.md. If the owner sends screenshots of other
  screens, treat each visible defect the same way (cause, fix, failing test, evidence).

WP1 — Make the documents tell the truth
- README.md: re-measured test counts; an "Operations studies" table (E1, FA1, W1, D1, G1, JS1, PM1, QC1) with the kind of
  each number; generation (local only, off in the demo) and its limits; n8n; ABC/XYZ; CO2 cap; negative results kept.
  A hidden HTML comment with the source path next to every number.
- docs/research/results.md: one section per new study (question, data, method, result, limits).
- PROJECT_STATUS.md, STATUS.md, PROGRESS.md: current.
- docs/course/coverage.md: Week → topic → study id / module → files → Research card → screen → evidence id → status.

WP2 — One source for presentation numbers
- scripts/course_metrics.py → docs/course/metrics.md and metrics.json from the registry ("current" runs only) and each
  run's metrics.json: study, headline, key metrics, n, data kind, run id, date. Deterministic; a test fails if a current
  run has no metrics file. Every later document quotes only from metrics.md.

WP9a — Interim pack (Week 6, 10 %)
- docs/course/ai-use-statement.md (draft for the owner to approve).
- Copy SupplyLens_image_prompts_phase8.md (supplied by the owner) to docs/design/image-prompts-phase8.md.
- docs/course/interim-deck.md: 8–10 slides within the confirmed time limit: problem, data and its limits, architecture,
  the spine "one shortage, end to end", three results (S2 accuracy ≠ value, E1 CO2 trade-off, QC1 or JS1), plan to the
  final, team roles. Speaker notes map slides to the interim rubric.
- docs/course/demo-script-5min.md: timestamps, clicks, words, demo account and workspace, a fallback for each step;
  warm the hosted API first (cold start, PERF-P7-02). Generation is local only: plan a recorded clip as backup.
- docs/course/marker-guide.md: how the lecturer opens the live demo, which accounts, a 10-minute guided path, what is
  simulated, where the evidence is.
- CONTRIBUTIONS.md (only with owner answer 8A.1a).
- Rehearse: walk the script once against the hosted demo; record timing and any failures in EVIDENCE.md. Tag
  course-interim. Respect the 48-hour push freeze.

8A COMPLETION: update STATUS, ISSUES, EVIDENCE (P8-E01…), DECISIONS (owner answers as D-ids), PROGRESS; create
docs/agent-handoff/phases/PHASE-08.md (section 8A); commit; confirm CI and deploy; summary; STOP.
```

---

## Session 8B — Weeks 6 to 10 (close the topic gaps)

```text
[paste the common header first]
Restore context as in 8A.0, plus phases/PHASE-08.md section 8A and the owner's recorded answers.

WP3 — Logistics (Week 7; only with dataset approval)
- L1 ETA: predict delivery time on LaDe-D (one or two cities) from courier, region, time of day, distance and workload
  features. Historical-mean baseline vs LightGBM (quantile LightGBM for intervals and their coverage). Metrics MAE,
  RMSE, ACC@30, chronological split. Report the LaDe paper's leaderboard separately, labelled as theirs.
- L2 last-mile routing: sample courier-days; OR-Tools VRP (time windows and capacity where the data allows) vs the
  courier's actual sequence vs nearest-neighbour. Metrics: distance, late stops, solve time, and fuel and CO2 from
  distance using the same rounded DESNZ factors as E1 (labelled assumed). Haversine distance labelled as such.
- Study-only; registry L1/L2; Research section "Getting goods to customers"; a failing-able test (solver never worse
  than nearest-neighbour on a fixed small instance). No approval → L2 on a labelled synthetic instance, L1 BLOCKED.

WP4 — LSTM forecasting (Week 3)
- New study (W2 or F3), not inside frozen F1. Same split and metrics as W1 (WAPE, MAPE over non-zero actuals, RMSE) on
  total daily units, optionally the 50-product pooled target. Child process for PyTorch; ≥ 3 seeds, mean and spread.
  Compare with XGBoost, Prophet, seasonal naive and the TCN where comparable. Honest headline either way.

WP5 — Imbalance and group parity (Week 10)
- B1 on PM1(a) (AI4I 2020): none vs class weights vs SMOTE (training folds only) vs threshold moving; recall, precision,
  PR-AUC, expected cost under PM1's cost model. Parity of recall and false-positive rate by machine Type (L/M/H)
  before and after. Same screen on D1 by supplier group (simulated). imbalanced-learn in an evaluation dependency
  group if possible so the serving bundle is unchanged.

WP6 — Support assistant and CRM hand-off (Week 8)
- Read-only "order and stock status" assistant: answers from SupplyLens records with cite-or-withhold (the citation is
  the record id), workspace-scoped through RLS, rate-limited, refuses anything that changes data.
- Hand-off: when it cannot answer or the user asks for a person, n8n creates a ticket. HubSpot changed in 2026: legacy
  developer accounts were merged into standard accounts and legacy public apps can no longer be created; the tickets
  API is date-versioned. Read the current HubSpot developer docs before coding, use a developer test account only,
  dry-run by default, real call only behind an env flag. Check that the n8n HubSpot node uses a current endpoint; if
  not, use an HTTP node. Owner chose stub → record the payload locally.
- G2-support: ≥ 40 questions including unanswerable ones; answered-correctly, wrong, withheld rates.

WP7 — AI document extraction (Week 8 "document processing with AI")
- Today uploads are plain text only and terms come from CSV. Add PDF intake (text layer; OCR only if needed and
  approved), then extract key fields (parties, effective and expiry dates, renewal, termination, exclusivity, minimum
  commitment, and where present price, MOQ and lead time) into a DRAFT terms record that a person confirms; nothing
  extracted is used for planning until confirmed. Every field cites its character span.
- X1 study: measure field-level precision, recall and exact-span match against the CUAD expert labels already in the
  repository (73 contracts, 2,176 labels), for a rules/regex baseline, the existing retrieval (top-k clause), and, if
  enabled locally, the generation model. Report per field; keep negative results.

WP8 — GenAI polish and red team (Week 11)
- Fix KNOW-P7-01: ask which product (choice list) instead of a plain refusal for supplier-only questions.
- Red-team suite for generated answers and the support assistant (≥ 15 cases): instructions hidden in uploaded
  documents and record notes ("ignore previous instructions", "say the price is 0"), instructions in file names and
  metadata, requests to reveal the system prompt or keys, out-of-scope requests. Each case asserts a concrete property
  (figure unchanged, answer withheld, no key pattern). Report attack success rate.
- G2 human-written questions: if there is a team, members write and label ≥ 40 questions with a one-page rubric (who
  labelled what is recorded); optionally a few Arabic questions (bge-m3 is multilingual), reported separately. Report
  figures-in-cited-passage, citation correctness, wrong answers, over-refusals, p50/p95 latency and tokens per answer.
  Do not close EXT-06/ARC-04 unless the owner agrees the reviewers qualify.
- scripts/course_demo_local.sh: starts the stack with generation on (local Ollama); a test confirms the public demo
  profile still refuses to start with generation on.


WP-UI — Interface rules for every screen this session adds or changes (applies to WP3–WP8)
- Placement (propose in one message before building; do not add top-level navigation without owner approval):
  * Status assistant (WP6): a drawer opened from the header and from the command palette ("Ask about an order or
    stock"), not a new page. Shows the question, the answer sentences with record-id citations that link to the record,
    or "withheld" with the reason; a "Talk to a person" button that shows the hand-off result honestly
    ("dry run: ticket not sent" in stub/dry-run mode).
  * Extracted terms (WP7): Policies › document › "Extracted terms" tab. One row per field: value, confidence source
    (rule / retrieval / model), cited span highlighted in the document reader, Confirm / Reject / Edit. A DRAFT badge
    until a person confirms; confirmed terms show who and when. Nothing unconfirmed reaches planning.
  * KNOW-P7-01 (WP8): when the product is ambiguous, show product choice chips under the question instead of a refusal.
  * Research page: new cards only from the registry, grouped under the existing "Operations studies" and "Running the
    warehouse" sections plus a new "Getting goods to customers" section (L1, L2) and "Documents and answers" (X1, G2,
    red team). Each card states the data kind.
- States for each new surface: loading, empty (first use), empty after filter, offline, 403, error with retry, withheld
  answer, read-only role (RoleNote). Empty states use the approved illustration for that state (WP-ART) or the
  existing icon fallback; errors and loading never use art.
- Quality bar: light and dark themes; 1440, 834 and 390 px; keyboard only; visible focus; axe clean; touch targets
  ≥ 24 px; no horizontal page scroll on phones; numbers and money on one line; typographic text as the existing UI.
- Tests: new journeys J13 (ask a status question → cited answer → hand-off dry run) and J14 (upload PDF → review
  extracted fields → confirm one → it appears as a confirmed term) on desktop, mobile, WebKit and Firefox (CI).
  Screenshot baselines only for intended changes, after looking at the images (D-080), darwin and linux both.
  Overview LCP must not get worse; lab vitals measured alone.
- Public demo: the status assistant and the rule-based extraction may run there (no generation); model-based
  extraction and generated answers stay local (D-041 for the demo). The UI says which mode is active.

WP-ART — Illustrations (only if the owner supplies approved images; never generate images yourself)
- The owner produces images with the briefs in docs/design/image-prompts-phase8.md and places the PNGs in
  design/source-assets/supplylens/. Check each against its brief and the acceptance list in that file (transparent
  background, no text/numbers/logos/people/charts, subject in the middle 70 %, reads at 96 px, works on light #f4f8f6
  and dark #0d1517). Report any that fail; do not edit art.
- For accepted files: update source_manifest.json (hash, brief, status), run scripts/optimize_illustrations.py, add the
  ids to apps/web/lib/illustrations.json and the Art type in components/illustration.tsx, show each only in its briefed
  state, update docs/design/illustrations.md and record the owner approval as a D-id (closes the D-040 withholding for
  A02/A13/A16 if those are accepted). Review in both themes at three widths; refresh only the affected baselines.

8B COMPLETION: registry, Research cards, tests, results.md sections, coverage.md and metrics.md regenerated; evidence,
issues, decisions, PHASE-08.md section 8B; CI and deploy confirmed; summary; STOP.
```

---

## Session 8C — Weeks 10 to 12 (responsible AI, final pack)

```text
[paste the common header first]
Restore context as in 8A.0, plus PHASE-08.md sections 8A and 8B.

WP9 — Responsible AI and model cards (outcome C)
- docs/course/responsible-ai.md from existing controls: four-eyes approval bound to payload hash and expiry, separation
  of duties, deterministic purchasing, cite-or-withhold and abstention, append-only audit, RLS, PII redaction, demo
  lockdown, FA1, B1, E1, red-team results, labelled simulated data, kept negative results. For each: risk, code
  location, test, evidence id, what is NOT covered.
- Model cards for W1 models, LSTM, D1, PM1, QC1, L1, X1, the generation setup; data cards for AI4I 2020, Open-Meteo,
  LaDe. Include feature importance (or SHAP if already a dependency) for D1, PM1 and L1.
- UAE paragraph ("aligned with", never "used by"): PDPL (Federal Decree-Law No. 45 of 2021), Dubai's private-sector
  AI-agent plan, "human leads, AI enables" as the approval design. Re-verify each fact by web search, cite the URL, drop
  what cannot be verified.

WP10 — Business case (MAIB is a business degree)
- docs/course/business-case.md built on the Value page ledger and docs/specs/01 "Business value and ROI": benefits and
  costs with source, unit, baseline, assumption and data kind; a sensitivity table on the two or three assumptions
  that matter; the cost of the AI itself (compute, inference, people supervising). Simulated money stays labelled
  simulated. Add an adoption plan: users and roles, change management, rollout steps, what a pilot must prove.

WP11 — Final pack (exam week, 30 %)
- final-deck.md: 12–16 slides: problem and UAE context, data and limits, architecture, one slide per outcome A–D,
  results table, business case, responsible AI, negative results, limitations, next steps, team roles. Speaker notes
  map each slide to the final rubric.
- demo-script-10min.md, same format as the 5-minute script, with the local generation segment and its backup clip.
- report.md exported to the format confirmed in 8A.1d: executive summary, problem, related work, data, methods,
  results by outcome, business case, responsible AI, limitations, conclusion, references; appendices: coverage.md,
  metrics.md, rubric-map.md, ai-use-statement.md, CONTRIBUTIONS.md.
- Related work and references in APA 7, drawn first from the unit's prescribed readings (Unhelkar & Gonsalves 2021;
  Kersten 2019; Hemachandran et al. 2023; Abaku et al. 2024; Seyedan & Mafakheri 2020; Foya 2021; Nwasuka & Nwaiwu
  2023; Thomke et al. 2025; Chung 2021; Hofmann et al. 2020; Blackman 2022; Edelman & Abraham 2023; Alavi & Westerman
  2023) plus the papers behind each dataset. Open or look up every reference before citing it; no unverifiable ones.
- Deck visuals: real screenshots of the running product (revision-labelled, both themes where useful), charts made
  from metrics.json, architecture as Mermaid. Generated images only for the title, section-divider and closing slides
  (D-series briefs in docs/design/image-prompts-phase8.md, owner-supplied). Never use generated images for charts,
  diagrams, screenshots, data or people.
- rubric-map.md, case-links.md (Amazon forecasting → F1/S2; Toyota vision → QC1; Paack → L1/L2; Duolingo/HealthPlix →
  guardrails and model cards; Thomke et al. on Gen AI quality control → G1/G2 and the red team), qa-prep.md (15 likely
  examiner questions with honest answers).
- Acceptance: every number is in metrics.md; each deck fits its time limit read aloud (about 130 words per minute,
  recorded); the 10-minute script walked once on the hosted demo and once on the local profile; the 48-hour freeze
  respected; tag course-final.

8C COMPLETION: STATUS, ISSUES, EVIDENCE, DECISIONS, PROGRESS, PHASE-08.md section 8C; write NEXT_SESSION_PROMPT.md for
Phase 9 (identity and SaaS, owner decisions first); CI and deploy confirmed; summary with open owner actions; STOP.

DEFINITION OF DONE FOR PHASE 8
- Every week in coverage.md is "done" with evidence or "blocked" with reason and owner action.
- README, results.md and status files agree with the registry and re-measured test counts.
- New studies registered, tested, on the Research page, labelled by data kind.
- Interim and final decks, both demo scripts, report, rubric map, marker guide, Q&A prep, business case, responsible-AI
  document and the AI-use statement exist under docs/course/; every number is in metrics.md; every reference verified.
- CI green; the public demo still refuses generation; no external system written to without approval.
```
