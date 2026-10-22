# Phase 3 — performance, scalability and backend reliability

**Dates:** 2026-10-23 (UTC) · **Start:** `main` @ `2365f49` · **Brief:** the owner's "Phase 3: performance, scalability
and backend reliability" (followed instead of the hand-over's web-robustness proposal, as that prompt directs when the owner
gives a brief — DECISIONS PD-014). Evidence `P3-E..` → [`../EVIDENCE.md`](../EVIDENCE.md); issues →
[`../ISSUES.md`](../ISSUES.md); product decisions D-068 … D-072 → root [`DECISIONS.md`](../../DECISIONS.md).

**Benchmark scope, stated once.** All measurements ran on the owner's laptop (Apple M4 Pro, 12 cores, 24 GB, macOS;
API, PostgreSQL 17, an embedding stub and the load driver on one machine), with synthetic reference data (100,000 chunks,
~1,000,000 sales rows, 20 users) and before/after on the same data, driver and durations. This is **not** the declared
8 vCPU / 32 GiB profile (EXT-04), excludes real embedding latency, and is **not** production evidence.

## 1. Investigation

| Question from the brief | Finding | Label |
|---|---|---|
| Is the 4→5 req/s retrieval collapse still reproducible? | **No, not on this machine**: before any change it served 5 req/s at retrieval p95 256 ms, metadata p95 44 ms, 0 failures; it saturated near 8–9 served req/s (P3-E04). The 2026-10-21 collapse was on a 4 vCPU Xeon; the knee moved with the hardware. | VERIFIED (here); declared profile UNVERIFIED |
| Full-text search, RLS, indexes, plans | The GIN index still cannot be used under RLS (`@@` is not leakproof; D-035 stands). Both retrieval queries read ≈100,000 buffers per search because the inline 4 KB vector made every chunk row occupy one 8 KB page: the lexical scan read 782 MB of vectors it never uses (PERF-P3-01). The vector query evaluated the distance twice and sorted full rows (PERF-P3-02). | VERIFIED (EXPLAIN BUFFERS, P3-E03) |
| pgvector | Exact scan, no ANN index; 1024-d float vectors cannot fit two per page (PERF-P3-09). HNSW/halfvec would change ranking and need the retrieval studies re-run — not done. | VERIFIED |
| Connection pooling | 10 + 10 connections, 30 s pool wait ending in 500; 64 admitted requests on a 40-thread pool (hidden queue) (PERF-P3-03). | VERIFIED (code) |
| Document filtering | Role/known-at/effective filters join 2,000 versions by hash (cheap); `/documents` counted chunks with a sub-query per version (PERF-P3-06). | VERIFIED (plan, code) |
| Admission / overload | 503 shedding existed (DEF-10) but one shared "costly" cap let compute refuse searches; no queue, no per-workspace bound (SEC-P2-11), no statement timeout (PERF-P3-04/05). | VERIFIED (code) |
| Expensive work | Forecasts and CP-SAT run inside the API process; 3 planners looping scenarios raise metadata p95 44 → ~205 ms and take 0.8 core (GIL) (PERF-P3-08). Targets still met, so isolation is recorded, not built. | VERIFIED (mixed runs) |
| Worker | One workspace's error ended the whole tick every tick; one workspace could monopolise a tick's dispatches; an outbox item whose worker kept dying was re-claimed forever (P2-REL-03). Job retries, leases, fencing and exhausted-lease handling were already sound (Phase 1). | VERIFIED (code) |
| Observability | No latency, saturation, queue-depth or per-tenant series (PERF-P3-07). | VERIFIED (absence) |

## 2. Fixes (files and why)
| Fix | Files | Why |
|---|---|---|
| Vectors in their own table | `migrations/versions/0010_chunk_vectors.py`; `knowledge/retrieve.py`, `knowledge/ingest.py`, `ingest/cuad.py`, `ingest/acord.py`, `alerts.py`, `lifecycle.py`; `scripts/loadtest/seed_reference.py` | The lexical scan reads 131 MB instead of 782 MB; forced RLS on the new table, per-tenant copy, transactional rewrite, rollback restores bit-identical values; the export format (`chunks.ndjson`) is unchanged |
| Narrow vector ranking | `knowledge/retrieve.py` | Distance once per row; full rows for the top 30 only |
| Admission control | `api/admission.py` (new), `api/app.py`, `config.py` | Retrieval and compute classes, global cap = thread-pool size, 0.5 s bounded queue (12), 503/429 + Retry-After, work-conserving per-workspace share (SEC-P2-11) |
| Timeouts | `db.py`, `knowledge/retrieve.py`, `api/app.py`, worker `main.py` | statement_timeout 30 s for serving roles, 8 s per retrieval transaction, 5 s pool wait; all answer 503 with Retry-After; owner connections and the worker unbounded |
| Bounded listings | `api/routes_core.py`, `api/routes_decisions.py`, `api/schemas.py`, `packages/contracts/*` | `/inventory` and `/documents` at most 5,000 rows, limit/offset, totals; documents chunk count by one grouped scan |
| Metrics | `metrics.py` (new), `api/app.py`, `api/deps.py` | Prometheus text at `/metrics` with a bearer token: per-route latency/counts, admission, pool, connections, statement timeouts, job/outbox depth, per-workspace use |
| Worker reliability | `actions/service.py`, `supplylens_worker/main.py` | Dead letter (UNKNOWN_OUTCOME + alert) after 8 interrupted dispatches; per-workspace isolation; ≤ 10 dispatches per workspace per tick |
| Web (overload UX) | `lib/api.ts`, `app/providers.tsx`, `components/connection-banner.tsx`, `app/(app)/inventory/page.tsx` | "SupplyLens is busy" banner; reads retried after Retry-After; truncated inventory says so |
| Load tooling | `scripts/loadtest/run_load.py` (macOS sampler, `--compute-users`, transport-error types), `overload_probe.py` (`--tenant/--email/--tag`) | Reproducible on the hardware available |

