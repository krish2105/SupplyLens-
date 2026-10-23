# Service management: incidents, support, onboarding, releases

Written in Phase 6 (2026-10-24) as the procedures an operator follows. **Nobody is on call today**, and there is no
paging integration, status page or support desk: those need an owner decision and staff (P1-OPS-01, EXT-10). Where a step
needs one of them, it says so.

## 1. Incident classification

| Severity | Definition (any one) | Examples | Response target* | Update cadence |
|---|---|---|---|---|
| **SEV1** | Wrong or duplicate external commitments possible; data of one workspace visible to another; data loss; whole service down | Two ERP orders for one action; cross-tenant read; database lost; API 5xx for all users | Acknowledge 15 min, mitigate 60 min | every 30 min |
| **SEV2** | Orders cannot be placed or reconciled; a workspace cannot plan; recovery objective at risk | ERP connector `UNAVAILABLE` > 30 min or `CREDENTIALS_INVALID`; worker stopped; `UNKNOWN_OUTCOME` older than 4 h; WAL archiving failing | Acknowledge 30 min, mitigate 4 h | every 2 h |
| **SEV3** | Degraded but workable; one exception | One read-back mismatch; one receipt exception; overdue receipts; slow pages | Next business day | daily |
| **SEV4** | Cosmetic or question | Label wording; how-to | Backlog | — |

\* Proposed targets. They mean nothing until someone is on call.

Detection sources, all available today: `GET /api/v1/ops/health` (status `failing` → SEV1/2 candidate), Exceptions
inbox alerts (with the webhook configured, alerts reach a chat or paging tool), `/metrics` (queue depth, oldest queued
job, database pool, `db_unavailable_total`), the daily reconciliation check (runbook).

## 2. Incident response

1. **Declare**: open an incident record (date, severity, reporter, symptom, affected workspaces). Template:
   `incident-YYYYMMDD-<slug>.md` in the operator's incident log, outside this repository if it holds customer data.
2. **Contain before you fix**, choosing the step that cannot make it worse:
   * Suspected duplicate or wrong orders → pause dispatch for the workspace. Stop the worker; on serverless hosting,
     ask approvers to stop approving. Do not retry or resend anything.
   * Suspected cross-tenant exposure → take the API down (SEV1); preserve the logs.
   * ERP outage → nothing to do: the circuit breaker pauses dispatch (runbook *ERP connector*).
3. **Diagnose** with `ops/health`, `ops/reconciliation`, the audit trail (`GET /api/v1/admin/audit.csv`) and traces.
4. **Recover**: runbook procedures (unknown outcome, connector, worker, database restore). After any database restore,
   **reconcile every order that is not `RECONCILED` against the ERP** before allowing new approvals.
5. **Close** when `ops/health` is `ok` and no order is unaccounted for. Within 5 business days, write a review covering
   cause, timeline, impact (orders, workspaces, money), and actions with owners. The review is blameless.

## 3. Support and escalation

| Tier | Who | Handles | Escalates when |
|---|---|---|---|
| 0 | Workspace administrator (customer) | Members and roles, imports, Test ERP connection, re-running a stale draft | the product misbehaves or the ERP integration fails |
| 1 | SupplyLens operator | Runbook procedures, reconciliation, alerts, restarts | code defect, data repair, SEV1/SEV2 |
| 2 | Engineering | Defects, data repair through audited scripts, releases and rollbacks | ERP-side problems → customer's ERP owner |
| ERP owner (customer) | Named in the onboarding record | Credentials, ERP outages, ERP-side order corrections | — |

Rules: never change order or ledger rows by hand in the database; every correction goes through an audited path
(reconcile, accept remote order, cancel order, record receipt, cancel open units). Customer data in tickets: references
only (action id, PO number), no exports.

## 4. Customer onboarding

1. **Agreement and scope** (owner): workspace kind, data to load, ERP in scope or not. ERP qualification follows
   `docs/operations/erp-integration.md` and is a separate milestone.
2. **Workspace and people**: create the workspace from **Import data / new workspace** (stock, sales and terms CSV
   templates with validation and quarantine, D-038). Add members in Administration with the least role. Approvers must
   be different people from planners (separation of duties is enforced). Corporate sign-in is P1-IAM-01 (not ready).
3. **Data check**: publish only batches whose quarantine report has been read; record the batch hashes (shown in Data
   admission) in the onboarding record.
4. **Alerts**: set the alert webhook to the customer's channel; agree who acknowledges what (§3).
5. **Dry run**: one investigation through to an approved draft on the customer's data, with the sandbox adapter. The
   order goes to the simulator, never a real ERP.
6. **Go-live checklist**: `ops/health` ok; daily reconciliation owner named; escalation contacts recorded; backup and
   restore drill (`scripts/recovery_drill.sh`) passed on the hosting platform within the last 30 days.

## 5. Release and rollback

Release (today, `main` → Vercel):
1. Locally: ruff, pytest (including the lexical-only run, `SUPPLYLENS_OLLAMA_URL=http://127.0.0.1:9`), contract check, web
   lint/types/build, browser suites, and `build_api.py --pin` when backend code changed.
2. Push to `main`; CI must be green on the required checks (lint, secrets, backend, contracts-and-web). Read e2e and
   the screenshot regression too, even though they are not required.
3. A schema change also needs the hosted migration (PD-009: temporary setup token → `/setup/schema` → remove token →
   redeploy). New code must keep working on the previous schema until then (as `integrations/schema.py` does for 0011).
4. Verify the live service read-only: `/health`, sign-in, the changed screen.

Rollback:
* **Application**: redeploy the previous good commit (`git revert` and push), or promote the previous deployment in
  Vercel. The second is a Vercel feature that has **not** been rehearsed for this project.
* **Schema**: prefer rolling forward. Downgrades exist and are rehearsed (`tests/test_rehearsals.py`), but they refuse
  whenever they would destroy operational records (receipt batches, deletion certificates, ERP alerts). Never force them.
* **Data**: point-in-time recovery (runbook *Backup and restore*). Then reconcile every non-`RECONCILED` order against the
  ERP, and re-apply tenant deletions newer than the restore point.
