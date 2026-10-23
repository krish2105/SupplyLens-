# Service levels and recovery objectives

Phase 6 (2026-10-24). The targets below are **proposals** (D-093). This page records what was measured, where, and
what each target would need. Nothing here is a claim that SupplyLens achieves them in production. There is no production
deployment (P1-OPS-01), no uptime history and no on-call.

## Proposed objectives and their indicators

| Objective (proposed) | Indicator | Where it is measured today |
|---|---|---|
| **Availability 99.9%** per calendar month (≈ 43.8 min of downtime) | Share of minutes in which an external probe gets `GET /health` = 200 | **Not measured**: no external probe exists. `/health` now answers 503 when the database is unavailable (D-091), so a probe can tell an outage from a defect |
| Request success ≥ 99.5% of API requests not 5xx (503 overload responses counted as failures) | `supplylens_http_requests_total{status}` | `/metrics` (per process) |
| **Dispatch**: 99% of approved orders reconciled within 5 minutes while the ERP connector is OK | `service_levels.approved_to_reconciled_within_5_min`, p50/p95 | `GET /api/v1/ops/reconciliation` (audit timestamps) |
| No order without a known outcome for more than 4 hours | `unaccounted_orders` and the age of `needs_attention` | same endpoint; alerts `failed_reconciliation` |
| Receipt feed fresh within 2 minutes | `sync.last_receipt_sync_at` | same endpoint |
| **RPO ≤ 15 minutes** | Acknowledged writes lost when the primary's disk is lost | `scripts/recovery_drill.sh` |
| **RTO ≤ 60 minutes** | Loss of the primary → API healthy on the restored database | `scripts/recovery_drill.sh`, `scripts/pitr_drill.sh` (CI) |

An ERP outage does not count against SupplyLens availability: approved orders wait in the outbox, keep their retry
budget, and go out when the ERP answers (D-089). It does count against the dispatch objective, which is why that
objective applies only while the connector is OK.

## What was measured

All on one machine (Apple M4 Pro, PostgreSQL 17.11) unless stated. The scratch clusters are created and deleted by the
scripts; no real database was touched.

| Drill | Data | Result | Report |
|---|---|---|---|
| Disk loss, `archive_timeout = 60 s` (`recovery_drill.sh`) | 1.29 GB copy of the local load-test database (100,000 chunks with vectors, 2,000 products); writer committing every 0.2 s | 871 writes acknowledged, **290 lost**, all in the last 59.5 s; **RPO 59.8 s**; base backup 48 s (272 MB compressed); restore 3.4 s; **loss → healthy API 7.0 s**; counts and migration head identical | `artifacts/reports/recovery_drill_20261023T200749Z.json` |
| Disk loss, `archive_timeout = 15 s` | same, 90 s of writes | 433 acknowledged, **1 lost**; RPO 0.4 s (the loss fell just after an archive; the bound is 15 s); restore 3.4 s; loss → healthy API 7.0 s | `artifacts/reports/recovery_drill_20261023T201201Z.json` |
| Database crash-stop for 20 s (`outage_drill.sh`), worker killed beforehand | Demo workspace, 5 approved orders waiting | API and worker survived; `/health` 503 throughout; API healthy at once when PostgreSQL returned; all 5 orders reconciled **5.3 s** later, exactly one ERP order each | `artifacts/reports/outage_drill_20261023T200126Z.json` |
| Point-in-time recovery after an operator error (`pitr_drill.sh`, CI, Linux, PostgreSQL 16) | 10.8 MB | restore 0.5 s; every order accounted for | CI run 40007865030, artifact `pitr-report` |
| Logical dump and restore (`backup_restore_drill.sh`, 2026-10-21) | 70 MB dump | backup 6.2 s, restore 6.6 s | `artifacts/reports/restore_drill_20261021T194413Z.json` |
| Dispatch latency (Administration, disposable browser-test stack) | 117 orders from test runs | p95 1 s; 100% within 5 minutes | test data, not a pilot |

## Feasibility

**RPO ≤ 15 minutes: feasible.** It requires one change from the drill: the WAL archive must live on separate storage
(another host or object storage). In the drill it shared the primary's disk, and losing both would lose everything since
the last base backup. With archiving, loss is bounded by `archive_timeout` (measured 59.8 s at 60 s). An alert must also
fire when archiving stops: `pg_stat_archiver.failed_count` rising, or `last_archived_time` older than 2 ×
`archive_timeout`. That alert is not built. For near-zero RPO, stream WAL continuously (`pg_receivewal`) or keep a
synchronous standby. The hosted demo's database (Neon) has the provider's own point-in-time restore, which **has not
been tested for this project**.

**RTO ≤ 60 minutes: technically feasible at the measured size, not yet operationally.** The technical part took seconds
for 1.29 GB. It grows with the base backup's size and the WAL to replay; at tens of GB expect minutes, which needs a
measurement on the target platform, not an extrapolation. What dominates a real RTO is unmeasured: noticing the loss,
deciding to restore, and having credentials and the runbook at hand. That needs on-call staff and a rehearsal on the
production platform at least quarterly. After every restore, every order that is not `RECONCILED` must be reconciled
against the ERP (runbook), which takes minutes per exception.

**Availability 99.9%: not supportable on the current setup; plausible with platform work.** Single points of failure
today: one PostgreSQL (local) or one managed database whose availability tier is unknown to us (hosted); one worker
process (local) or request-driven work (hosted); no external probe, no alerting to a person, no on-call. At 43.8 min per
month, one unattended database incident uses the whole budget. Needed, in order:
1. An external uptime probe on `/health` with paging (detection).
2. A managed PostgreSQL with a standby and automatic failover, plus WAL archiving to separate storage.
3. At least two API instances behind a load balancer, and two or more worker processes (safe by design: leases,
   `FOR UPDATE SKIP LOCKED`, fencing tokens; throughput with several workers is not load-tested, P2-REL-03).
4. Zero-downtime releases (the hosting platform's atomic deploys; schema changes kept backward-compatible, D-090).
5. On-call with the incident process in `service-management.md`, and an error-budget policy that stops feature releases
   when the budget is spent.

Owner decisions needed: hosting platform and database tier (P1-OPS-01), whether to staff on-call, and whether to adopt
these objectives for a pilot (EXT-03).
