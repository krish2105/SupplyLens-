# Phase 6 — ERP integration and operational excellence

**Dates:** 2026-10-24 (UTC) · **Start:** `main` @ `e9ed389` (Phase 5 closed: Linux Research baselines committed) ·
**Commits:** see `git log` after `e9ed389` · **Owner brief:** Phase 6 (ERP adapter boundary, COO readiness, reliability
validation). Purchasing stays deterministic and approval-gated; **no real ERP, credentials or partner tenant exist**, so
every ERP result here is against the local simulator and external qualification is **BLOCKED** (EXT-02).

Evidence `P6-E..` → [`../EVIDENCE.md`](../EVIDENCE.md); issues → [`../ISSUES.md`](../ISSUES.md); decisions D-088 … D-093 →
root [`DECISIONS.md`](../../../DECISIONS.md). Operator documents: [`erp-integration.md`](../../operations/erp-integration.md),
[`slo.md`](../../operations/slo.md), [`service-management.md`](../../operations/service-management.md), runbook.

## 0. Starting point (verified in code)
Already strong: approval bound to the payload hash, the outbox written in the approval's transaction, lookup before any
resend, line-by-line read-back, a dead letter after 8 interrupted dispatches, an open-order ledger with manual receipts and
cancellations, a PITR drill in CI, migration rehearsals. Missing: an adapter contract (the dispatcher imported the
simulator directly), any classification of ERP errors, ERP receipt and status synchronisation, cancellation in the ERP,
a view of a stopped worker, and a health or reconciliation report. Recovery numbers were bounds on a toy database.

## 1. Findings and fixes
| ID | Sev. | Finding | Fix |
|---|---|---|---|
| ERP-P6-01 | **P1** | An outage spent the retry budget: a ~30 s outage failed every queued order | Circuit breaker; outages and credential failures do not spend attempts (D-089) |
| ERP-P6-02 | P2 | A business rejection was retried 5 times and retryable by hand | `AdapterRejected`: fail at once, `failure_kind = rejected`, retry refused |
| ERP-P6-03 | P2 | Expired credentials looked like any error | `CREDENTIALS_INVALID` stop, health probe, **Test ERP connection** |
| ERP-P6-04 | P2 | A lookup failure during a retry escaped the dispatcher; repeated lease expiries could dead-letter orders | Paused like an outage; lookup-first preserved |
| ERP-P6-05 | P2 | No receipt or status sync, no cancellation in the ERP; ERP-side cancellations left phantom supply | Receipt feed, order-status sync, Cancel order (D-088, D-092) |
| OPS-P6-01 | P2 | 500 on every route during a database outage | 503 `database_unavailable` + Retry-After (D-091) |
| OPS-P6-02 | P2 | A stopped worker was invisible; no health or reconciliation report | `worker_heartbeats`, `/ops/health`, `/ops/reconciliation`, Administration cards, `/metrics` gauges |
| OPS-P6-03 | P2 | Hosted database not migrated to 0011 | Open: owner action (PD-009); the code runs in its pre-0011 mode meanwhile (D-090) |
| OPS-P6-04 | P3 | Held receipts keep the feed cursor (limit 500 per sync) | Open, documented |

## 2. ERP operations (simulator) — completed vs unverified
See [`erp-integration.md`](../../operations/erp-integration.md) for the full table. In short:

| # | Operation | Against the simulator | Against a real ERP |
|---|---|---|---|
| 1 | Authentication/configuration | Done (registry, credential stop, probe) | BLOCKED: no credentials or scheme |
| 2 | Inventory/supplier sync | CSV imports only (existing); no ERP pull | **Not built**: needs vendor schemas |
| 3 | PO submission | Done | BLOCKED |
| 4 | Idempotency/retry safety | Done | BLOCKED: vendor deduplication unknown |
| 5 | Acknowledgement/read-back | Done | BLOCKED |
| 6 | Receipts/partial fulfilment | Done (feed) | BLOCKED: feed shape unknown |
| 7 | Rejection/cancellation | Done | BLOCKED |
| 8 | Reconciliation/exceptions | Done (+ drift, report) | BLOCKED |
| 9 | Outages/expired credentials | Done (+ DB outage drill) | BLOCKED |
| 10 | Audit/uncertain outcomes | Done | BLOCKED |

