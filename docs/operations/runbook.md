# SupplyLens operations runbook (local / controlled environment)

Scope: a single-host development or demonstration installation. Nothing here qualifies a production
deployment (no enterprise identity, no off-host backups, no managed monitoring).

## Processes

| Process | Command | Port | Health |
|---|---|---|---|
| PostgreSQL 17 + pgvector | Homebrew service `postgresql@17` | 5432 | `pg_isready -h /tmp` |
| API | `uv run uvicorn supplylens.api.app:app --host 127.0.0.1 --port 8000` | 8000 | `GET /health` |
| Worker | `uv run python -m supplylens_worker.main` | — | `GET /api/v1/ops/health` → `workers.live ≥ 1` (a heartbeat row per tick; stale after 30 s); container check reads the heartbeat file |
| Web | `npm --prefix apps/web run dev` (or `start` after build) | 3100 | page loads |
| Embeddings (optional) | Ollama with `bge-m3:567m` | 11434 | Settings → Connections |

Containers: `docker compose up -d --build` starts db (WAL archiving on), migrate (+bootstrap), api, worker and web.
`--profile observability` adds Jaeger (set `SUPPLYLENS_OTEL_ENDPOINT=http://jaeger:4318` to send traces to it).
CI builds and starts the whole stack on every push (`compose-smoke` job); see EVIDENCE_INDEX for what was run where.

## First install

```bash
cp .env.example .env
./scripts/dev_db.sh
uv sync
uv run alembic -c services/api/alembic.ini upgrade head
python3 scripts/download_datasets.py --dataset online_retail_ii
uv run python -m supplylens.bootstrap
uv run python -m supplylens.ingest.acord
uv run python -m supplylens.ingest.cuad
uv run python -m supplylens.ingest.world_bank
uv run python evaluations/forecast_study.py
```

The forecast study registers the trained models; until it has run, forecasts use the seasonal-naive baseline.

## Reset the development database

`./scripts/reset_dev_db.sh` empties all tenant data (keeps control-plane users and tenants) and re-runs bootstrap.
Re-run the ingest commands and the forecast study afterwards. Destructive for the local dev database only.

## Backup and restore

Two independent mechanisms. Use the first for a portable copy, the second to recover to a point in time.

### 1. Logical dump (portable, daily-grade RPO)

```bash
./scripts/backup_restore_drill.sh
```

Takes a logical dump of `supplylens`, restores into an isolated `supplylens_restore_drill`, checks table counts,
document bytes against their SHA-256 and model artifacts against their recorded hashes, writes
`artifacts/reports/restore_drill_*.json`, then drops the drill database.

Restore to a new host: create roles (`scripts/dev_db.sh`), **create the `vector` extension as a superuser first**
(it is not a trusted extension; the first drill failed without this), then `pg_restore --no-owner
--role=supplylens_owner -L <list without EXTENSION entries>`. Copy `storage/` (document bytes) and `artifacts/`
(model weights) alongside the dump; embeddings are rebuilt from documents but documents and approvals are not.

Measured on 2026-10-21: 70 MB dump, backup 6.2 s, restore 6.6 s. A dump alone cannot recover orders placed after it
was taken (see 2).

### 2. Continuous WAL archiving + base backups (point-in-time recovery, BUS-014 / ARC-06)

The compose database runs with `wal_level=replica`, `archive_mode=on`, `archive_timeout=60`; each completed WAL segment is
copied to the `walarchive` volume, and `archive_timeout` bounds how much recent work a lost primary disk can lose
(**RPO ≤ archive_timeout for the unarchived tail, plus whatever the archive volume itself loses; keep it on separate storage**).

```bash
./scripts/base_backup.sh                 # physical base backup into the `basebackups` volume (take one daily)
./scripts/pitr_drill.sh                  # rehearsal on a scratch cluster, never touches your data
```

