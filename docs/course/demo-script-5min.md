# Five-minute live demo — Week 6 interim presentation (DRAFT)

> DRAFT for the team (Phase 8, 8A WP9a, 2026-11-10). Timings below are **planned**; the measured times of the hosted
> rehearsal are recorded in `docs/agent-handoff/EVIDENCE.md` (Phase 8). The Week 6 time limit is not known yet: cut
> step 7, then step 6, if the slot is shorter. Updated 2026-11-10 for the status assistant and Extracted terms (timings
> re-planned, not yet rehearsed). The live screens show live demo data: say "the headline count", do not
> read study numbers off the screen; study numbers are on the slides and come from `metrics.md`.

**Where:** https://supplylens-self.vercel.app (the public demo; generation is off there, D-041).
**Accounts:** the demo role accounts on the sign-in page are public and passwordless (D-050). Use **Planner** for steps
1–4, **Approver** for step 5, **Viewer** for steps 6–8. Approver must be a different person from the planner who drafted
(separation of duties), which is why the account changes.
**Workspaces:** *UCI Research* (real sales, simulated operations) for Overview and Research; *Demo* (fictional reference
case) for the order journey and the status assistant.

## Before you start (5 minutes ahead)

1. Open `https://supplylens-self.vercel.app/health` and wait for `ok`: the first request after idle starts the Python
   function and can take several seconds (PERF-P7-02).
2. Sign in once as Planner, open Overview, then Approvals in the Demo workspace, so both are warm.
3. Have the backup video ready (recorded walk of these steps, plus the local cited-answer segment): **owner to record**.
4. Close other tabs; set the browser zoom to 100 %; choose the theme you will present in before you start.

## Script

| Time (planned) | Screen and clicks | Words (short) | If it fails |
|---|---|---|---|
| 0:00–0:35 | Step 1: Overview, UCI Research, as Planner. Point at the headline, the provenance chips ("Simulated", "Derived"), the 3D schematic and "What this data can answer" | "One screen tells you what is at risk and what the data can and cannot answer. Stock here is simulated, and the screen says so: the sales are real, the stock is not." | Cold start: wait, then refresh once. 3D missing: the 2D floor plan shows the same records. |
| 0:35–1:05 | Step 2: Exceptions (left menu). Pick a shortage row → **Investigate** | "Exceptions are ranked by severity and value. We take one shortage end to end." | No shortage listed: switch to the Demo workspace, where the reference case is always ready. |
| 1:05–2:00 | Step 3: Investigations, Demo workspace: **Start investigation** for the reference case, then **Review** the result | "The investigator gathers stock, open orders and the supplier terms in force, and the planner proposes an order inside the budget. Every number in this packet has a source: data cutoff, forecast version, the cited clause, the checks." | Run slow: say what it is doing; show an earlier run from the list. |
| 2:00–2:45 | Step 4: Policies & evidence: open the cited clause (**Open at passage**); point at *Known by* and *In force on*. Then the **Extracted terms** tab → **Show in text** on the minimum order quantity | "Two clocks: what we knew by the decision date, and which version was in force. The extracted terms are read by fixed rules and stay a draft: nothing here is used for planning until a person confirms it." | Passage not opening: show the version list and **Compare versions**. No terms listed: say the rules found none in that version and move on. |
| 2:45–3:40 | Sign out → **Approver**. Step 5: Approvals, Demo: open the draft, check the exact payload, **Approve** (the button shows the total); the order goes to the sandbox ERP and is read back (**Reconcile with sandbox** if it waits) | "A second person approves this exact payload; if anything changed, the approval would not hold. The order counts as done only after it is read back from the ERP — here a local sandbox, no real ERP is connected." | Nothing to approve: the demo releases untouched orders hourly; show the approved history instead. |
| 3:40–4:15 | Sign out → **Viewer**. Step 6: Demo workspace, header button **Ask about an order or stock** (or ⌘K). Ask `stock of DEMO-SKU-001`, then `cancel the order for DEMO-SKU-001` | "A support assistant that only reads: every sentence links to the record it came from, and it refuses to change anything. 'Talk to a person' would open a HubSpot ticket; on the demo it is a dry run." | No answer: name a product code from the Inventory table. Drawer stuck: Esc, then the ⌘K entry. |
| 4:15–4:45 | Step 7: Research, UCI Research: the **On this page** menu → *Moving goods* and *Documents and answers*; point at a card's course week and data kind | "One study per course topic. Every result says what kind of number it is; most are simulations, and we keep the negative results." | Cards slow: open `docs/course/metrics.md` from the repository instead. |
| 4:45–5:00 | Step 8: Close on the last slide | "Real sales, simulated operations, and a person approves every order. Our AI-use statement is in the report." | — |

## Local-only segment (not in the hosted demo)

Generated answers that cite or withhold run only on a local machine with a local model (D-094, `SUPPLYLENS_GENERATION_ENABLED`).
Show them only from the **recorded clip** (owner to record on the local profile) or skip them in Week 6.

## Accessibility and fallback

- Keyboard path works throughout (Tab, Enter, arrow keys in the theme switch); say so if asked.
- If the hosted demo is down: play the backup video; do not start a local stack in the slot.

---

AI use: see [`ai-use-statement.md`](ai-use-statement.md) (draft awaiting the owner's approval).
