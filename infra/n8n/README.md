# n8n agent: shortage to draft purchase order

`supplylens-shortage-to-draft.json` is an n8n workflow (tested with n8n 2.43.4) that turns SupplyLens exceptions into
draft purchase orders for a person to approve:

```
Every 15 minutes / Run now → Settings → Sign in → Session → Read exceptions → Read open drafts → Pick shortages
  → Prepare draft order (POST /api/v1/agent-runs, mode "draft", Idempotency-Key) → wait → Read the run → Notify
```

- **Pick shortages** keeps shortage exceptions of the chosen severity (`severities`, default `['high']`) for products
  that are not already in a draft awaiting approval, largest money at risk first, at most `max_skus` (3). With nothing
  to do the workflow stops without calling the investigator.
- **Prepare draft order** asks SupplyLens' deterministic investigator to forecast, check the supplier terms in force and
  optimise a draft. The idempotency key is per hour and product set, so a retried step cannot start a second run.
- **Notify** builds the message a team channel would receive (replace the Code node with a Slack, Teams or email node).

## What n8n cannot do
The workflow signs in as a **planner**. A planner can prepare drafts but cannot approve or send them: approval is a
different person in SupplyLens, bound to the exact payload, and only an approved order reaches the purchasing system
(D-012, D-074). n8n never holds approver rights and never talks to the purchasing system.

## Run it locally
```
npm install --prefix ~/n8n n8n@2.43.4
export N8N_USER_FOLDER=~/n8n/home
~/n8n/node_modules/.bin/n8n import:workflow --input=infra/n8n/supplylens-shortage-to-draft.json
~/n8n/node_modules/.bin/n8n execute --id=SLshortage2draft          # or open http://localhost:5678 and press "Run now"
```
Edit the **Settings** node for your stack (base URL, workspace, account). The **Sign in** step uses the local development
sign-in; a deployed stack signs in through its identity provider instead, with a planner service account.

## Verified (2026-10-27, local CI-equivalent stack)
Run 1: drafted SYN001, SYN009, SYN029 → run status WAITING_FOR_APPROVAL, one draft order. Run 2: skipped those three and
drafted SYN002, SYN022, SYN030 (the test copy accepted medium severity; the fixture has no high-severity shortage).
