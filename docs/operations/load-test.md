# Load test on the reference profile (ARC-07, BUS-015)

**Verdict, stated plainly.**

* The declared target (ARC-07: 20 concurrent interactive users, 5 retrieval requests/s, p95 metadata reads < 500 ms,
  p95 retrieval < 2 s, 100,000 chunks, 1,000,000 transaction rows) was **not met at 5 retrieval requests/s on the machine
  available (4 vCPU, 16 GiB)**. It was **met at 4 requests/s**, cold and warm. The declared profile is 8 vCPU / 32 GiB, which
  was not available; no claim is made for it beyond the arithmetic in "Extrapolation".
* The first run, against the code as it was before this work, **collapsed** (metadata p95 38 s, 59 % of retrieval requests
  timed out). Five defects found by that run were fixed (see "What the load test found").
* Capacity is approved here **only for the workload and machine measured** (BUS-015 says exactly this).

## Phase 3 re-run, before and after (2026-10-23, a different machine)

**Machine:** Apple M4 Pro laptop (12 cores: 8 performance + 4 efficiency; 24 GB), macOS 27, PostgreSQL 17.11 (Homebrew,
`shared_buffers` 128 MB, `work_mem` 4 MB, `max_parallel_workers_per_gather` 2 — defaults, **not** the compose file's 0),
pgvector 0.8.6, Python 3.12.13, one uvicorn process. API, PostgreSQL, the embedding **stub** (`fake_ollama.py`) and the
driver share the machine. Data: `seed_reference.py` (`supplylens_load`, one workspace, 100,000 chunks with 1024-d vectors,
1,008,206 sales rows, 2,000 SKUs, 20 users). Warm: a 60–120 s warm-up run first; PostgreSQL was not restarted (it serves
other local databases) and the OS cache was not dropped. Same driver, durations and data before and after.
**Before** = `main` @ `2365f49`; **after** = Phase 3 (migration 0010, admission control, timeouts). CPU = mean cores.

| Retrieval rate (duration) | Version | Metadata p50 / p95 / p99 ms | Retrieval p50 / p95 / p99 ms | Retrieval served | Refused | PostgreSQL / API cores |
|---|---|---|---|---|---|---:|
| 5/s (180 s) | before | 12 / 44 / 71 | 241 / 256 / 288 | 901 of 901 | 0 | 1.09 / 0.11 |
| 5/s (180 s) | after | 11 / 52 / 87 | **151 / 157 / 173** | 901 of 901 | 0 | **0.67** / 0.11 |
| 8/s (75 s) | before | 16 / 73 / 127 | 336 / 678 / 1,002 | 599 of 601 | 2 × 503 | 2.38 / 0.17 |
| 8/s (75 s) | after | 11 / 52 / 82 | 149 / 158 / 180 | 601 of 601 | 0 | 1.00 / 0.14 |
| 12/s (75 s) | before | 22 / 138 / 230 | 711 / 1,953 / 2,362 | 619 of 900 (7.6/s) | 280 × 503 | 3.84 / 0.19 |
| 12/s (75 s) | after | 12 / 63 / 92 | 156 / 177 / 207 | 900 of 900 (11.2/s) | 0 | 1.59 / 0.18 |
| 16/s (75 s) | before | 20 / 148 / 232 | 714 / 1,692 / 2,213 | 666 of 1,200 (8.2/s) | 534 × 503 | 4.09 / 0.20 |
| 16/s (75 s) | after | 17 / 117 / 142 | 263 / 442 / 715 | 1,200 of 1,200 (14.8/s) | 0 | 3.55 / 0.30 |
| 20/s (75 s) | before | 18 / 119 / 147 | 655 / 1,552 / 1,826 | 726 of 1,499 (9.0/s) | 773 × 503 | 4.46 / 0.21 |
| 20/s (75 s) | after | 18 / 131 / 164 | 453 / 978 / 1,150 | 1,246 of 1,499 (15.3/s) | 253 × 503 | 4.18 / 0.31 |
| 5/s + 3 planners looping 60-SKU scenarios (120 s) | before | 37 / 207 / 306 | 296 / 473 / 565 | 601 of 601 | 0 | 1.25 / 0.76 |
| same | after | 46 / 201 / 282 | 202 / 399 / 480 | 601 of 601 | 0 | 0.85 / 0.88 |

Metadata failures: one request per 5/s "after" run and one in the "before" mixed run ended without any HTTP response
(client status 599, 12 ms; nothing in the API log). Cause **unverified**; consistent with a keep-alive race (uvicorn closes
idle connections after 5 s, users think 4–8 s). The driver now records the exception type. Scenario runs: ~1.5 s each;
the 429s in the mixed runs are the per-user scenario rate limit (20/min), not admission control.

**Burst probe** (`overload_probe.py --tenant load-ref`, 120 searches, 60 concurrent, after only): 9 accepted (p95 1.0 s),
111 refused with 503 (p95 0.52 s: the 0.5 s queue wait), the next request 200 in 223 ms right after the burst.

What changed the numbers (single-request timings, same machine, same queries):
* **Heap width** (migration 0010): vectors moved to `chunk_vectors`. The chunks heap fell from 782 MB to 131 MB, so the
  full-text scan, which still cannot use its index under row-level security (D-035), reads text only: 54 → 29 ms. The
  vector table is still 781 MB — a 1024-d float vector plus tuple header exceeds half an 8 KB page, so one vector per
  page either way (PERF-P3-09).
* **Vector query**: top-30 ranked on the narrow table with the distance computed once, full rows fetched for 30: 155 →
  113 ms. Hybrid search in-process: 140 ms median.
* **Admission** (D-069): separate retrieval/compute caps, a 0.5 s bounded queue, work-conserving workspace shares, the
  thread pool sized to the cap, 503/429 with Retry-After; pool and statement timeouts (D-070).

Against ARC-07 on this machine: 20 users, 5 retrieval/s, metadata p95 52 ms (< 500), retrieval p95 157 ms (< 2 s) —
**met with wide margin, and met up to 16 req/s**; at 20 req/s the service serves ~15/s and refuses the rest at once.
This is a development laptop with a stubbed embedder; it is **not** the declared 8 vCPU / 32 GiB profile and says nothing
about production. Raw files: `artifacts/reports/loadtest-p3-*.json`, `overload_probe_p3-after-loadref_*.json`,
`metrics-sample-p3-loadtest.txt`.

## Setup (everything on one machine)

| | |
|---|---|
| Host | 4 vCPU (Intel Xeon @ 2.1 GHz), 16 GiB, Linux 6.18; API, worker, PostgreSQL, embedding stub and load driver all on it |
| Software | PostgreSQL 16.15 with pgvector 0.6.0 (`shared_buffers` 128 MB default, `effective_cache_size` 4 GB, `work_mem` 4 MB), API as shipped (one uvicorn process), Python 3.12 |
| Data (`scripts/loadtest/seed_reference.py`, workspace `load-ref`) | 100,000 chunks with 1024-d vectors in 2,000 documents; 1,007,629 daily sales rows (2,000 SKUs × 560 days, ~10 % of days absent); 2,000 stock positions; 4,000 supplier terms. **Synthetic**: pseudo-English text with a skewed vocabulary, random unit vectors |
| Users | 20 accounts (5 planners, 15 viewers), one session each. Rate limits are per user, so sharing one account would test the limiter |
| Interactive traffic | Each user opens a screen (2–3 parallel reads: overview, inventory, exceptions, product, documents, runs, data) then thinks 4–8 s. About 6 metadata reads/s in total |
| Retrieval traffic | `GET /evidence/search`, open loop at a fixed rate spread over the users, 2 domain words + 0–1 mid-frequency word (hybrid: lexical + exact vector search + fusion) |
| Latency | measured at the client per request, send to last byte |
| Embeddings | **a stub** (`fake_ollama.py`, ~10 ms, deterministic vectors). Real embedding-model latency is **not included** (ARC-07 excludes external model calls but asks that they be benchmarked separately; no model weights are reachable from this environment, so that benchmark was not run) |
| Cold | PostgreSQL and API restarted before the run; **the operating-system page cache was not dropped** (not permitted), so "cold" means empty `shared_buffers` and fresh processes |

Reproduce: `scripts/loadtest/seed_reference.py`, then `scripts/loadtest/run_reference.sh` (settings in the script header).
Raw results: `artifacts/reports/loadtest-*.json`; `scripts/loadtest/summarise.py` prints them.

## Results

All figures are milliseconds. Metadata = every non-search read. "Fail" = no HTTP 200 (timeouts included).

| Run | Retrieval rate | Metadata p50 / p95 / p99 | Retrieval p50 / p95 / p99 | Fail | PostgreSQL cores (mean) | Meets ARC-07 |
|---|---:|---|---|---|---:|---|
| **Before fixes**, cold, 90 s (`baseline-cold`) | 5/s | 8,765 / 38,047 / 55,135 | 24,240 / 41,223 / 52,533 | 34 of 167 metadata, 267 of 451 retrieval | 3.46 | no |
| After fixes, **cold**, 90 s (`final-4rps-cold`) | 4/s | 28 / 174 / 241 | 856 / 988 / 1,057 | 0 of 925 | 2.82 | **yes** |
| After fixes, **warm**, 240 s (`final-4rps-warm`) | 4/s | 28 / 165 / 225 | 850 / 970 / 1,084 | 0 of 2,485 | 2.91 | **yes** |
| After fixes, cold, 90 s (`final-5rps-cold`) | 5/s | 921 / 3,595 / 4,091 | 5,789 / 8,783 / 9,475 | 1 of 928 | 3.26 | no |
| After fixes, warm, 240 s (`final-5rps-warm`) | 5/s | 3,298 / 12,338 / 13,630 | 12,918 / 20,152 / 21,447 | 2 of 2,075 | 3.43 | no |

Retrieval-rate sweep, 75 s each, after the plan fix (`sweep2`, PostgreSQL default parallel query) and with
`max_parallel_workers_per_gather = 0` (`sweep3-noparallel`):

| Rate | default: metadata p95 | default: retrieval p95 | no-parallel: metadata p95 | no-parallel: retrieval p95 |
|---:|---:|---:|---:|---:|
| 1/s | 117 | 518 | – | – |
| 2/s | 156 | 522 | – | – |
| 3/s | 182 | 712 | 161 | 961 |
| 4/s | 434 | **3,517** | 174 | 971 |
| 5/s | 8,601 | 16,300 | 2,224 | 7,398 |

Parallel query is faster for one request but lets concurrent requests starve each other of workers; with it disabled
latency is flatter and 4/s holds. The shipped compose file sets it to 0; the "final" runs used it.

Resources at 4/s warm: API 0.30 cores / 285 MB peak RSS; PostgreSQL 2.91 cores / 2.2 GB; driver 0.03 cores.
**Cost (BUS-015).** No price list exists for a deployment, so cost is reported as CPU: about 320 core-seconds per 1,000
requests of this mixed traffic, of which retrieval is ≈ 0.7 core-seconds per request at 100,000 chunks and metadata reads
≈ 0.02–0.1. Multiply by your instance price.

### Batch and compute-heavy work, measured separately (one user, nothing else running; `loadtest-final-batch`)

| Work | Result |
|---|---|
| Forecast, 200 SKUs, seasonal naive | p50 2.6 s (5 runs) |
| Forecast all 2,000 SKUs (10 requests of 200) | **25 s** |
| Scenario (forecast + dependence + CP-SAT plan), 200 SKUs | p50 11.1 s (3 runs) |
| Scenario over the whole catalogue (the API plans ≤ 200 SKUs per run, so 10 runs) | **98 s** |
| Agent run, 50 SKUs, to "waiting for approval" | 2.6 s and 3.7 s |
| Model training | **not measured here** (needs the licensed retail history; the study timings are in `docs/research/results.md`) |
| External model (embeddings / LLM) | **not measured** (no weights reachable; the agent is deterministic by the owner's choice (DECISIONS.md)) |

These run inside the API process (0.9 core during the batch), so a batch and interactive traffic compete for it. They
were **not** measured together.

## What the load test found (all fixed unless stated)

1. **Inventory and exceptions were slow at 2,000 SKUs** (0.57 s and 0.60 s warm, single user; 3.4 s on first call): a
   correlated sub-query counted supplier terms per SKU with no index, and the 28-day sales aggregate scanned the whole
   table. Now a grouped join and two indexes (migration 0006): **0.06 s and 0.036 s**.
2. **Retrieval got ten times slower on the 11th request** (0.75 s → 8.2 s) because the database driver prepares a statement
   after five uses and PostgreSQL then switched to a generic plan, in which the search text and the query vector were
   re-evaluated for every scanned row. Connections now force custom plans (`db.py`, `tests/test_db_config.py`).
3. **Full-text search cannot use its index under row-level security** (the `@@` operator is not leakproof): 25 ms without
   RLS, 3.2 s with it, because every row's `tsvector` is evaluated. Not fixable without weakening RLS; reduced by keeping
   the tsvector inline (below). Search cost therefore grows linearly with a tenant's chunk count. **Open.**
4. **4 KB vectors pushed the text columns out of line**, so a lexical scan detoasted every row (3.1 s). `body` and `tsv`
   are now `STORAGE MAIN` and the vector `PLAIN` (0.24 s lexical, and the exact vector scan fell from 610 ms to ≈ 210 ms
   parallel / 335 ms single-process).
5. **No back-pressure.** Past capacity the service does not shed load: requests queue, the connection pool (10 + 10, 30 s
   timeout) errors, and the system took minutes to recover after the 5/s run; the first attempt to start the next phase failed at login.
   Fixed on 2026-10-22 (503 shedding, DEF-10) and extended in Phase 3 (classes, queue, workspace shares, timeouts).
6. The API limits a plan to 200 SKUs (`422 select between 1 and 200 SKUs`; 60 since D-043), and `/inventory` and `/documents` return the
   whole catalogue unpaginated (≈ 0.9 MB at 2,000 SKUs). Within target here; they will not scale far beyond it.
   Bounded with limit/offset in Phase 3 (D-071).

## Extrapolation (labelled as such)

At 4/s warm the whole machine used about 3.3 of 4 cores (PostgreSQL 2.9, API 0.3, others 0.1); 5/s needs roughly
4.2 cores of that mix, hence the collapse on 4. An 8-vCPU host would then run 5/s at about half utilisation, if the
workload scales with cores and memory bandwidth, and if PostgreSQL's shared buffers and connection limits are sized for it.
That is arithmetic, not a measurement: **ARC-07 stays "not met on the declared profile" until it is run there.**

## What this does not show

* Behaviour with real embeddings (vector clustering affects any future approximate index; latency of the embedding call).
* Real text: the corpus is synthetic, so lexical selectivity is an assumption (domain words at ~5 % of chunks).
* Several API processes or replicas, a connection pooler, or storage slower than this host's.
* Interactive traffic concurrent with batch work, or with ingestion.
* Sustained load beyond 4 minutes, or memory growth over hours.
