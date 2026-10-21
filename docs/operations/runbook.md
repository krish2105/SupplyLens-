# SupplyLens operations runbook (local / controlled environment)

Scope: a single-host development or demonstration installation. Nothing here qualifies a production
deployment (no enterprise identity, no off-host backups, no monitoring stack).

## Processes

| Process | Command | Port | Health |
|---|---|---|---|
| PostgreSQL 17 + pgvector | Homebrew service `postgresql@17` | 5432 | `pg_isready -h /tmp` |
| API | `uv run uvicorn supplylens.api.app:app --host 127.0.0.1 --port 8000` | 8000 | `GET /health` |
| Worker | `uv run python -m supplylens_worker.main` | — | jobs/outbox drain in Administration |
| Web | `npm --prefix apps/web run dev` (or `start` after build) | 3100 | page loads |
| Embeddings (optional) | Ollama with `bge-m3:567m` | 11434 | Settings → Connections |

Containers: `docker compose up --build` starts db, migrate (+bootstrap), api, worker and web. The API image build is
recorded in EVIDENCE_INDEX; the full stack has not been run under Compose on this host (colima VM: 2 CPU / 2 GB).

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

Measured on 2026-10-21: 70 MB dump, backup 6.2 s, restore 6.6 s. This is a local rehearsal, not point-in-time
recovery; the live-write RPO requirement (no lost orders) needs continuous WAL archiving, which is not configured.

## Unknown order outcome

Symptoms: an action shows `UNKNOWN_OUTCOME` (Exceptions inbox or Approvals). Do **not** re-approve or resend.
Open the draft → *Reconcile with sandbox*. The system looks the operation up by its idempotency key: found →
read back and compared → `RECONCILED`; not found → safely re-queued (the sandbox deduplicates by key).

## Stale approval

`STALE` means the supplier terms, payload or approval expiry changed after preparation. Start a new investigation
(or edit quantities, which revalidates); the old approval can never be reused.

## Model retraining and promotion

Run `uv run python evaluations/forecast_study.py`. Registry status follows the frozen validation rule. A tenant
administrator can change status in Administration with a reason (audited); a model can only become champion if it
has a recorded evaluation. Trained models refuse forecast origins earlier than their training cutoff.

## Contracts and CI

`./scripts/check_contracts.sh` regenerates `packages/contracts/openapi.json` and `api.d.ts` and fails on drift.
`.github/workflows/ci.yml` runs pytest against pgvector, the contract check, typecheck and `next build`. The workflow
has not run on GitHub (no remote configured).

## Known limitations

- Rate limits are in-process token buckets (valid for a single API instance only).
- Session cookies are dev-only; OIDC is not configured. Do not expose this installation to a network.
- No OpenTelemetry exporter; requests carry `x-trace-id` and are logged with timings.