## 3. Failure and recovery scenarios tested
| Scenario | How | Result |
|---|---|---|
| ERP timeout (unknown outcome) | test; reconcile during and after an outage | No resend; 503 while the ERP is down; one order after |
| ERP outage, short and long | test: 23 paused attempts | 0 attempts spent; reconciled once on return; alert raised and resolved |
| Expired credentials | test + browser (disposable stack) | Dispatch stops; probe fails then succeeds; one order; alert resolved |
| Business rejection | test | FAILED at once, never retried |
| Worker crash after submit, then outage | test | Lookup-first after recovery; one order |
| Worker crash + database outage (20 s) | `outage_drill.sh` | Both processes survived; 503 throughout; orders reconciled 5.3 s after the database returned; 1 order each |
| Duplicate requests | test (cancel-order with one key) | One cancellation, replay marked |
| Partial processing / partial receipts | tests | Booked once, resumable cursor, over-delivery → exception |
| Delayed receipts | test | Overdue alert after 2 days, cleared on receipt |
| ERP-side cancellation, drift | tests | Supply released with alert; drift alerts only |
| Primary disk loss | `recovery_drill.sh` (1.29 GB) | See §5 |

## 4. Monitoring and support readiness
Built: `GET /api/v1/ops/health` (database, workers, jobs, outbox, imports, alerts, connector), `GET /api/v1/ops/reconciliation`
(states, needs-attention with next steps, ledger, overdue lines, sync, service levels), `POST /api/v1/ops/connector/test`,
Administration cards (Service health, Order reconciliation), `/metrics` gauges, three alert kinds, Exceptions labels.
Written: runbook procedures (connector, cancellation, receipts, daily reconciliation, worker/database), incident
classification and response, support tiers and escalation, onboarding, release and rollback
([`service-management.md`](../../operations/service-management.md)). **Not in place:** an external uptime probe, paging,
on-call staff, a status page, an alert on WAL archiving failures.

## 5. Reliability validation (measured, not assumed)
| Target (proposed) | Measured | Verdict |
|---|---|---|
| RPO ≤ 15 min | 59.8 s at `archive_timeout = 60 s` on 1.29 GB (290 of 871 acknowledged writes lost); 0.4 s at 15 s (1 of 433 lost; bound 15 s). One run each | Feasible, **if** the WAL archive is on separate storage (it was not, in the drill) and archiving failures alert |
| RTO ≤ 60 min | Loss → healthy API 7.0 s (restore 3.4 s) on 1.29 GB; CI PITR 0.5 s on 10.8 MB | Technically feasible at this size; detection and decision time unmeasured (no on-call) |
| Availability 99.9% | Not measured (no probe, no history) | Not supportable today; needs HA database, ≥ 2 API instances and workers, probe and paging, on-call ([`slo.md`](../../operations/slo.md)) |

## 6. Tests executed
See EVIDENCE P6-E01 … New: `tests/test_phase6_erp.py` (28: adapter conformance, dispatcher failures, cancellation,
synchronisation, operations, 503, metrics); `scripts/outage_drill.sh`, `scripts/recovery_drill.sh` (+ `ops_drill.py`).
Changed: `tests/conftest.py` (new tables), `tests/test_rehearsals.py` (HEAD 0011).

## 7. Credentials, partner access and infrastructure still needed
* An ERP vendor, an authorised test tenant, credentials and schemas (list in `erp-integration.md`): EXT-02.
* The hosted migration to 0011 through the setup token (owner, PD-009): OPS-P6-03.
* A production platform with an HA database, off-host WAL archive, ≥ 2 instances, secret manager (P1-OPS-01).
* An external uptime probe and paging, on-call staff, a status page (owner decision).
* A pilot customer to measure real dispatch latency, exceptions and receipts (EXT-03).