`pitr_drill.sh` builds a scratch cluster with archiving, creates real orders through the application, takes a base backup,
creates one more order that exists only in archived WAL, simulates an operator error (truncates the order tables and the
sandbox ERP orders), restores the backup, replays WAL to a recovery target just before the error, promotes, and verifies
that every count equals its value at the target and every sandbox order maps to exactly one action. It writes
`artifacts/reports/pitr_drill_*.json` (PostgreSQL version, restored size, RTO, RPO bound). The measured RTO is for the
tiny drill database only and grows with backup size and WAL volume.

Real recovery from the compose stack: stop the stack, restore the newest base backup into an empty `pgdata` volume
(`tar -xzf base.tar.gz`; unpack `pg_wal.tar.gz` into `pg_wal`), set `restore_command = 'cp /wal_archive/%f %p'` and
`recovery_target_time = '<UTC time just before the incident>'` in `postgresql.auto.conf`, `touch recovery.signal`, start
PostgreSQL, wait for promotion, then **reconcile every order whose outcome is not RECONCILED against the ERP** (Unknown order
outcome, below). A restore that predates a tenant deletion brings the deleted tenant back: re-apply the deletion with
`uv run python -m supplylens.lifecycle reapply-deletions [<tenant-id> ...]`, passing the tenant ids from the deletion
certificates you keep outside the database (a backup older than the deletion does not contain its certificate).

## Unknown order outcome

Symptoms: an action shows `UNKNOWN_OUTCOME` (Exceptions inbox, Approvals, Administration → Order reconciliation). Do
**not** re-approve or resend. This includes a dispatch the worker was interrupted on more than 8 times (reason "dispatch
interrupted … reconcile before any retry"): it is parked here instead of being sent again. Open the draft → *Reconcile*.
The system looks the operation up by its idempotency key: found → read back and compared → `RECONCILED`; not found →
safely re-queued (the adapter contract requires deduplication by key). If the ERP cannot be reached, reconcile answers
503 `erp_unavailable` and changes nothing: try again when the connector is back.

## Stale approval

`STALE` means the supplier terms, payload or approval expiry changed after preparation. Start a new investigation
(or edit quantities, which revalidates); the old approval can never be reused.

## ERP connector (Phase 6; adapter contract in `docs/operations/erp-integration.md`)

Administration → **Service health** shows the connector state; `GET /api/v1/ops/health` returns the same.

| State / alert | Meaning | What to do |
|---|---|---|
| `UNAVAILABLE`, alert `erp_connector:unavailable` | 3+ consecutive "unreachable" answers; dispatch paused (30 s doubling to 5 min, one probe after each pause) | Check the ERP's status page and the network path. Nothing to resend: queued orders keep their place and retry budget and go out on their own when it answers. Escalate to the ERP owner after 30 min (SEV2) |
| `CREDENTIALS_INVALID`, alert `erp_connector:credentials` | The ERP refused the credentials; nothing is sent | Renew the credentials in the secret store and redeploy (or fix the configuration), then **Test ERP connection**. Dispatch resumes on success; the alert resolves |
| Action `FAILED`, `failure_kind = rejected` | The ERP refused this order (blocked supplier, closed period, ...) | Read the reason. **Retry is refused** on purpose. Fix the cause (supplier or terms) and prepare a new draft |
| Action `FAILED`, `failure_kind = exhausted` | 5 transient errors | Retry once the cause is gone (Retry checks the ERP first and refuses if the order exists) |

The simulator can reproduce each case on a development stack: `POST /api/v1/sandbox/connector`
`{"available": false}` or `{"credentials_valid": false}`, and the fault mode `reject` (development only).

## Order cancellation

An approver can **Cancel order** on a reconciled order with open units. The ERP decides: once every line is received it
refuses, and nothing changes here. On success the open units are released from the open-order ledger, so planning sees
the supply gone. With no answer, nothing changes here and the next order sync applies whatever the ERP then holds. A
supplier cancelling or rejecting an order inside the ERP has the same effect at the next sync, with alert
`erp_sync:closed:<action>`: re-plan if the need remains.

## Receipts, synchronisation exceptions and overdue receipts

The worker reads the ERP's goods-receipt feed every 60 s and books each receipt once (key `erp:<receipt_id>`; the
audit entry `order.received` says `source: erp`). Manual receipts (draft → *Record receipt*) and receipt CSV imports remain
for ERPs without a feed.

