# Marker guide: how to open and assess SupplyLens (DRAFT)

> DRAFT for the owner (Phase 8, 8A WP9a, 2026-11-10). For the lecturer and any examiner of the MAIB unit *AI in
> Operations* (MAIB AI 218). The lecturer's answers on reusing a project that existed before the group formed, and on
> how AI use must be acknowledged, are still open: this guide makes no claim about them.

## Open the live demo

1. Go to **https://supplylens-self.vercel.app**. The first request after a quiet period can take several seconds while
   the server starts.
2. On the sign-in page choose a **demo role account**. They are public and need no password; each has the rights its
   name says:
   - **Viewer** — reads dashboards, forecasts and evidence.
   - **Planner** — runs forecasts, scenarios and investigations; prepares purchase-order drafts.
   - **Approver** — reviews evidence packets and approves or rejects drafts.
   - **Tenant admin** — administration screens (in the public demo, administration that changes data is refused).
3. Pick a workspace at the top: **UCI Research** (real sales of one online retailer, simulated operations),
   **Contract research** (public contracts and procurement awards) or **Demo** (a fictional reference case).

Nothing you do can harm the demo: administration, imports, exports and deletion are refused in the public demo, and
orders go only to a local sandbox ERP adapter (no real ERP is connected).

## A ten-minute guided path

| Minutes | Where | What to look for |
|---|---|---|
| 0–2 | Overview (UCI Research, Viewer) | The headline at-risk count, provenance chips (observed, simulated, derived), the 3D schematic and its 2D floor plan, "What this data can answer" with the basis of each capability |
| 2–4 | Exceptions → Investigations (Planner, Demo) | A shortage taken end to end: the investigator's evidence packet (data cutoff, forecast version, cited clause, checks) |
| 4–5 | Policies & evidence | The cited clause and the two dates: *known by* and *in force on* |
| 5–7 | Approvals (Approver, Demo) | Approval bound to the exact payload; the order is read back before it counts as done |
| 7–9 | Research (Viewer, UCI Research) | The section menu at the top; each card's study id, course week and data kind; "Moving goods" (FE1, ET1, RT1) and "Documents and answers" (X1, AS1, RED1); negative results kept |
| 9–10 | Header: *Ask about an order or stock*; Policies › a document › *Extracted terms* | The status assistant answers only from cited records and refuses changes; "Talk to a person" is a dry run. Extracted terms are a DRAFT with "Show in text" |

## What is simulated, and what is not in the demo

- **Simulated:** stock, suppliers, supplier agreements, costs, the delivery history in D1, the motor fleet in PM1, the
  goods-in images in QC1, routes and handling times in JS1, the trips in FE1, the deliveries in ET1 and the delivery days
  in RT1. They are labelled in every screen.
- **Real:** the UCI Online Retail II sales; public contract corpora (CUAD, ACORD) and World Bank awards; AI4I 2020 (a
  published synthetic dataset).
- **Not in the public demo:** trained forecasting models (the demo uses the seasonal-naive baseline and says so), the
  embedding server (retrieval runs lexical-only and says so), and generated answers (local only, off in the demo).
- **No real business outcome** has been measured yet.

## Where the evidence is

| What | Where |
|---|---|
| Every presentation number, with its source field and data kind | [`docs/course/metrics.md`](metrics.md) |
| Course week → study → screen → evidence | [`docs/course/coverage.md`](coverage.md) |
| Study questions, methods, results and limits | [`docs/research/results.md`](../research/results.md) |
| Reviewed headline and status of every run (superseded runs kept with a reason) | `evaluations/study_registry.json` |
| Commands run and their results, per phase | [`docs/agent-handoff/EVIDENCE.md`](../agent-handoff/EVIDENCE.md) |
| Decisions and their reasons | `DECISIONS.md` |
| AI tools used to produce the work | [`docs/course/ai-use-statement.md`](ai-use-statement.md) |

---

AI use: see [`ai-use-statement.md`](ai-use-statement.md) (draft awaiting the owner's approval).
