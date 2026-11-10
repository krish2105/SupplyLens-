# Case links: the unit's cases and demos → SupplyLens

How each case, article and demo named in the unit outline (section 2.4, class activities; see
[`outline-check.md`](outline-check.md) section 5) connects to the group project. Each case was looked up on 2026-11-10;
its full APA 7 reference and where it was checked are in [`references.md`](references.md). The "About" lines are our
own short summaries of the publisher's public abstract or summary only: we have not read the cases themselves, and
nothing here goes beyond what the abstract says. This page does not answer any case question, lab or exercise.

Study ids are those in [`metrics.md`](metrics.md) (registry reviewed 2026-11-10). No numbers are quoted here; any number
used in a deck comes from `metrics.md` with its data kind. Status of each study id:

- **registered**: in `metrics.md` today: AGT, AS1 (status assistant), B1 (bias mitigation), C1, D1, E1, ET1 (arrival
  times), F1, FA1, FE1 (fuel), G1, IB, JS1, PM1, QC1, R1, R2, R3, RED1 (red team), RT1 (last-mile routes), W1, W2 (LSTM),
  X1 (contract-term extraction); F2 and S2 are registered as **exploratory** and may only be quoted with that word. FE1,
  ET1 and RT1 run on simulated data because no logistics dataset has been approved.
- **drafts**: the model cards (`docs/research/model_and_data_cards.md`) and the responsible-AI document
  ([`responsible-ai.md`](responsible-ai.md)), for the team to review.
- **planned**: G2 (human-written questions, WP8): they must be written by people.

## Summary

| Week | Case or demo | Verified as | SupplyLens parts | Biggest difference |
|---|---|---|---|---|
| 2 | AI in SCM demo (Dubai RTA) | demo only; no published material identified | E1, D1, PM1, FE1 | no RTA data or link of any kind |
| 4 | Mobile-clinic inventory | SMU024, Singapore Management University | inventory classes and safety stock, IB, S2 (exploratory) | a real clinic pharmacy vs retail sales with simulated stock |
| 5 | Gupta Furniture | W30149, Ivey Publishing | JS1, F1, the CP-SAT planner behind E1 | medium-term aggregate plan vs a one-shift schedule |
| 6 | Thomke et al., Gen AI quality control | R2505E, Harvard Business Review | G1, R3, G2 (planned), RED1 (red team), AGT | live experiments on sales vs offline checks on generated labels |
| 7 | Paack | IES914, IESE | ET1, RT1 (new), FE1, D1, E1 | a real, scaling delivery firm vs generated deliveries and routes |
| 8 | "What gets measured, AI will automate" | H08SHM, HBR digital article | C1, R3, X1 and AS1, AGT | an argument about jobs vs measured tasks with people kept in charge |
| 9 | Amazon demand-forecasting demo | demo only; no published material identified | F1, S2 (exploratory), W1, W2 (new) | one retailer's history vs Amazon scale |
| 9 | Toyota-style vision QC | the week 9 lab topic, not a case | QC1 | generated images vs real production images |
| 9 | Duolingo | 825097, Harvard Business School | guardrails, model cards (draft), G1, S2 (exploratory) | consumer product with real users vs offline studies |
| 9 | HealthPlix | NTU329, Asian Business Case Centre (NTU) | guardrails, human approval, X1, model cards | clinical decisions and adoption evidence we do not have |
| 10 | Blackman, AI ethics committee | R2204J, Harvard Business Review | FA1, B1, responsible-AI document (draft) | a standing committee vs a student team's review |
| 10 | Blackman & Ammanath, 3 conversations | H06VL0, HBR digital article | responsible-AI document (draft), FA1, B1 | an organisation's process vs a project document |
| 11 | Alavi & Westerman, knowledge work | H07UOW, HBR digital article | G1, R2, R3, AGT, AS1, G2 (planned) | work redesign and productivity vs answer faithfulness |

## Week 2 — AI in supply chain management demo (Dubai RTA)

- **Verified as**: the outline names only "AI in SCM demo (Dubai RTA)". It gives no title, publisher or product
  number, and we did not identify the demo material, so nothing is cited and nothing is claimed about RTA.