| Alert | Cause | What to do |
|---|---|---|
| `erp_sync:receipt:<id>` | The ERP booked more than is open, or a receipt for an unknown line | Compare the receipt with the order in the ERP; book the correct quantity by hand or correct the ERP. Over-deliveries are never booked automatically |
| `erp_sync:drift:<action>` | The ERP holds an order SupplyLens records as failed, stale or unapproved | Never resolve by resending. Either cancel the order in the ERP, or reconcile it here if it is legitimate. The alert clears when the two agree |
| `overdue_receipt:<action>` | Open units past the expected date + 2 days (business date = the workspace's operational date) | Chase the supplier; book the receipt when it arrives or cancel the open units. Clears on receipt or cancellation |

A receipt for an order not yet reconciled here (`UNKNOWN_OUTCOME`, `CONFIRMED`) is held, and booked after
reconciliation.

## Daily reconciliation check (operations owner)

Administration → **Order reconciliation** (`GET /api/v1/ops/reconciliation`):
1. "Every approved order has a known outcome", or work through **Orders that need a person** from the oldest.
2. Approved → reconciled p95 and "within 5 minutes" against the objective (`docs/operations/slo.md`).
3. Open `erp_sync` / `overdue_receipt` alerts; last receipt sync less than 2 minutes old while the worker runs.
Record exceptions older than one business day in the incident log (`docs/operations/service-management.md`).

## Worker stopped or database unavailable

* **Worker**: `ops/health` → `workers.status = failing` ("no worker has ticked in the last 30 s"). Approved orders wait;
  nothing is lost. Restart the worker. It resumes the queue and dispatches from the outbox; lease expiry makes interrupted
  sends look the order up first. A worker that crashes mid-send is covered by the same rule (tests and the outage drill).
* **Database**: the API answers **503 `database_unavailable`** with `Retry-After` (Phase 6; before, a 500) and the
  worker logs failed ticks and keeps retrying every 5 s. Measured on a scratch cluster (`scripts/outage_drill.sh`): after a
  20 s crash-stop, the API was healthy as soon as PostgreSQL accepted connections, and 5 orders that waited through the
  outage were reconciled 5.3 s later, exactly one ERP order each. Restore procedures are under *Backup and restore*.

## Model retraining and promotion

Run `uv run python evaluations/forecast_study.py --config ml/configs/forecast_study_v2_1.json` (current protocol; about
20 minutes on an M4 Pro). Registry status follows the frozen validation rule. A tenant administrator can change status
in Administration with a reason (audited).

**Promotion gate (Phase 5, `forecasting/governance.py`).** A trained model becomes champion only if its recorded
evaluation shows a validation pinball below the same experiment's seasonal-naive baseline, recorded 80% coverage within
0.65–0.95, raw quantile crossing at most 20%, no smoke run, and every registered artifact present on this host with its
registered hash. The API answers 422 `promotion_gate` with the reasons otherwise. Test-window results are never a gate.

**Serving fallbacks.** A trained model refuses origins before its training cutoff. When decision flows allow it, a
champion whose artifact is missing, untrusted or failing is replaced by seasonal naive for that run (flag `_model`) and a
high-severity `model_unavailable` alert opens; products younger than the model's 56-day window get the baseline,
flagged per product.

**Monitoring and rollback.** `GET /api/v1/models/monitoring?as_of=YYYY-MM-DD` (administrators) scores stored forecasts
against sales, recomputes seasonal naive on exactly the same products, origins and days (shadow baseline), reports
realised 80% coverage and demand drift (PSI against the champion's training year). It recommends; it never acts. If it
reports the champion worse than the shadow baseline on at least 200 points, roll back by promoting the baseline (or the
previous version) in Administration with a reason — the same audited path as any promotion.

## Alerts (BUS-018)

Eight alert kinds open in the **Exceptions** inbox (the operational queue) and optionally go to a webhook:
`stale_data`, `failed_reconciliation`, `budget_exhausted`, `model_unavailable`, `job_failed`, and since Phase 6
`erp_connector`, `erp_sync`, `overdue_receipt`. Identical open alerts are de-duplicated
(occurrence count increases); an alert resolves itself when its cause clears (for example, a failed order is re-queued and
reconciled). Planners, approvers and administrators acknowledge alerts.

Webhook: set `SUPPLYLENS_ALERT_WEBHOOK_URL` and `SUPPLYLENS_ALERT_WEBHOOK_SECRET`. Each delivery is a JSON POST with
`X-SupplyLens-Timestamp` (Unix seconds), `X-SupplyLens-Signature` = `sha256=` + HMAC-SHA256(secret, `"<timestamp>.<body>"`) and
`Idempotency-Key: alert-<id>`. Receivers must verify the signature, reject timestamps older than a few minutes, and
de-duplicate on the idempotency key. Failed deliveries retry with backoff (2^n s, at most 5 min) and give up after
`MAX_DELIVERY_ATTEMPTS`; the alert stays in the queue either way.

## Tracing (OpenTelemetry)

Set `SUPPLYLENS_OTEL_ENDPOINT` to an OTLP/HTTP collector (for example `http://jaeger:4318`). Spans: HTTP requests, SQL
statements, agent-graph nodes, retrieval, forecasting and ERP dispatch. The trace context is stored in each queued job so a
worker's spans continue the request that caused them. Unset = tracing off; every response still carries `x-trace-id`.

## Metrics and overload (Phase 3)

Set `SUPPLYLENS_METRICS_TOKEN` (32+ random characters) and scrape `GET /metrics` with `Authorization: Bearer <token>`
(Prometheus text format; unset = the endpoint does not exist). Each API process reports its own values; sum them. What to
watch:

| Series | Meaning | Act when |
|---|---|---|
| `supplylens_http_request_duration_seconds` (by route) | latency histogram | p95 of metadata reads > 0.5 s or of `/api/v1/evidence/search` > 2 s |
| `supplylens_admission_rejected_total{class,reason}` | requests refused for capacity (`queue_full`, `wait_timeout`) or a workspace over its share (`tenant_share`) | rising steadily: add API capacity or database CPU |
| `supplylens_admission_inflight` / `_capacity` / `_waiting` | in-flight and queued per class (all, retrieval, compute) | waiting > 0 for minutes |
| `supplylens_db_pool_checked_out`, `supplylens_db_pool_timeouts_total` | connection-pool saturation | timeouts > 0 |
| `supplylens_db_connections{state}`, `supplylens_db_max_connections` | database connections for this database | active near max |
| `supplylens_db_statement_timeouts_total` | statements cancelled (retrieval 8 s, others 30 s) | any sustained rate |
| `supplylens_jobs{status}`, `supplylens_jobs_oldest_queued_seconds`, `supplylens_outbox{status}` | queue depth (cached 15 s) | oldest queued job > 60 s; `UNKNOWN_OUTCOME` > 0 (reconcile) |
| `supplylens_tenant_*_total{workspace}` | per-workspace requests, server seconds, retrieval/compute seconds, refusals, errors | one workspace dominating `retrieval_seconds` |

Overload behaviour: a full class waits up to `SUPPLYLENS_ADMISSION_WAIT_MS` (0.5 s) in a queue of
`SUPPLYLENS_ADMISSION_QUEUE` (12), then answers **503** `overloaded` with `Retry-After: 2`; a workspace over its share
answers **429** `workspace_busy`; an exhausted pool or a cancelled statement answers **503** with `Retry-After: 3`. The web
client shows "SupplyLens is busy" and retries reads after Retry-After. Caps: `SUPPLYLENS_MAX_INFLIGHT` (48, also the
thread-pool size), `SUPPLYLENS_MAX_INFLIGHT_RETRIEVAL` (6), `SUPPLYLENS_MAX_INFLIGHT_COMPUTE` (4), `SUPPLYLENS_TENANT_SHARE`
(0.5); timeouts `SUPPLYLENS_DB_STATEMENT_TIMEOUT_MS` (30000), `SUPPLYLENS_RETRIEVAL_STATEMENT_TIMEOUT_MS` (8000),
`SUPPLYLENS_DB_POOL_TIMEOUT_S` (5). All are per process.

## Tenant export and deletion (BUS-023)

Administration → *Export*: a consistent snapshot (one `REPEATABLE READ` transaction) of every tenant table as NDJSON, the
document bytes, optionally the embedding vectors, and a manifest with row counts and SHA-256s; the archive is re-read and
verified before it is marked READY and the verification result is part of the manifest. Deletion needs the typed workspace
slug, a verified export that has been downloaded, and a reason; it removes tenant rows in foreign-key order, deletes document
files, writes a deletion certificate, and purges the append-only audit rows in one narrow SECURITY DEFINER step that refuses
any other tenant or a non-customer workspace. **Backups taken before a deletion still contain the tenant's data**: delete or
expire them under the retention policy the owner sets (not defined in this build). Restoring such a backup brings the tenant back until
`reapply-deletions` is run (see Backup and restore).

## Performance settings that matter (ARC-07)

Measured on the reference data set (100,000 chunks, ~1,000,000 sales rows); details in `docs/operations/load-test.md`.

* The application opens connections with `plan_cache_mode=force_custom_plan`. Without it, a prepared statement's sixth use
  can switch to a generic plan and retrieval slows ten-fold. Do not put a pooler in front that drops startup options without
  setting the same parameter on the database role.
* For the database role used by the API, `max_parallel_workers_per_gather = 0` gave steadier retrieval latency under
  concurrent users than the default (the compose file sets it). Revisit if the host has many idle cores.
* Full-text search runs a sequential scan of the tenant's chunks under row-level security (the GIN index cannot be used
  there), so retrieval cost grows linearly with a tenant's chunk count. Since migration 0010 the vectors live in
  `chunk_vectors`, so that scan reads text only (131 MB instead of 782 MB at 100,000 chunks); the exact vector scan still
  reads one 8 KB page per vector (a 1024-d float vector does not fit twice in a page).
* Listings (`/inventory`, `/documents`) return at most `SUPPLYLENS_LIST_MAX_ROWS` (5,000) rows per response; page with
  `limit`/`offset`.

## Rehearsals (BUS-020)

`uv run pytest tests/test_rehearsals.py` (needs a PostgreSQL superuser through `PGHOST/PGUSER/PGPASSWORD`) runs on scratch
databases: a failed migration (schema, data, orders and audit untouched), rollback to the previous release and roll-forward,
rollback refusing to destroy deletion certificates, ERP connector outage then recovery (exactly one order), refusal to retry
when the remote order exists, and embedding-service outage (retrieval degrades and says so, the workflow completes). The
pass criterion in each is no unaccounted order and no lost audit evidence.

## Contracts and CI

`./scripts/check_contracts.sh` regenerates `packages/contracts/openapi.json` and `api.d.ts` and fails on drift.
`.github/workflows/ci.yml` runs on every push, pull request and weekly: ruff (correctness, imports, bugbear, security rules),
lockfile check, gitleaks over full history, pip-audit and `npm audit`, pytest against pgvector (including the BUS-020
rehearsals), the contract check, typecheck, `next build`, the Playwright suites (journeys, consistency, resilience,
accessibility, Web Vitals) against a real API and database seeded with the synthetic fixture, the PITR drill, and a full
`docker compose` build-and-smoke.

## Known limitations

- Session cookies are dev-only; OIDC is not configured. Do not expose this installation to a network.
- Logout does not revoke a captured session cookie before it expires (security review F-06).
- Search has no tenant-wide request ceiling, only a per-user one (F-05).
- Lexical search reads every chunk of the tenant (see Performance settings); a vector index (HNSW) would cut the vector
  half of the cost but needs real embeddings to validate recall, which this build cannot produce.
- Recovery objectives were rehearsed on a toy database; RTO for a real data volume is unmeasured.
- Mobile LCP is above the field target in the throttled lab profile (`docs/operations/web-vitals.md`).
