---
marp: true
theme: default
paginate: true
size: 16:9
title: SupplyLens — interim presentation (MAIB AI 218, Week 6)
footer: "SupplyLens · AI in Operations (MAIB AI 218) · AI use: docs/course/ai-use-statement.md"
style: |
  section { font-family: "Hanken Grotesk", "Helvetica Neue", Arial, sans-serif; color: #172b27; }
  section.cover { padding-right: 62%; }
  section.cover h1 { font-size: 1.9em; line-height: 1.1; }
  section.cover p { font-size: 0.8em; }
  h1, h2 { color: #0f6b55; }
  table { font-size: 0.7em; }
  blockquote { font-size: 0.6em; color: #4a5f5a; border-left: 4px solid #63c9a8; margin: 0 0 0.6em; padding-left: 0.6em; }
---

<!--
DRAFT for the owner and team (Phase 8, 8A WP9a, 2026-11-10). Not approved.
- Every number on a slide is copied from docs/course/metrics.md (generated from the study registry). Do not type a new
  number: regenerate metrics.md instead.
- Time limit, date and format of the Week 6 presentation are not known yet (open action 8A.1d). Read aloud at about
  130 words per minute and cut slides to fit once the limit is known.
- Images: only the title uses a generated illustration (D01). The closing illustration D06 is not used: the supplied
  file is truncated (owner to re-export). Charts, diagrams and screenshots are never generated.
- Export: npx @marp-team/marp-cli@4.5.1 docs/course/interim-deck.md --pdf --pptx --allow-local-files < /dev/null. The
  architecture diagram is an SVG rendered from images/architecture-interim.mmd.
-->

<!-- _class: cover -->
<!-- _paginate: false -->
![bg](images/deck-title.png)

# SupplyLens

Evidence-grounded inventory and procurement decisions

AI in Operations (MAIB AI 218) · Interim group presentation, Week 6

Krishna Mathur · Atharva Soundankar · Yash Petkar

<!--
Speaker notes (rubric: presentation skills). Introduce the team and the one-line promise: decide what to order, from
whom and why, and be able to prove it later. Who presents which slide: to be agreed by the team.
-->

---

## The problem: ordering decisions nobody can prove later

- A planner has to decide **what to order, from whom, and why**, under a budget, with supplier terms that change over time.
- Most tools give a number. They do not show **which forecast, which contract clause in force on that date, and which
  checks** the number came from, and they rarely stop a person from sending an order nobody approved.
- Operations KPIs at stake: **cost, service level and sustainability**, which pull against each other.

<!--
Rubric: content quality. Link to unit outcome A (optimise operations) and B (impact on the supply chain).
No numbers on this slide on purpose.
-->

---

## Data, and what it cannot tell us

| Source | What it is | Kind |
|---|---|---|
| UCI Online Retail II | Real sales of one online retailer (CC BY 4.0) | Observed |
| Stock, suppliers, agreements, costs | Generated, labelled **SIMULATED** in every screen | Simulated |
| CUAD, ACORD | Public contract clauses with expert labels | Human-labelled |
| AI4I 2020, generated images | Studies only (maintenance, inspection) | Published synthetic / simulated |

- The sales data has **no stock, no lead times and no lost sales**: every planning result is a simulation.
- No study measures a real business outcome yet.

<!--
Rubric: content quality. Say this before any result: it is the honest frame for everything after it.
-->

---

## Architecture

![w:1100](images/architecture-interim.svg)

<!--
Diagram: images/architecture-interim.svg is rendered from images/architecture-interim.mmd (Mermaid 10.9.1); it is
drawn from that source, not by hand and not generated as an image. Re-render after any change.
-->

Approvals are bound to the exact payload and expire; purchasing stays deterministic.

<!--
Rubric: application of techniques. Point at where AI sits (forecasting, retrieval, optional local cited answers) and
where it deliberately does not (the order itself is deterministic and approved by a person).
-->

---

## The spine: one shortage, end to end

1. **Forecast** shows a product will run short (Forecast lab).
2. **Exception** appears on Overview and Exceptions.
3. **Investigator** gathers stock, terms in force, open orders.
4. **Planner** (CP-SAT) proposes an order within budget and constraints.
5. **Evidence packet**: data cutoff, forecast version, cited clause, constraint checks.
6. **Approval** by a second person, bound to that exact plan.
7. **Order** sent to the sandbox ERP and **read back** before it counts as done.

<!--
Rubric: application of techniques and content quality. This is the live demo path (docs/course/demo-script-5min.md).
-->

---

## Result 1 — better accuracy did not mean better value (S2, exploratory)

> Data kind: simulation on real UCI demand and forecasts; assumed terms and costs. **Exploratory**: it reuses F1's last test window, so it is not confirmatory. Run S2-20261023T183015Z.

- **503** products, four weekly reviews. Forecast error (MAE): seasonal naive **21.0631**, LightGBM **15.4437**, TCN **14.9027** — the trained models are more accurate.
- Through the product's own ordering logic, no budget limit, total simulated cost: a base-stock rule with no forecast **£11,982.68**, seasonal naive **£12,957.35**, TCN **£13,672.77**, LightGBM **£19,842.31**.
- Registry headline: *Through the product's own ordering logic, lower forecast error did not mean lower simulated cost.*

<!--
Rubric: content quality and application of techniques (demand forecasting, Week 3; inventory, Week 4). The point the
brief asked for: accuracy is not value. Numbers from the exploratory section of metrics.md (D-109): say "exploratory"
aloud, as the slide does.
-->

---

## Result 2 — cost, service and CO2 (E1)

> Data kind: Simulation: real UCI scope; terms, stock, lanes, CO2 factors and unit weights assumed. Run E1-20261026T200641Z.

- Scope: **40** products, **23,980** units required, binding weekly budget.
- No CO2 cap: **4,565** units short. CO2 capped at **0.95** of that: **4,574** short — a small cut is almost free.
- Registry headline: *halving CO2 costs 13.8 points of coverage.*
- An evolutionary search (NSGA-II) reaches **0.9807–0.9849** of the exact front's hypervolume: close, but not exact.

<!--
Rubric: application of techniques (multi-objective optimisation, Week 2). Every number here is in metrics.md, E1.
-->

---

## Result 3 — visual inspection at goods-in (QC1)

> Data kind: Simulation: generated images, assumed costs. Run QC1-20261030T193358Z.

- **3,000** test images, **862** with a defect.
- A small CNN separates defects with AUC **0.9972**; hand-made features reach **0.9462**.
- Checking only what the CNN flags: recall **0.9872** (**11** escaped defects), cost **£419.40** against **£900.00** for
  inspecting everything.
- Generated images are easier than photographs: this is a method check, not a factory result.

<!--
Rubric: application of techniques (computer vision for quality control, Weeks 6 and 9). Numbers from metrics.md, QC1.
-->

---


## Plan to the final project

- Weeks 6 to 10: LSTM forecasting; class imbalance and group parity; ETA and last-mile routing (dataset approval
  pending); AI document extraction from contracts; an order and stock status assistant with a ticket hand-off;
  a red-team test of generated answers.
- Weeks 10 to 12: responsible-AI document and model cards, business case with a sensitivity table, final deck and
  report.
- Negative results are kept (for example: weather did not clearly improve the forecasts, W1).

<!--
Rubric: content quality. Plan comes from the Phase 8 brief (sessions 8B and 8C).
-->

---

<!-- _paginate: false -->

## Team

Krishna Mathur · Atharva Soundankar · Yash Petkar

Questions?

AI-use statement: `docs/course/ai-use-statement.md`

<!--
Rubric: team collaboration. Who did what is recorded in CONTRIBUTIONS.md once the team agrees it (names only for now).
Closing illustration D06 left out: the supplied file is truncated (owner to re-export).
-->