- **About**: abstract not public; no link.
- **SupplyLens parts**: E1 (cost, coverage and CO2 trade-off; simulation), D1 (late-delivery risk; simulation), PM1
  (breakdown prediction; AI4I 2020 benchmark and a simulated fleet), FE1 (fuel-inefficient trips; simulation, new and
  registered).
- **Comparable**: the week's lab themes (multi-objective optimisation; delay, breakdown and fuel risk) are the same
  questions E1, D1, PM1 and FE1 ask.
- **Not comparable**: SupplyLens has no RTA data and no connection to RTA. Any UAE framing in the report says "aligned
  with", never "used by" (brief, 8C WP9).

## Week 4 — Stock-up vs stock-out: the inventory management dilemma at a mobile clinic

- **Verified as**: Zeller, Wee & Cheah (2022), *Stock-up vs stock-out: The inventory management dilemma at a mobile
  clinic*, Singapore Management University, SMU024 (distributed by Harvard Business Publishing and Ivey).
- **About**: a mobile clinic's doctor wants common medicines always on hand while its procurement manager wants lower
  holding costs. Students compare continuous- and periodic-review systems and set reorder and order-up-to levels to
  balance service against cost.
- **SupplyLens parts**: ABC/XYZ classes, safety stock (z·σ·√L) and the cost-of-service curve on the Inventory screen;
  IB (SupplyLens policy on InventoryBench; published benchmark); S2 (exploratory: lower forecast error did not mean
  lower simulated cost).
- **Comparable**: the same trade-off between service level and holding cost, and the same reorder-point and safety-stock
  arithmetic.
- **Not comparable**: the case is a real clinic pharmacy where a stock-out keeps a patient waiting; our demand is one
  online retailer's sales history (UCI) with simulated stock and assumed costs. We have not checked our ordering logic
  against the case's continuous-versus-periodic comparison.

## Week 5 — Gupta Furniture: demand fulfillment and cost efficiency through aggregate planning

- **Verified as**: Sharma (2024), *Gupta Furniture: Demand fulfillment and cost efficiency through aggregate
  planning*, Ivey Publishing, W30149.
- **About**: a production supervisor must choose how to make the firm's best-selling office chair so that a demand
  forecast is met at the lowest total cost. The plan covers roughly 9 to 15 months and trades off inventory, regular and
  overtime work, subcontracting and staffing.
- **SupplyLens parts**: JS1 (receiving-floor job shop: exact CP-SAT against dispatch rules, with the ft06 check;
  simulation); F1 (the demand forecast a plan would start from); the CP-SAT purchasing planner behind E1 (a
  cost-minimising plan under a budget).
- **Comparable**: choosing a plan by optimisation instead of a simple rule, and showing how much the simple rule costs.
- **Not comparable**: aggregate planning is a medium-term production and workforce plan; JS1 is a one-shift schedule
  for goods arriving at a warehouse, and SupplyLens plans purchases, not production or staffing. Aggregate planning is a
  gap, not something the project covers.

## Week 6 — Thomke, Eisenhauer & Sahni, "Addressing Gen AI's quality-control problem"

- **Verified as**: Thomke, Eisenhauer & Sahni (2025), *Harvard Business Review*, September–October 2025, R2505E (a
  week 6 reading). It is about Amazon's product-catalogue system, not the week 9 forecasting demo.
- **About**: generative AI invents or drops content and produces too many options to judge, while human review and
  standalone test tools are costly and see only a sample. The authors describe how Amazon's Catalog AI blocks
  unreliable data, tests new product-page ideas and improves from those checks.
- **SupplyLens parts**: G1 (every generated answer checked for figures in a cited passage and correct citations; offline
  evaluation with generated labels); R3 (answer-support rules that withhold); G2 (planned human-written questions); the
  red team RED1; AGT (an investigator agent checked by an oracle on frozen scenarios).
- **Comparable**: automatic checks on every answer instead of human spot checks, and withholding an answer rather than
  publishing an unchecked one.
- **Not comparable**: Amazon tests generated content on live traffic and can measure business effect; we have no live
  users, our G1 labels are generated rather than human-written, and the model is a small local one that is off in the
  public demo. We measure faithfulness to sources, not sales.

## Week 7 — Paack: harnessing data in the logistics industry

- **Verified as**: Zamora, Valor Sabatier & Sastre Boquet (2022), *Paack: Harnessing data in the logistics industry*,
  IESE, IES914.
