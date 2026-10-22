# SupplyLens decision log

| ID | Date | Decision | Reason | Alternatives | Status |
|---|---|---|---|---|---|
| D-001 | 2026-10-21 | Treat the specification stack as proposed defaults | From the pack | — | Superseded by D-002+ |
| D-002 | 2026-10-21 | Repository at `SupplyLens/` root; original packs and ZIPs left untouched and git-ignored | Owner choice | Build inside pack folder | Accepted (owner) |
| D-003 | 2026-10-21 | UCI Online Retail II is the only public dataset admitted in phase 1; M5 skipped | Owner choice; M5 is non-commercial and needs owner rule acceptance | Full core profile | Accepted (owner) |
| D-004 | 2026-10-21 | No generative LLM; extractive answers and deterministic agent nodes | Owner choice | Local LLM (Ollama), hosted LLM API | Accepted (owner) |
| D-005 | 2026-10-21 | Local bge-m3 (Ollama, 1024-d) for embeddings, lexical fallback | Owner choice; keeps data local | No neural models | Accepted (owner) |
| D-006 | 2026-10-21 | Bold visual direction on the spec palette; signature = dual-clock rail | Owner chose "bold"; the two clocks are the product's differentiator | Minimal enterprise | Accepted (owner) |
| D-007 | 2026-10-21 | Native dev runtime (Homebrew PG17 + pgvector), compose later | colima VM has 2 CPU/2 GB | Docker-first | Accepted |
| D-008 | 2026-10-21 | One `supplylens` Python package shared by API and worker; ML/opt as sibling packages | Spec: shared domain services, separate processes | Microservices | Accepted |
| D-009 | 2026-10-21 | Memberships, tenants, users are control-plane tables without RLS, read-only to the app role | Sign-in must list a user's tenants before tenant context exists | RLS + SECURITY DEFINER lookup | Accepted |
| D-010 | 2026-10-21 | Quarantine exact duplicate sale lines (keep first) and cross-sheet overlap rows | Publisher sheets overlap 1–9 Dec 2010; duplicates inflate the target | Keep all rows | Accepted |
| D-011 | 2026-10-21 | Non-merchandise codes (POST, D, M, fees…) quarantined via code pattern `^\d{5}[A-Za-z]{0,3}$` | Not products; documented in report | Hand list | Accepted |
| D-012 | 2026-10-21 | Workspace as-of = 2011-12-08 23:59 UTC (9 Dec is partial) | Avoid partial-day origin | 9 Dec | Accepted |
| D-013 | 2026-10-21 | UCI operational layer is simulated from assumption set `uci-sim-ops v1` (seed 20111208): purchase cost = 45–65% of median selling price, 4 fictional suppliers, generated agreements labelled SIMULATED, two amendments | Source has sales only (BUS-003, ML-007) | Leave planning unavailable | Accepted |
| D-014 | 2026-10-21 | Reference case added to Demo workspace as fictional documents (spec chapter 4 values) | Make EXE-003 visible in the UI | Tests only | Accepted |
| D-015 | 2026-10-21 | Replenishment need = q50 path + assumed safety days; q90 sum shown only as uncalibrated reference | Spec: summing daily quantiles is not a calibrated lead-time quantile | Sum q90 | Superseded by D-024 |
| D-016 | 2026-10-21 | Planner allows explicit shortfall with an assumed penalty in investigations; reference case runs with shortfall disallowed | Budget-constrained portfolios are otherwise always infeasible | Hard coverage only | Accepted |
| D-017 | 2026-10-21 | Dev sign-in via signed HttpOnly cookie, CSRF header, same-origin proxy through Next | OIDC not configured; spec forbids home-grown passwords (none used) | — | Accepted (dev only) |
| D-018 | 2026-10-21 | GET endpoints accept `?ws=` for the workspace (EventSource cannot set headers); mutations still require the header | SSE requirement | Polling | Accepted |
| D-019 | 2026-10-21 | Web dev server on port 3100 | Port 3000 used by another local project | — | Accepted |
| D-020 | 2026-10-21 | Light-theme accent darkened to #0F6B55 and risk to #8A5208 | axe measured 4.39:1 and 4.01:1 on soft chips | Larger text | Accepted |
| D-021 | 2026-10-21 | Owner instruction "build everything e2e": admit the core datasets the owner had downloaded (ACORD, CUAD, World Bank, InventoryBench) | Owner's later instruction supersedes D-003 scope | Stay UCI-only | Accepted (owner) |
| D-022 | 2026-10-21 | Contract research workspace for public corpora; never joined to UCI or fictional suppliers | Keep unrelated domains separate (README_DATASETS) | Load into UCI workspace | Accepted |
| D-023 | 2026-10-21 | LightGBM and PyTorch run in separate processes (TCN via `python -m supplylens_ml.tcn`) | Both bundle OpenMP; loading both crashes (OMP #15); KMP_DUPLICATE_LIB_OK is unsafe | Env-var workaround | Accepted |
| D-024 | 2026-10-21 | Replenishment basis = sum of daily q90 over the window (labelled heuristic) | Study S1: median-based targets under-stock heavily on heavy-tailed sales | q50 + safety days | Superseded by D-032 |
| D-025 | 2026-10-21 | Champion = TCN by frozen validation rule even though TCN vs LightGBM is not significant on test | Selection rule fixed before test scoring | Pick on test | Accepted |
| D-026 | 2026-10-21 | Trained models refuse forecast origins before their training cutoff; decision flows fall back to seasonal naive and say so | Prevent replay leakage | Allow with warning | Accepted |
| D-027 | 2026-10-21 | InventoryBench scored only with its unmodified official evaluator at pinned commit 62b1f11, run with `python -I` | DAT-005: pin and inspect evaluator | Re-implement scoring | Accepted |
| D-028 | 2026-10-21 | Retrieval abstains when named identifiers appear in no permitted result | Unknown-product questions must not be answered from a neighbour | Always answer | Accepted |
| D-029 | 2026-10-21 | pgvector must be created by a superuser before restore; restore list excludes EXTENSION entries | First restore drill failed on this | — | Accepted |
| D-030 | 2026-10-21 | Linux containers use PyTorch CPU wheels via a uv index scoped to `sys_platform == 'linux'` | Default Linux wheel pulls multi-GB CUDA libraries | CUDA image | Accepted |
| D-031 | 2026-10-21 | Model promotion is an audited tenant-admin action requiring a recorded evaluation | Spec: promotion via evaluation; audit | Automatic only | Accepted |
| D-032 | 2026-10-21 | Replenishment need = service-level quantile of demand over lead time + coverage (lead-time-demand model), replacing the summed-q90 heuristic (D-024) | Summed q90 over-covers (99-100 % in simulation, 50-60 % more stock); the model hits within 2-5 points of its target with measured day-to-day dependence. Simulation-checked only; not validated on real retail history | Keep summed q90; train a lead-time-demand network | Accepted, revisit on real data |
| D-033 | 2026-10-21 | Database connections force custom plans (`plan_cache_mode=force_custom_plan`) | Generic plans re-parsed the search text and query vector per row: 0.75 s became 8 s per retrieval (load test) | Leave auto and rely on pool settings | Accepted |
| D-034 | 2026-10-21 | `chunks.embedding` is stored inline; `body` and `tsv` are `STORAGE MAIN` (migration 0006) | 4 KB vectors pushed text out of line; lexical scan 3.1 s to 0.24 s at 100,000 chunks | Separate embeddings table | Accepted |
| D-035 | 2026-10-21 | Full-text search keeps row-level security and accepts a sequential scan of the tenant's chunks | The GIN index cannot be used under RLS (operator not leakproof); weakening RLS for speed was rejected | SECURITY DEFINER search bypassing RLS; per-tenant partitions | Accepted, cost grows linearly with a tenant's chunks |
| D-036 | 2026-10-21 | Cross-encoder reranking is optional, off by default, and only reorders candidates the SQL filters admitted; supersession stays a hard rule | Weights are not reachable from the build environment, so it cannot be evaluated here | Make it default | Accepted, unevaluated |
| D-037 | 2026-10-22 | Push session-4 work straight to `main` | Owner decision (session 4 question) | Feature branch + PR | Accepted (owner) |
| D-038 | 2026-10-22 | Onboarding scope = three CSV templates (sales, stock, terms) with upload, map, validate, quarantine and immutable publish into a new workspace | Owner decision; smallest supported source that removes developer-driven onboarding (S18) | ERP connector first; Excel | Accepted (owner) |
| D-039 | 2026-10-22 | Identity = local Keycloak in Docker (OIDC code + PKCE, role claims, deactivation) | Owner decision; verified locally only, not qualified against a corporate IdP | Stay on dev accounts | Accepted (owner) |
| D-040 | 2026-10-22 | Illustration pack: publish 13 of 16 derivatives; A02, A13, A16 use HTML/icon fallbacks | Owner decision; those three contradict their briefs (document lines, joined suppliers, kraft cartons) | Regenerate art; publish all | Accepted (owner) |
| D-041 | 2026-10-22 | Generative inference stays disabled | Standing owner decision carried forward | — | Accepted (owner) |
| D-042 | 2026-10-22 | Forecast study protocol 2.0.0: corrected baseline, rolling test origins 2011-10-13 and 2011-11-10, validation 2011-08-18 and 2011-09-15; reported as a corrected re-run, not a fresh confirmatory test | Protocol 1.0.0 used the defective baseline (F01) and already looked at both windows | Treat v1 as valid; drop the study | Accepted |
| D-043 | 2026-10-22 | Declared pilot scale: 60 SKUs per run, single-location SKUs only; explicit lists over the limit are rejected, implicit truncation is reported, multi-location SKUs are excluded with a reason | S21: silent slicing and location collapse | Paginate runs; sum across locations | Accepted, revisit with SKU-location planning |
| D-044 | 2026-10-22 | Structured term values (price, MOQ, multiple, lead time) are visible to every workspace reader; the link to a restricted source document (title, section, excerpt, labels) follows the document's ACL | S10 asked for an explicit policy; operational values are needed to plan, document text is not | Terms inherit document ACL | Accepted |
| D-045 | 2026-10-22 | Open supply = SupplyLens orders dated on or after the stock snapshot and on or before the decision date (business dates), net of receipts and cancellations | S12; research workspaces run on a simulated clock, so wall time cannot be used | Wall-clock confirmation time; ERP open-order feed | Accepted |
| D-046 | 2026-10-22 | Idempotent operations record their response inside the business transaction; the web client keeps one key per user intent until it succeeds | F05 crash-after-commit window | Outbox for every route | Accepted |
| D-047 | 2026-10-22 | Read-back verification compares line multisets, prices, units, need-by and status; any difference leaves the action CONFIRMED with a mismatch reason, never RECONCILED | F06 | Total-only comparison | Accepted |
| D-048 | 2026-10-22 | Migration 0007 rolls back by parking its tables and identity values in schema `retired_0007` and restores them on the next upgrade | Rollback must not destroy open orders, receipts or imports | Refuse downgrade with data | Accepted |
| D-049 | 2026-10-22 | The production profile fails closed: no dev sign-in, no default secrets or owner DB credentials, Secure cookies, OIDC required | S09 | Warn only | Accepted |

## Authorisation scope recorded
Routine local development, local databases, dataset download of UCI (owner-approved); use of the core datasets the
owner downloaded (owner instruction "build everything e2e"). No deployments,
spending, external writes or credentials were used. The sandbox ERP is local only.