## 3. Results (before → after, same machine; full tables in `docs/operations/load-test.md`)
| Retrieval rate | Retrieval p95 | Metadata p95 | Served | PostgreSQL cores |
|---|---|---|---|---|
| 5/s | 256 → **157 ms** | 44 → 52 ms | 4.8/s → 4.8/s | 1.09 → 0.67 |
| 12/s | 1,953 → **177 ms** | 138 → 63 ms | 7.6/s → **11.2/s** (0 refused) | 3.84 → 1.59 |
| 16/s | 1,692 → **442 ms** | 148 → 117 ms | 8.2/s → **14.8/s** (0 refused) | 4.09 → 3.55 |
| 20/s | 1,552 → 978 ms | 119 → 131 ms | 9.0/s → **15.3/s** (253 × 503) | 4.46 → 4.18 |
| 5/s + 3 planners | 473 → 399 ms | 207 → 201 ms | 4.8/s | 1.25 → 0.85 |

Single requests: lexical 54 → 29 ms, vector 155 → 113 ms. Burst of 120 (60 concurrent): 9 accepted, 111 refused within
0.5 s, recovery immediate (223 ms). ARC-07 on this machine: met with wide margin at 5 req/s and up to 16 req/s.

## 4. Tests run
| Suite | Result |
|---|---|
| ruff, `uv lock --check`, hosted pin check | pass |
| pytest (full) | 398 → **414 passed, 6 skipped** (Keycloak; 413 before the hosted-migration regression test) |
| `tests/test_phase3_performance.py` | 15 passed (exposed one defect in the new share rule, fixed) |
| Migration rehearsal (0005 → 0009 → 0010 → rollback → head) | vectors bit-identical |
| Contracts, tsc, `next build` | pass |
| Playwright (disposable stack) | 114 → **116 passed, 2 skipped** (×2) |
| Load matrix before/after, burst probe | P3-E04, P3-E06, P3-E07 |

## 5. Remaining bottlenecks and infrastructure requirements
- **Vector scan** (PERF-P3-09): 781 MB per search at 100,000 chunks; the next step is an ANN index (HNSW with iterative
  scans under RLS) or halfvec, each with the retrieval studies (R1/R2) re-run before adoption.
- **Lexical scan** stays linear in a workspace's chunks under RLS (D-035); per-tenant partitions or a reviewed
  LEAKPROOF/SECURITY DEFINER design are the only routes to the index, both owner decisions.
- **Compute in the API process** (PERF-P3-08): run forecasts/scenarios in separate worker processes or a compute service
  before many planners share one instance.
- **Per-process limits** (PERF-P3-10): caps × instances on serverless; cluster-wide admission needs shared state (Redis or
  PostgreSQL) — with P1-OPS-01.
- **Infrastructure for a real claim:** the declared 8 vCPU / 32 GiB host (EXT-04), PostgreSQL sized for it
  (`shared_buffers` ≥ 25 % RAM so the 0.9 GB of chunk data stays resident), a pooler that keeps
  `plan_cache_mode=force_custom_plan`, real `bge-m3` embeddings, a metrics scraper with alerting on the runbook series.

## 6. Hosted demo
Migration 0010 reaches Neon through the temporary setup token (PD-009, PD-016). **The first attempt failed** (P3-E14):
Neon's owner role bypasses row-level security, so the per-workspace copy saw every workspace on every pass and hit a
duplicate key. The transaction rolled back (schema stayed at 0009, demo unaffected). The copy now also filters
`tenant_id = t`, and a new rehearsal migrates as a role that bypasses RLS (P3-E15). Lesson: local rehearsals ran with an
owner bound by RLS; hosted owners may not be — data migrations must be correct under both. Results of the retried
migration and the live checks are in EVIDENCE. `/metrics` stays absent on the demo (no token configured).

## 7. Next actions
1. Web robustness (deferred by PD-014): P1-FE-01, P1-FE-02 rest, P2-FE-03…08, P2-QA-01/02, P3-FE-09/10.
2. Phase 4 (data protection and retrieval quality) — include PERF-P3-09 with the retrieval study re-run.
3. Re-run this matrix on the declared profile with real embeddings when the owner provides it.