- **About**: in early 2021 a fast-growing parcel-delivery company that lets shoppers choose their delivery slot faces
  rising operational complexity. The case looks at the role of data, its governance and digitalisation, and whether the
  firm can stay flexible as it scales.
- **SupplyLens parts**: ET1 (delivery-time prediction) and RT1 (last-mile routing with van capacity and delivery
  windows), both new and on simulated data; FE1 (fuel-inefficient trips; simulation); D1 (late-delivery risk;
  simulation); E1's assumed CO2 factors. The week 7 fleet predictive-maintenance demo links to PM1.
- **Comparable**: customer-chosen delivery windows are the constraint RT1 plans around, and failed or late deliveries
  are what ET1 and D1 try to predict.
- **Not comparable**: Paack's data is real and growing; ours is generated from a stated process because no logistics
  dataset (LaDe, Amazon Last Mile) has been approved, so ET1 and RT1 are method checks. The case is mainly about data
  strategy and governance, which SupplyLens touches only through its audit trail and per-workspace access rules.

## Week 8 — Catalini, Wu & Zhang, "What gets measured, AI will automate"

- **Verified as**: Catalini, Wu & Zhang (2025), *Harvard Business Review* digital article, 19 June 2025, H08SHM (the
  outline calls it the week 8 case).
- **About**: the authors argue that today's AI is already enough to disrupt many creative, analytical and professional
  fields, because any task that can be turned into data becomes open to automation. Leaders should therefore invest in
  what is hard to measure.
- **SupplyLens parts**: C1 (clause retrieval against CUAD expert labels; human-labelled), R3, X1 (extraction of
  contract fields into a draft a person confirms; confirming is not built), AS1 (status assistant), AGT, and the planner-only n8n agent.
  The week 8 document-processing demo links to the document upload and X1.
- **Comparable**: SupplyLens automates the measurable steps (finding a clause, drafting extracted terms, answering a
  status question) and measures each against labels.
- **Not comparable**: the article is an argument about whole occupations; we measure single tasks. By design the
  judgement steps stay with people: purchases need approval, and extracted terms are not used until a person confirms
  them.

## Week 9 — Amazon demand-forecasting demo

- **Verified as**: the outline names only "Amazon demand-forecasting demo"; no title, publisher or product number, and
  we did not identify the material, so nothing is cited.
- **About**: abstract not public; no link.
- **SupplyLens parts**: F1 (LightGBM and TCN against seasonal naive; historical backtest on UCI sales); S2
  (exploratory: forecast accuracy against simulated cost); W1 (Prophet, XGBoost, weather); W2 (LSTM, new).
- **Comparable**: daily demand forecasts judged against a naive baseline, with intervals, and the question of whether a
  better forecast actually lowers cost.
- **Not comparable**: one online retailer's past sales, a few hundred products, against Amazon's scale and data; F1 is
  not an untouched holdout, and S2 is exploratory.

## Week 9 — Toyota-style vision quality control

- **Verified as**: in the outline this is the week 9 **lab** ("defect vs non-defect CNN, Toyota-style vision QC"), not a
  case; no published source is named, so nothing is cited. Labs are not done in the project.
- **About**: abstract not public; no link.
- **SupplyLens parts**: QC1 (a small CNN against hand-made features, and a policy of inspecting only what it flags;
  simulation with generated images).
- **Comparable**: the same task (defect or not) and the same business question (what to inspect).
- **Not comparable**: QC1 images are generated, and the setting is goods-in at a warehouse, not a production line. No
  Toyota data or method is used.

## Week 9 — Duolingo: on a "streak"

- **Verified as**: Rayport, Keller & Luo (2025), *Duolingo: On a "streak"*, Harvard Business School, 825097.
- **About**: Duolingo's co-founder and CTO looks back at the end of 2024 on how gamification, adaptive AI and the streak
  feature drove growth. The case asks whether generative AI should take the app into new subjects, which ones, how fast,
  and with what risks.
- **SupplyLens parts**: guardrails (cite-or-withhold answers, the public demo with generation off), model cards
  (draft), G1; S2 (exploratory) for the point that the metric a system optimises must match the outcome that
  matters.
- **Comparable**: deciding where generative AI can be trusted, and keeping product metrics tied to real outcomes.
- **Not comparable**: a consumer app with real users and engagement data, and a strategy question about expansion;
  SupplyLens is an operations tool with no real users, and every number it has is offline or simulated.

