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

# n8n workflow: support hand-off to a HubSpot ticket (Phase 8 WP6)

`supplylens-support-handoff.json` (inactive by default) is the n8n route for the status assistant's "Talk to a person":

```
Hand-off received (webhook, header secret) → Check the payload → Create HubSpot ticket → Reply with the ticket id
```

- SupplyLens does **not** call this workflow. `POST /api/v1/assistant/handoff` returns a dry-run ticket payload (and
  records it in the audit log) unless HubSpot is switched on in the API itself (`SUPPLYLENS_HUBSPOT_ENABLED=true` and
  `HUBSPOT_ACCESS_TOKEN`, never in the public demo). A team that prefers n8n to hold the HubSpot key sends that payload
  to this webhook instead.
- **Check the payload** accepts only a SupplyLens hand-off (subject starting "SupplyLens: ", a pipeline stage) and passes
  on only the ticket fields `subject`, `content`, `hs_pipeline`, `hs_pipeline_stage` and `hs_ticket_priority`, so the
  webhook cannot be used to write other HubSpot objects.
- **Create HubSpot ticket** posts to `https://api.hubapi.com/crm/objects/2026-09/tickets` (HubSpot's date-versioned CRM
  path; check the version before enabling). Both credentials are placeholders to create in n8n: a header secret for the
  webhook and an `Authorization: Bearer …` header with a HubSpot service key that has `crm.objects.tickets.write`.
  No key is in this repository.
- Use a HubSpot test account first, as the project rules require for external services. Not run against HubSpot in
  this repository: the JSON was checked for structure only.
