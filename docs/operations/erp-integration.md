# ERP integration: adapter boundary, status and qualification

**Status (2026-10-24): no real ERP has been connected.** SupplyLens talks to purchasing systems through one adapter
contract. The only registered adapter is `sandbox_erp`, a local simulator in the same database. Every result below that
says *verified* means **verified against that simulator** (unit, integration and drill tests). It does not mean a real
ERP was tested. External qualification is **BLOCKED** until an authorised ERP test tenant, credentials and schema exist
(register item EXT-02).

## The boundary

| Piece | File | Role |
|---|---|---|
| Contract | `services/api/src/supplylens/integrations/contract.py` | `ErpAdapter` protocol; error classes; order statuses |
| Registry | `integrations/registry.py` | `SUPPLYLENS_ERP_ADAPTER` picks a registered adapter; an unknown name refuses every call (nothing is guessed) |
| Simulator | `integrations/sandbox_erp.py` | `SandboxErpAdapter`; fault injection; warehouse receipts and supplier cancellations for tests |
| Connector state | `integrations/connector.py`, table `erp_connector_state` | Circuit breaker: outage pause, credential failure stop, health probe |
| Dispatch | `actions/service.py` | Approval-bound outbox → submit → read-back → reconcile; cancellation |
| Synchronisation | `integrations/sync.py` (worker, every 60 s) | Order status, goods-receipt feed, overdue receipts |
| Reports | `operations.py`; `GET /api/v1/ops/health`, `GET /api/v1/ops/reconciliation`, `POST /api/v1/ops/connector/test` | Health, reconciliation, service levels |
| Conformance suite | `tests/test_phase6_erp.py` part 1 | What every adapter must pass, with a harness for its test environment |

Error classes and what SupplyLens does with them:

| Class | Meaning | Reaction |
|---|---|---|
| `AdapterUnavailable` | Unreachable or refusing service; nothing processed | Item returns to the queue **without spending a retry**. After 3 in a row the connector is `UNAVAILABLE`: dispatch pauses 30 s, then doubling up to 5 min, with one probe after each pause; high alert `erp_connector:unavailable` |
| `AdapterAuthError` | Credentials missing, expired or revoked; nothing processed | Connector `CREDENTIALS_INVALID`: dispatch stops until a health check succeeds (worker every 60 s, or **Test ERP connection**); high alert |
| `AdapterRejected` | Business refusal (blocked supplier, closed period); nothing created | Action `FAILED`, `failure_kind = rejected`, high alert; **retry is refused**, because the same order would be rejected again |
| `AdapterTimeout` | No answer; may or may not have applied | `UNKNOWN_OUTCOME`; reconcile looks the order up by its key and never resends blindly |
| `AdapterError` | Other transient failure, known not applied | Up to 5 attempts with exponential back-off, then `FAILED` (`exhausted`) |

## The ten operations

| # | Operation | Implemented | Verified against the simulator | Real ERP |
|---|---|---|---|---|
| 1 | Authentication and configuration | `SUPPLYLENS_ERP_ADAPTER`, registry refusing unknown adapters, credential failure → `CREDENTIALS_INVALID` stop and health probe | yes: tests for expired credentials, unregistered adapter, probe recovery | **BLOCKED**: no credentials or auth scheme (OAuth client, API key, certificate) known |
| 2 | Inventory and supplier data synchronisation | Imports through validated CSV batches (stock, sales, terms, receipts) with quarantine and immutable publish (D-038); no adapter pull | yes (existing onboarding tests) | **BLOCKED / not built**: an ERP pull needs the vendor's item, location and supplier schemas and a mapping review |
| 3 | Purchase-order submission | Approval-bound payload, outbox written in the approval's transaction, fresh-send re-checks | yes | BLOCKED |
| 4 | Idempotency and retry safety | Caller key `po-<action>`; contract requires target deduplication; lookup before any resend; fencing tokens on leases | yes: duplicate delivery, double approval, worker crash after submit, retry with the remote order present | BLOCKED: whether the vendor deduplicates on a caller key must be confirmed; if not, the adapter must look up by a reference field before every send |
| 5 | Acknowledgement and read-back | Line-by-line multiset comparison (SKU, location, quantity, unit, price, line value) plus supplier, currency, total, need-by, status; mismatch → `CONFIRMED`, accepted only by a second person | yes: 5 read-back faults | BLOCKED |
| 6 | Receipts and partial fulfilment | ERP receipt feed (cursor, key `erp:<receipt_id>`), partial lines, over-delivery → exception, receipt before local reconciliation held; manual receipts and receipt CSV imports remain | yes | BLOCKED: feed or webhook shape unknown |
| 7 | Rejection and cancellation | Business rejection never retried; **Cancel order** (approval rights, audited, target decides); supplier cancellation in the ERP releases open units with an alert | yes | BLOCKED |
| 8 | Reconciliation and exceptions | `UNKNOWN_OUTCOME` reconcile, mismatch acceptance, drift alert (ERP holds an order recorded here as failed, stale or unapproved), reconciliation report | yes | BLOCKED |
| 9 | Outages and expired credentials | Circuit breaker; retry budget preserved; database outage handled by the worker (drill) | yes: unit tests and `scripts/outage_drill.sh` | BLOCKED |
| 10 | Audit and recovery from uncertain outcomes | Every dispatch step, pause, cancellation and receipt is in `audit_events`; dead letter after 8 interrupted dispatches; PITR and disk-loss drills check orders against the ERP | yes | BLOCKED |

Not built, by design: automatic re-submission of a rejected order; automatic acceptance of a changed order; automatic
cancellation after drift. Each stays with a person (D-088). Purchasing stays deterministic and approval-gated.

## What qualifying a real ERP adapter needs

Owner or customer (none of this can be produced by code):

1. **A named ERP and an authorised test tenant** (sandbox or company code) where test purchase orders may be created
   and cancelled, with written permission to do so. Production must never be used for qualification.
2. **Credentials for that tenant**: auth scheme, client id and secret or certificate, scopes for create, read and cancel
   purchase orders and for reading goods receipts. They must be delivered through a secret manager, never in the
   repository (P1-OPS-01).
3. **Schemas and mappings**: purchase-order create and read payloads; supplier, item and location identifiers and how they
   map to SupplyLens ids; units of measure; currency and tax handling; need-by or delivery date field; status values and
   their meaning; the goods-receipt feed or webhook.
4. **Behaviour answers**: does the API deduplicate on a caller key, and for how long? Is creation synchronous? Which
   errors mean "not applied"? What are the rate limits? Are changes made by the ERP (price, quantity, date) reported, or
   only visible on read?
5. **Network path**: allow-listing, VPN or private link from the hosting platform.
6. **A named person on the customer side** for incident escalation and for approving the first real order.

Engineering steps once those exist:

1. Implement `ErpAdapter` for the vendor and map its errors onto the five classes above.
2. Write a harness for the vendor test tenant (outage, credentials, rejection, timeout, receipt) and run the
   conformance suite against it.
3. Register the adapter. Run the dispatcher and sync tests with it, then the outage drill against the test tenant.
4. Pilot: a handful of real, approved, low-value orders, with every outcome reconciled by hand against the ERP before
   the adapter's `status` becomes `QUALIFIED`.