## Week 9 — Rx:AI, putting machine learning into medical prescription: the case of HealthPlix

- **Verified as**: Shao et al. (2022), Asian Business Case Centre, Nanyang Technological University, NTU329 (the author
  list differs between distributors; see `references.md`).
- **About**: the case asks why health technology is slow to be adopted in developing countries, using India and
  HealthPlix's effort to get doctors to use AI tools. Executives' discussions let students weigh ways past the adoption
  barriers.
- **SupplyLens parts**: guardrails and abstention (G1, R3); human approval before anything changes (purchases need a
  second person; extracted terms stay a draft until confirmed, X1); model cards (draft); the adoption plan in
  the business case (planned, 8C WP10).
- **Comparable**: AI as decision support where a professional keeps the decision, and adoption as the hard part.
- **Not comparable**: prescribing carries patient-safety and medical-regulation stakes that purchasing does not; we have
  no clinical data and no adoption evidence at all, which a pilot would have to provide.

## Week 10 — Blackman, "Why you need an AI ethics committee"

- **Verified as**: Blackman (2022), *Harvard Business Review*, July–August 2022, R2204J.
- **About**: AI can harm people at scale through bias, privacy breaches and unsafe failures, often because of the data
  or the goal it was given, and a purely technical fix is not enough. The article recommends a committee of ethicists,
  lawyers, technologists, strategists and bias experts to review every AI system a firm builds or buys.
- **SupplyLens parts**: FA1 (reweighing a binding allocation across customer groups; simulation), B1 (new: SMOTE, class
  weights, threshold moving and adversarial debiasing, with group parity), the responsible-AI document (draft), and
  the approval controls.
- **Comparable**: reviewing each model's risks before use, and measuring a group gap and what it costs to close it.
- **Not comparable**: we have no committee. FA1's groups are customer regions in a simulated allocation and B1's are
  machine types in a synthetic dataset, so these show the methods; they are not fairness findings about people.

## Week 10 — Blackman & Ammanath, "Ethics and AI: 3 conversations companies need to have"

- **Verified as**: Blackman & Ammanath (2022), *Harvard Business Review* digital article, 21 March 2022, H06VL0 (the
  outline credits Blackman alone).
- **About**: firms agree on the AI harms to avoid but struggle to act on them. The authors advise deciding who should
  take part, setting ethical standards, finding the gaps against them and their root causes, and then putting fixes in
  place.
- **SupplyLens parts**: the responsible-AI document (draft), which lists for each control the risk, code, test, evidence
  and what is not covered (a gap analysis in the same spirit); FA1; B1; team roles in CONTRIBUTIONS.md.
- **Comparable**: stating standards and then the gaps against them, in writing.
- **Not comparable**: the article addresses an organisation with stakeholders; ours is a student project's document
  with no organisation behind it.

## Week 11 — Alavi & Westerman, "How generative AI will transform knowledge work"

- **Verified as**: Alavi & Westerman (2023), *Harvard Business Review* digital article, 7 November 2023, H07UOW.
- **About**: generative AI can greatly help knowledge work if it is applied with care, and managers can take steps so
  that employees get the benefit. New tools are arriving quickly and firms in professional services, healthcare and
  finance are investing heavily.
- **SupplyLens parts**: G1 (cited generated answers, local model), R2 and R3 (retrieval and answer support), AGT, the
  planner-only n8n agent, AS1, and G2 (planned).
- **Comparable**: generation that supports a planner's work (answers cite the agreement, the agent investigates) while
  the planner decides.
- **Not comparable**: we measure answer faithfulness offline; we have no study of how anyone's work or productivity
  changes.

## Other demos named in the outline

The outline also names an inventory demo (week 4), an AI-scheduler demo (week 5), a fleet predictive-maintenance demo
(week 7), a document-processing demo (week 8), a strategy video (week 10) and a GenAI demo (week 11). None has a title,
publisher or product number in the outline, so none is cited. Their project counterparts are, in order: the Inventory
screen and IB; JS1; PM1; the document upload, C1 and X1; FA1 and B1; G1 and AGT.

---

AI use: see [`ai-use-statement.md`](ai-use-statement.md) (draft awaiting the owner's approval).
