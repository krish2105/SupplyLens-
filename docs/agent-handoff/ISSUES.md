# Agent handoff — issue register

Opened in Phase 0 (2026-10-22, commit `9fcbedb`). Severity scale: see DECISIONS.md PD-005.
**Label:** VERIFIED = the auditing session re-read the cited code (and, where noted, ran a probe or command);
PLAUSIBLE = reasoning from code that was not reproduced; needs investigation before fixing. **Status:** `open`
unless a later phase changes it — update the status column and add the evidence ID; never delete a row.

The 22 earlier CTO-audit findings (F01–F08, S09–S22) are tracked in `docs/remediation/REGISTER.md` and are not
repeated. Where a Phase 0 finding is a residual of one of them it says so.

## Summary

| ID | P | Area | Title | Label | Status |
|---|---|---|---|---|---|
| P0-SEC-01 | P0 | Hosted demo / authz | Public passwordless `tenant_admin` can alter the shared live demo (memberships, workspaces, imports) | VERIFIED (code + live account list) | fixed, verified live (P1-E14) |
| P0-PLAN-01 | P0 | Planning | Default `allow_shortfall=True` with 500-minor penalty makes "order nothing" optimal for any unit cost ≥ 5.00 | VERIFIED (code + solver probe) | fixed (P1-E03) |
| P1-PLAN-02 | P1 | Planning | Lead-time demand sized with the *fastest* supplier's lead time; optimiser then buys from slower one | VERIFIED (code + probe) | fixed (P1-E03) |
| P1-ACT-01 | P1 | Actions | An action that went STALE at dispatch cannot be re-approved (outbox UNIQUE violation → 500) | VERIFIED (code + schema) | fixed (P1-E03) |
| P1-ACT-02 | P1 | Actions / planning | Orders not yet RECONCILED (QUEUED, SUBMITTED, UNKNOWN_OUTCOME, CONFIRMED-mismatch) are invisible to planning → duplicate purchasing; CONFIRMED has no exit | VERIFIED (code) | fixed (P1-E03, P1-E10) |
| P1-SEC-02 | P1 | Hosted demo / secrets | Hosted API function derives and holds the Neon **owner** DSN at runtime | VERIFIED (code) | fixed in code; residual: platform still injects owner vars (P1-E13) |
| P1-FE-01 | P1 | Web | Workspace defaults to `uci-research` and is never reconciled with the user's memberships | VERIFIED (code); user impact INFERRED | fixed: the shell moves to a workspace the user belongs to; no-workspace screen (P4-E05, P4-E07) |
| P1-FE-02 | P1 | Web | Receipt quantities keyed by `sku_id` on SKU@location rows → booking against the wrong location | VERIFIED (code) | fixed: inventory API one row per SKU@location, UI keyed by SKU@location, stock by location (P4-E03, P4-E07) |
| P1-IAM-01 | P1 | Identity / SaaS | One platform-wide IdP, roles from a `<slug>:<role>` claim, link-by-email, no SCIM; not qualified against a corporate IdP | VERIFIED (code); qualification = external | open |
| P1-OPS-01 | P1 | Platform | No production deployment architecture: no IaC, no staging, no secret manager, single uvicorn process, no SLOs/dashboards/on-call | VERIFIED (absence) | open |
| P1-SAAS-01 | P1 | SaaS | No self-serve signup, billing, plans, usage metering or tenant provisioning outside an existing admin | VERIFIED (absence, grep) | open |
| P1-PROC-01 | P1 | Process | `main` is unprotected (no required checks/reviews) on a public repo; work pushed directly (D-037) | VERIFIED (`gh api …/protection` 404) | partially fixed: protection on, admins exempt (P1-E15) |
| P2-REL-01 | P2 | Worker | Job whose lease expires on its last attempt stays `RUNNING` forever | VERIFIED (probe P0-E16) | fixed (P1-E03) |
| P2-REL-02 | P2 | Worker | Agent-run execution is not fenced; heartbeat thread dies silently on a DB error → possible double execution / duplicate drafts | PLAUSIBLE | fixed: heartbeat + unique index (P1-E03) |
| P2-REL-03 | P2 | Worker | Single-threaded worker processes tenants serially, one job per tenant per tick; outbox re-claim has no attempt cap or heartbeat | VERIFIED (code); impact PLAUSIBLE | partially fixed: dead letter after 8 interrupted dispatches, per-workspace failure isolation, ≤10 dispatches per workspace per tick (P3-E08); still one thread, no N-tenant load test |
| P2-PLAN-03 | P2 | Planning / temporal | Replays with `effective_date` > `knowledge_cutoff` read stock, open orders, shares, dependence and capacity dated after the cutoff | VERIFIED (code) | fixed (P1-E03) |
| P2-PLAN-04 | P2 | Planning | Dependence (ACF) computed on recorded days as if consecutive calendar days → variance understated | VERIFIED (probe by reviewer; code re-read) | fixed (P1-E03) |
| P2-PLAN-05 | P2 | Planning | Scenario studio plans through unresolved term conflicts (agent path blocks them) | VERIFIED (code) | fixed (P1-E03) |
| P2-ML-01 | P2 | Forecasting | No test of a successful trained-model forecast through the service; missing artifacts raise `artifact_missing` without baseline fallback | VERIFIED (tests); fallback gap PLAUSIBLE | fixed (P5-E05) |
| P2-KNOW-01 | P2 | Retrieval | Abstention fires only for digit-bearing tokens; vector channel has no similarity floor → nearest chunk presented as an answer | VERIFIED (code) | partially fixed: support rule + ambiguity flag (R3, P5-E04); see KNOW-P5-02/03 |
| P2-PRIV-01 | P2 | Onboarding / privacy | Rows quarantined as personal data are stored raw, shown to viewers, and copied into an immutable quarantine table | VERIFIED (code) | fixed for new uploads (SEC-P2-07); old rows not rewritten |
| P2-API-01 | P2 | API | No request-body size limit before multipart parsing (and before auth) | PLAUSIBLE | fixed (SEC-P2-03, P2-E03) |
| P2-FE-03 | P2 | Web | No ESLint, no unit tests; e2e code excluded from typecheck | VERIFIED | fixed: ESLint zero warnings, Vitest (19 tests), e2e typechecked, all in CI (P4-E02, P4-E04) |
| P2-FE-04 | P2 | Web | No `error.tsx` / `global-error.tsx` / `not-found.tsx`; render errors white-screen the app | VERIFIED (absence) | fixed: route, root and global error boundaries, not-found page, shell widget boundaries (P4-E07) |
| P2-FE-05 | P2 | Web | Agent-run start, forecasts, exports, deletion, onboarding, alert ack, retry/reconcile send fresh idempotency keys per click | VERIFIED (code) | fixed: one key per user intent for every mutation by default (P4-E04, P4-E07 double-click tests) |
| P2-FE-06 | P2 | Web | Query errors rendered as endless loading or as empty states on several screens | VERIFIED (code, per reviewer list) | fixed: QueryError on all 24 unhandled queries (P4-E04, P4-E07) |
| P2-FE-07 | P2 | Web | Onboarding mapping state stale when switching batch; unhandled rejections (onboarding, sign-out) | VERIFIED (code) | fixed: batch steps keyed, batch-open and sign-out errors shown, drafts no longer follow the user (P4-E04) |
| P2-FE-08 | P2 | Web | Web Vitals reporter re-registers observers on every route change → duplicated, mislabelled vitals | VERIFIED (code) | fixed: observers registered once, route read at report time |
| P2-QA-01 | P2 | Tests | E2E specs share the Demo reference SKU and run in parallel → order-dependent failure | VERIFIED (P0-E12/E13) | fixed: cross-worker reference-case lock; 3 consecutive full runs clean (P4-E08) |
| P2-PERF-01 | P2 | Performance | Retrieval cost linear in tenant chunks under RLS; declared 5 req/s target not met (4 req/s on 4 vCPU); mobile overview LCP 2.76 s | RECORDED; re-run in Phase 3 on different hardware | partially fixed: per-search cost cut (0010), overload predictable; ARC-07 met on an M4 Pro laptop (P3-E06, P3-E07), **not** on the declared 8 vCPU profile (EXT-04); mobile LCP not addressed |
| P2-QA-02 | P2 | Tests / CI | Lab Web-Vitals thresholds fail on shared CI runners (desktop INP proxy 224 ms > 200 ms on a docs-only commit) | VERIFIED (CI run 39827354915) | fixed locally: median of 3 loads, unchanged targets; CI confirmation in P4-E12 |
| SEC-P2-01 | P1 | Test safety | Destructive fixtures (pytest TRUNCATE, Playwright order cancellation) ran against any configured target | VERIFIED | fixed (P2-E03, P2-E07) |
| SEC-P2-02 | P2 | Sessions | Development sessions were stateless: no revocation on sign-out, no idle timeout | VERIFIED | fixed, verified live (P2-E15) |
| SEC-P2-03 | P2 | Resource limits | No body cap before parsing/auth; unlimited sign-in attempts and admin writes | VERIFIED | fixed; throttle per process (residual) |
| SEC-P2-04 | P3 | Error disclosure | Database error text returned by onboarding routes and integration status | VERIFIED | fixed (P2-E03) |
| SEC-P2-05 | P3 | Object-level authz | Cross-tenant reconcile / alert acknowledge answered 409, not 404 (no oracle) | VERIFIED | fixed (P2-E03) |
| SEC-P2-06 | P2 | Supply chain | Actions by tag, unverified gitleaks download, unpinned pip-audit, unpinned hosted dependencies | VERIFIED | fixed; Docker digests open |
| SEC-P2-07 | P2 | Privacy | = P2-PRIV-01 (personal data stored from CSV uploads) | VERIFIED | fixed for new uploads |
| SEC-P2-08 | P3 | Availability | IdP outage made every OIDC request 500 | VERIFIED (code) | fixed in code; not exercised (no Keycloak) |
| SEC-P2-10 | P3 | Parsing | Oversized CSV field / NUL byte → 500 | VERIFIED | fixed (P2-E03) |
| SEC-P2-11 | P2 | Rate limits | No per-tenant retrieval ceiling or admission control (security review F-05) | RECORDED | fixed per process: work-conserving per-workspace share of each admission class, 429 `workspace_busy` (P3-E08); not cluster-wide |
| SEC-P2-12 | P3 | Audit | Audit trail append-only for the app role but not tamper-evident against the owner role | VERIFIED (grants) | open |
| SEC-P2-13 | P3 | Retention | No retention jobs for auth_sessions, import_rows, web_vitals, alerts | VERIFIED (absence) | open |
| P3-DOC-01 | P3 | Docs | Numeric drift across README / PROJECT_STATUS / TASKS (tests, RLS tables, CI jobs, browser tests) | VERIFIED | fixed in README / PROJECT_STATUS current-state section |
| P3-DOC-02 | P3 | Docs | Contradictory statements (no deployments vs D-050; "current task: session 3"; OIDC "outstanding") | VERIFIED | fixed (root DECISIONS, PROJECT_STATUS, README) |
| P3-PLAN-06 | P3 | Planning | Smaller planner issues (ScaleError escapes explainer; UNKNOWN timeouts trigger extra solves; weekly budget on 21-day plan; stale docstrings) | VERIFIED (reviewer probes; code re-read for budget) | partially fixed: explainer ScaleError, timeout re-solves (P5-E05); budget-period and docstrings open |
| P3-ML-02 | P3 | Forecasting | Model file hashed then re-read by path (TOCTOU); `simulation_study.py` loads models without hash check | VERIFIED (code) | fixed (P5-E05) |
| P3-ONB-01 | P3 | Onboarding | Oversized CSV field / NUL byte → 500; overlap not re-checked at publish; workspace creation not atomic | VERIFIED (parser run by reviewer) / PLAUSIBLE (NUL) | partially fixed: parser errors (SEC-P2-10); publish re-check and atomic workspace creation open |
| P3-SEC-03 | P3 | Security hygiene | Stateless dev sessions not revocable (accepted F-06); CSP `'unsafe-inline'` (accepted F-09); IdP network errors in `confirm_session` uncaught; event stream keeps connect-time role | VERIFIED (code) | partially fixed: dev sessions revocable, IdP outage 503; CSP unsafe-inline and stream role open |
| P3-CI-01 | P3 | Supply chain | GitHub Actions pinned by tag not SHA; base images (`python:3.12-slim`, `node:24-slim`, `pgvector/pgvector:pg17`) not digest-pinned | VERIFIED | partially fixed: actions SHA-pinned, hosted deps pinned (SEC-P2-06); Docker images open |
| P3-FE-09 | P3 | Web | Minor UI issues (forecast Run enabled while role loading; dev copy shown to all; no return path on login; unguarded `JSON.parse` in SSE; tabs without tabpanels; 617–760 KB first-load JS per route; all pages client components) | VERIFIED (reviewer; spot-checked) | partially fixed: Run disabled until the role is known, admin copy, sign-in return path, guarded stream parsing, WAI-ARIA tabs; first-load JS size and client-only pages open |
| P3-OPS-02 | P3 | Deployment | Git-triggered Vercel production builds fail within seconds on every push (the API service's `build/vercel-api` is generated locally, not in git); only CLI deploys succeed | VERIFIED (`vercel ls`, P1-E12) | fixed (P2-E02) |
| P3-FE-10 | P3 | Web | Admin screens do not explain the demo lockdown before a click (the 403 message does) | VERIFIED (code) | fixed: demo lockdown notice and disabled controls before any click |
| PERF-P3-01 | P2 | Retrieval / schema | Inline 4 KB vectors made each chunk row fill an 8 KB page: the full-text scan (no index under RLS, D-035) read 782 MB of vectors per search | VERIFIED (EXPLAIN BUFFERS, P3-E03) | fixed: `chunk_vectors` (migration 0010); chunks heap 131 MB (P3-E05) |
| PERF-P3-02 | P3 | Retrieval | Vector query computed the distance twice per row and carried full chunk rows through the sort | VERIFIED (plan) | fixed: rank on the narrow table, fetch top 30 (P3-E05) |
| PERF-P3-03 | P2 | API | Admission allowed 64 in flight but sync routes ran on 40 threads (hidden queue); pool waits lasted 30 s and ended in 500 | VERIFIED (code) | fixed: thread pool sized to the cap, 5 s pool timeout → 503 Retry-After (P3-E08) |
| PERF-P3-04 | P2 | API | One shared "costly" cap: scenario runs could refuse every search; no queue, no per-workspace bound | VERIFIED (code) | fixed: retrieval and compute classes, bounded queue, workspace share (P3-E08) |
| PERF-P3-05 | P2 | Database | No statement timeout for serving roles; a runaway query held a connection after its caller left | VERIFIED (config) | fixed: 30 s serving, 8 s retrieval, 503 `query_timeout` (P3-E08) |
| PERF-P3-06 | P3 | API | `/inventory` and `/documents` unbounded; documents counted chunks with a sub-query per version | VERIFIED (code) | fixed: bounded with limit/offset, totals, grouped count (P3-E08) |
| PERF-P3-07 | P2 | Observability | No request-latency, saturation, queue-depth or per-tenant metrics | VERIFIED (absence) | fixed: `/metrics` with bearer token (P3-E08, P3-E09) |
| PERF-P3-08 | P2 | Performance | Compute runs inside the API process: 3 planners looping scenarios raise metadata p95 from ~50 to ~210 ms and use 0.8 of a core (GIL) | VERIFIED (P3-E06/E07 mixed runs) | open: targets still met; separate compute workers or processes for production (Phase 6) |
| PERF-P3-09 | P3 | Retrieval | A 1024-d float vector plus tuple overhead exceeds half a page, so the exact vector scan still reads 781 MB per search at 100,000 chunks (≈113 ms) | VERIFIED (relation size) | open: halfvec or an HNSW index change ranking and need the retrieval studies re-run (Phase 4/5) |
| P3-OPS-03 | P2 | Deployment | A push changing only backend code (`services/`, `ml/`, `optimisation/`) did not deploy: Vercel rebuilds a service only when files under its root (`deploy/vercel-api/`) change, and the API code is staged at build time | VERIFIED (66cd20a: CI success, no Vercel status or deployment); cause INFERRED from the service-root rule | fixed: committed `deploy/vercel-api/source.sha256`, re-pinned with `build_api.py --pin`, checked in CI (P3-E16) |
| PERF-P3-10 | P3 | Platform | Admission caps, the sign-in throttle and metrics are per process; N instances admit N × cap | VERIFIED (design, D-069) | open by design; cluster-wide limits belong with P1-OPS-01 |
| FE-P4-01 | P2 | Web | Expert clause labels were fetched and never shown (no control could select one) | VERIFIED (code, git history) | fixed: label viewer (P4-E07 J4) |
| FE-P4-02 | P2 | Web | A draft input (rejection reason) followed the user to the next draft when that one had none saved | VERIFIED (unit test fails on old code) | fixed (P4-E04) |
| FE-P4-03 | P2 | Web | If open order lines failed to load, the receipts card disappeared silently | VERIFIED (code) | fixed |
| FE-P4-04 | P2 | Web / mobile | Command palette trigger hidden below tablet width: no search or jump on phones | VERIFIED (mobile-safari run) | fixed |
| FE-P4-05 | P2 | Web | A session ended elsewhere left "session ended" boxes instead of going to sign-in | VERIFIED (J1) | fixed (D-073) |
| FE-P4-06 | P1 | Product | Documents could be ingested only by bootstrap/CLI: journey 4 had no product path | VERIFIED (route list) | fixed: `POST /api/v1/documents` + Policies form (D-076, P4-E03, P4-E07) |
| FE-P4-07 | P3 | Web / performance | Mobile CLS on /inventory rose to 0.14-0.17 after a Phase 4 change (snapshot label wrapping) | VERIFIED (layout-shift sources) | fixed: 0.04-0.07 (P4-E09) |
| FE-P4-08 | P3 | Web / a11y | Under heavy parallel CPU load focus was lost right after page load in ~1 of 10 runs; not reproducible single-threaded; the app has no focus-moving code | OBSERVED; cause UNVERIFIED | open: test acts after load; investigate with a trace on CI |
| QA-P4-01 | P2 | Tests | A first draft of the receipts journey booked receipts on the shared reference SKU, permanently changing the local `supplylens_p0e2e` reference case | VERIFIED | fixed: isolated onboarded workspace (PD-019); polluted DB left in place (PD-018) |
| ENV-P4-01 | — | Environment | Bundled Firefox does not start on macOS 27 here | VERIFIED | CI only (PD-020) |
| OPS-P4-01 | P2 | Deployment | The hosted-API source digest hashed only tracked files, so a local check passed while CI (seeing newly committed reports) failed | VERIFIED (P4-E12) | fixed: untracked files included, test output excluded |
| ML-P5-01 | P1 | Forecasting | Panel dates reloaded in the wrong unit: the TCN's weekday inputs were constant in training and serving | VERIFIED (probe) | fixed; F1 re-run 2.1.0, TCN 2.0.0 retired (P5-E02, P5-E03) |
| ML-P5-02 | P2 | Forecasting | Products younger than the trained model's window were dropped from forecasts | VERIFIED (code) | fixed (P5-E05) |
| ML-P5-05 | P2 | Forecasting | Zero-inflated daily intervals cannot be calibrated by a symmetric scale; intervals asymmetric (≈5% below q10) | VERIFIED (F2) | open: zero-aware calibration under a new frozen protocol |
| ML-P5-06 | P2 | Forecasting / decisions | Trained medians sum to 42–50% of realised volume | VERIFIED (F2) | open: never order medians (product uses lead-time demand at 90%) |
| KNOW-P5-01 | P2 | Retrieval | Unscoped multi-supplier questions answered with one supplier's clause | VERIFIED (R3) | fixed: ambiguity flag (P5-E04) |
| KNOW-P5-02 | P2 | Retrieval | Retrieval-only signals cannot separate out-of-scope from reworded questions: 10/26 out-of-scope declined, 51/172 reworded no longer answered | VERIFIED (R3 test half) | open: reader model + human-reviewed questions (EXT-06) |
| KNOW-P5-03 | P2 | Retrieval | Lexical-only search (hosted demo) flags supplier-named questions as ambiguous (0/4) | VERIFIED (R3 test half) | open: new frozen task set needed (found on test) |
| KNOW-P7-01 | P3 | Generation | The product-ambiguity check declines every question that names only a supplier (0/8 answered, 3/8 before), because each agreement sets terms per product; 1/9 ambiguous questions is still answered from one product | VERIFIED (G1, P7-E05) | open: ask which product in the UI instead of a plain refusal; human-reviewed questions (EXT-06) |
| PLAN-P7-01 | P3 | Planning | CO2 per unit comes from lanes assumed from lead time and an assumed 0.5 kg unit weight | Documented (D-095) | open: supplier lane and weight data |
| OPS-P7-01 | P3 | Agent | The n8n workflow signs in through the local development sign-in; a deployed stack needs a planner service account through the identity provider | Documented (infra/n8n/README.md) | open: depends on P1-IAM-01 |
| PERF-P7-01 | P3 | Performance | The CO2 frontier takes 31 s on the hosted demo (3.2 s on the laptop): 11 sequential CP-SAT solves in one serverless function | VERIFIED (P7-E11) | open: fewer caps on the hosted profile, or warm-start each cap from the previous plan |
| PLAN-P5-01 | P2 | Planning | Under a binding budget, coverage-first rationing maximises units covered, not margin or service (S2) | VERIFIED (S2, simulated) | open: owner decision on the rationing objective |
| FE-P5-01 | P2 | Web / layout | On a phone, study cards with tables (Research) and the Forecast lab columns were 460–520 px wide on a 375 px screen: grid items default to `min-width: auto` and grew to their tables | VERIFIED (measured card widths) | fixed: `min-w-0` on the grid items (P5-E13) |
| QA-P5-01 | P2 | Tests | The overflow checks compared `scrollWidth` with `innerWidth`; under phone emulation the browser widens `innerWidth` to the content, so the check could not fail | VERIFIED | fixed: compared with the configured viewport width; caught FE-P5-01 on `/forecast` (P5-E13) |
| QA-P5-02 | P3 | Tests | A Phase 5 retrieval test passed locally (embedding model running) but failed in CI (lexical only): it asserted an embedder-only detail | VERIFIED (CI run 40007061655) | fixed: asserts the right reason in each mode; run the suite with `SUPPLYLENS_OLLAMA_URL=http://127.0.0.1:9` before pushing retrieval changes (P5-E15) |
| ERP-P6-01 | P1 | Execution | An ERP outage spent the retry budget: 5 attempts with 2–16 s back-off, so a ~30 s outage failed every queued order and needed a person to retry each | VERIFIED (code; test reproduces the old count) | fixed: circuit breaker, outages do not spend attempts (D-089, P6-E03) |
| ERP-P6-02 | P2 | Execution | A business rejection was treated as transient: retried 5 times, then retryable by hand with the same order | VERIFIED (code) | fixed: `AdapterRejected` fails at once, `failure_kind = rejected`, retry refused (P6-E03) |
| ERP-P6-03 | P2 | Execution | Expired credentials were indistinguishable from any error: every queued order would fail; no health probe | VERIFIED (code) | fixed: `CREDENTIALS_INVALID` stop, probe, Test ERP connection (P6-E03, P6-E05) |
| ERP-P6-04 | P2 | Execution | A lookup failing during a lookup-first retry escaped the dispatcher: the item stayed IN_FLIGHT until its lease expired and each expiry counted towards the dead letter (8), so an outage of ~6 min could park orders as UNKNOWN_OUTCOME | VERIFIED (code) | fixed: paused like an outage, attempts kept above 1 so the next try still looks up first (P6-E03) |
| ERP-P6-05 | P2 | Execution | No ERP receipt or order-status synchronisation (receipts by hand or CSV only); no way to cancel a placed order in the ERP; an ERP-side cancellation left phantom supply in planning | VERIFIED (absence) | fixed against the simulator: receipt feed, order-status sync, Cancel order (D-088, D-092, P6-E03); real ERP BLOCKED (EXT-02) |
| OPS-P6-01 | P2 | Operations | `/health` and every route answered 500 while the database was down | VERIFIED (outage drill) | fixed: 503 `database_unavailable` + Retry-After (D-091, P6-E06) |
| OPS-P6-02 | P2 | Operations | A stopped worker was invisible outside its container (heartbeat file only); no service-health or reconciliation view or report | VERIFIED (absence) | fixed: `worker_heartbeats`, `GET /ops/health`, `GET /ops/reconciliation`, Administration cards (P6-E03, P6-E08) |
| OPS-P6-03 | P2 | Operations | Hosted database not yet migrated to 0011: the live demo runs the Phase 6 code in its pre-0011 mode (no connector state, sync, heartbeats) | VERIFIED (design, D-090) | open: owner runs the PD-009 setup-token procedure |
| OPS-P6-04 | P3 | Execution | Receipts held for an order awaiting reconciliation keep the feed cursor; more than 500 later receipts in that window would wait until it is reconciled | VERIFIED (design) | open: per-receipt hold table if real volumes need it |

## External blockers (cannot be closed by code alone)

| ID | Blocker | Blocks | Owner |
|---|---|---|---|
| EXT-01 | Corporate identity provider to qualify OIDC/SCIM | BUS-012, BUS-022, P1-IAM-01 acceptance | Owner / customer IT |
| EXT-02 | Real ERP test tenant + credentials + schemas (only `integrations/sandbox_erp.py`, a local simulator, exists; the adapter contract and what qualification needs: `docs/operations/erp-integration.md`) | BUS-013, EXE-013 | Customer |
| EXT-03 | Pilot business users | BUS-016, BUS-017, Real-MVP score | Owner |
| EXT-04 | Declared 8 vCPU / 32 GiB load profile | ARC-07 | Owner (hardware) |
| EXT-05 | Manual screen-reader pass | UX-010 | A person with NVDA/VoiceOver |
| EXT-06 | Human review of 50 R2 questions | ARC-04 | Reviewer |
| EXT-07 | Independent penetration test | BUS-021 completeness | Third party |
| EXT-08 | Generative LLM disabled (D-041) | ML-006 agent ablations | Owner decision |
| EXT-09 | M5 / ContractNLI licence acceptance | DAT-004 extension | Owner |
| EXT-10 | Pricing, SLAs, support model | BUS-024, BUS-025, EXE-014 | Owner |

---

## Details

### P0-SEC-01 — Public `tenant_admin` can alter the shared live demo
- **Files:** `services/api/src/supplylens/config.py` (`dev_login_available` true for `demo`), `api/routes_core.py:39-62`
  (passwordless `dev-login` by email), `authz.py:11-19` (`tenant_admin` ⇒ `admin.write`),
  `onboarding/service.py:30-67` (`create_workspace`, `set_membership`), `migrations/versions/0007_…:198-225`
  (`sl_set_membership` deletes any non-OIDC membership except the caller's own).
- **Reproduction (do not run on the live site):** `GET https://supplylens-self.vercel.app/api/v1/auth/dev-users`
  lists `tenant_admin@dev.supplylens.local` (P0-E20). `POST /api/v1/auth/dev-login {"email":"tenant_admin@…"}`, then
  `POST /api/v1/admin/members {"email":"approver@dev.supplylens.local","role":null}` with
  `X-SupplyLens-Tenant: demo` removes the approver from Demo for every visitor. `POST /api/v1/onboarding/workspaces`
  and `/onboarding/batches` are not rate-limited.
- **Impact:** any anonymous visitor can break or deface the public demo, create unbounded workspaces/imports on the
  Neon free tier, and remove roles; there is no reset. Reputational and availability risk on the owner's public URL.
- **Acceptance:** (1) in `environment=demo`, `admin.write`, membership changes, workspace creation, imports, tenant
  export/deletion are refused (403) for dev accounts, or every visitor gets an isolated, expiring sandbox tenant;
  (2) shared demo state is reset on a schedule or per session; (3) dev-login and mutation routes are rate-limited
  per client; (4) pytest covers each refused route under `environment=demo`; (5) verified against the hosted URL
  after redeploy with a read-only probe (expect 403).

### P0-PLAN-01 — Default shortfall makes "order nothing" optimal
- **Files:** `optimisation/supplylens_opt/planner.py:164-180` (objective `(purchase + penalty) * W + units*100 + tiebreak`);
  defaults `allow_shortfall=True`, `shortage_penalty_minor=500` in `agent/graph.py:284-285`,
  `planning/scenario.py:41-42`, `api/routes_decisions.py:208`; `AgentRunIn` has no penalty field.
- **Reproduction:** reviewer probe — need 100, unit cost 640, budget 1e8 → `OPTIMAL`, no lines, shortfall 100; the
  spec reference case (30 units at 500) with `allow_shortfall=True` → `OPTIMAL`, no lines, 30 short. Tests and the UI
  pass `allow_shortfall:false`, hiding it (`apps/web/app/(app)/runs/page.tsx:41`, `tests/test_agent_graph.py:34`).
- **Impact:** for any SKU whose unit cost ≥ the assumed penalty (22 of 37 demo terms), default scenario and agent runs
  recommend buying nothing while reporting `OPTIMAL`; `check()` does not flag shortfall. Silent stockouts — the core
  recommendation is wrong by default.
- **Acceptance:** shortfall is opt-in or its penalty is derived from margin/stockout cost and always exceeds unit
  cost; any plan with shortfall > 0 is surfaced as a flagged issue in agent `check()` and scenario output; tests cover
  penalty ≤ unit cost, = unit cost and > unit cost on both scenario and agent paths.

### P1-PLAN-02 — Protection interval uses the fastest supplier
- **Files:** `planning/scenario.py:86-88`, `agent/graph.py:232-235`; planner `planner.py:101-118` only checks arrival ≤ need-by.
- **Reproduction:** reviewer probe — flat q50 = 10/day, coverage 21: 273 units required at 2-day lead vs 482 at
  21-day; planner picks the 21-day supplier for 273 units (~43% under-order). UCI simulated primaries are cheaper and
  slower (`simulation/uci_ops.py:35-36`).
- **Acceptance:** required units depend on the chosen offer's lead time (per-offer requirement in CP-SAT, or plan per
  supplier lead-time class); golden test with two suppliers of different lead times asserts the slower choice orders
  the larger quantity.

### P1-ACT-01 — STALE actions cannot be re-approved
- **Files:** `actions/service.py:415-422` (STALE leaves outbox row `FAILED`), `:212-216` (edit accepts STALE),
  `:166-174` (approve inserts outbox without conflict handling); `migrations/versions/0001_core_schema.py:375-376`
  `UNIQUE (tenant_id, operation_id)`, `UNIQUE (tenant_id, action_id)`. No `DELETE FROM outbox` exists.
- **Reproduction:** approve → let approval expire or amend terms → dispatch (STALE) → edit → approve ⇒ UniqueViolation ⇒ 500.
- **Acceptance:** re-approval after STALE reuses/resets the outbox row (new operation id or reset row) without
  duplicate external sends; pytest walks STALE → edit → approve → dispatch → RECONCILED.

### P1-ACT-02 — Unreconciled orders invisible to planning; CONFIRMED dead-end
- **Files:** `planning/positions.py:60-78` (reads only `purchase_order_lines`), `actions/service.py:296-298`
  (ledger written only on RECONCILED), `:444-450` (mismatch ⇒ CONFIRMED), retry/reconcile accept only FAILED /
  UNKNOWN_OUTCOME; `services/worker/src/supplylens_worker/main.py:38` (CONFIRMED not terminal). An alert is raised
  for CONFIRMED (`service.py:301-306`) but no state transition resolves it.
- **Impact:** next run re-plans the same need while an order is queued/in flight/mismatched → double purchasing; runs
  stay WAITING_FOR_APPROVAL forever after a mismatch.
- **Acceptance:** planning subtracts committed-but-unreconciled quantities (approved/queued/submitted/unknown/confirmed)
  or blocks re-planning that SKU with a reason; an explicit, audited resolution path exists for CONFIRMED mismatches;
  tests for each state.

### P1-SEC-02 — Owner credentials inside the hosted API runtime
- **Files:** `scripts/vercel/build_api.py:36-44` (generated `index.py` sets `SUPPLYLENS_ADMIN_DATABASE_URL` from
  `DATABASE_URL_UNPOOLED`); used at runtime only by `hosting/setup.py`. `config.py::_fail_closed` checks the two URLs
  differ, not that the owner URL is absent.
- **Impact:** any code-execution or SSRF-to-env bug in the public API yields an owner connection that bypasses RLS.
- **Acceptance:** the serving function has no owner DSN in its environment (setup moved to a separate, token-gated,
  short-lived deployment or a CI job); demo/production profile refuses to start if an owner DSN is present; verified
  by a startup test.

### P1-FE-01 — Workspace not reconciled with memberships
- **Files:** `apps/web/lib/state.ts:6` (`withDefault("uci-research")`), `lib/api.ts:15`, `app/login/page.tsx:27`
  (`router.replace("/")`), `app/(app)/layout.tsx:94-96` (fallback membership used only for display).
- **Impact (INFERRED):** a user without `uci-research` membership (OIDC user, new customer workspace) gets 404
  `tenant_not_found` on every query while the UI shows another workspace and its role.
- **Acceptance:** after sign-in and on any `ws` the user is not a member of, the app switches to a permitted
  workspace (or shows a chooser); e2e test signs in as a user with only a customer workspace.

### P1-FE-02 — Receipt quantity keyed by SKU, not SKU@location
- **Files:** `apps/web/app/(app)/approvals/page.tsx:264-296`; related single-location assumptions in
  `inventory/page.tsx:47,108`, `components/warehouse3d.tsx:115`, `components/floorplan.tsx:23`.
- **Acceptance:** state keyed by `(sku_id, location_id)`; React keys unique; e2e books a receipt for one of two
  locations of the same SKU and asserts only that location changes.

### P1-IAM-01 — Identity model is not multi-tenant SaaS grade
- **Files:** `services/api/src/supplylens/api/oidc.py` (single issuer from settings; roles from claim
  `supplylens_roles` as `<slug>:<role>`; access token verified without audience), `sl_upsert_oidc_user` links by
  subject, else verified email (migration 0007).
- **Acceptance:** per-tenant IdP configuration (or an explicit single-IdP decision recorded in DECISIONS), tenant
  claims constrained to tenants bound to that IdP, SCIM or equivalent deprovisioning, account-linking policy tested,
  qualification against one real corporate IdP (EXT-01).

### P1-OPS-01 — No production deployment architecture
- **Evidence:** `infra/` holds only Dockerfiles, Keycloak realm and PG init; no Terraform/Helm/K8s; deployments are
  `docker-compose.yml` (local, dev profile), `render.yaml` (unused alternative), Vercel demo. API runs one uvicorn
  process (`api.Dockerfile` CMD). OTel export optional; no metrics, dashboards, SLOs or paging.
- **Acceptance:** one documented, reproducible staging + production environment from code (IaC), secrets from a
  manager, ≥2 API replicas + worker, health/readiness probes, dashboards and alert routes for the defined SLOs,
  restore drill run against that environment.

### P1-SAAS-01 — No SaaS commercial plumbing
- **Evidence:** no billing/subscription/signup code (`grep -ril "billing|stripe|subscription|signup"` over
  `services`, `apps/web` source: no hits). Workspaces can only be created by an existing `tenant_admin`.
- **Acceptance:** owner decision on SaaS scope recorded; then self-serve or sales-led provisioning flow, plan limits,
  metering of the cost drivers (retrieval, forecasts, storage), billing integration — each with tests.

### P1-PROC-01 — Unprotected `main`
- **Evidence:** `gh api repos/krish2105/SupplyLens-/branches/main/protection` → 404 "Branch not protected"; repo is
  public; D-037 pushes to `main`. CI runs after the fact (4 of the last 7 pushes failed CI, P0-E17).
- **Acceptance:** branch protection with required CI checks; changes land via PR.

### P2-REL-01 — Exhausted jobs stuck in RUNNING
- **Files:** `services/api/src/supplylens/jobs.py:21-33`; no other transition (grep `max_attempts`).
- **Reproduction:** P0-E16 probe.
- **Acceptance:** exhausted, lease-expired jobs become FAILED with a reason, the run is marked failed, an alert is
  raised; pytest covers claim/lease/fencing/exhaustion.

### P2-REL-02 — Unfenced agent-run execution (PLAUSIBLE)
- **Files:** `jobs.py:36-43` (heartbeat has no exception handling), `worker/main.py:56-62`, `agent/graph.py:346-352`
  (check-then-insert draft across transactions; no unique constraint per run+supplier).
- **Acceptance:** heartbeat failures stop the job; draft creation is idempotent at the schema level; test kills the
  heartbeat and asserts one draft.

### P2-REL-03 — Worker throughput and outbox re-claim
- **Files:** `worker/main.py:96-108` (serial loop over all tenants), `actions/service.py:264-277` (IN_FLIGHT
  re-claimed after 45 s, no attempts cap, no heartbeat; sandbox IntegrityError aborts the tick).
- **Acceptance:** concurrent workers/threads with bounded per-tenant fairness; outbox lease heartbeat and attempt cap;
  load test with N tenants.

### P2-PLAN-03 — Post-cutoff operational data in replays
- **Files:** `planning/scenario.py:62-68` (`load_positions(s, skus, eff)`, `demand_shares(…, eff)`), `:90`
  (dependence at `eff`), `agent/graph.py:162-176`, `:255-257` (capacity without `as_of <= eff`). Only the forecast
  origin is clamped (`scenario.py:80`). CSV-imported terms carry user-supplied `known_at` with no system recorded-at.
- **Acceptance:** all operational reads bounded by `min(cutoff, eff)` (or `eff > cutoff` rejected); README "two
  clocks" claim scoped accurately; tests with post-cutoff stock rows.

### P2-PLAN-04 — Dependence on gappy calendars
- **Files:** `planning/demand_history.py:22-30`, `optimisation/supplylens_opt/leadtime_demand.py:160-167`.
- **Acceptance:** history zero-filled to calendar days (or lags computed on dates); test with missing days.

### P2-PLAN-05 — Scenarios plan through conflicts
- **Files:** `planning/scenario.py:84-85` vs `knowledge/terms.py:7`; agent blocks (`graph.py:314`).
- **Acceptance:** conflicting SKUs excluded or flagged as review-required in scenario output; test.

### P2-ML-01 — Trained-model path untested; no fallback for missing artifacts
- **Files:** `tests/test_forecast_service.py` (refusal + fallback only); `forecasting/service.py:108-150,168`.
- **Acceptance:** a test trains a tiny LightGBM artifact, registers it, and forecasts through the service; missing
  artifact falls back to the baseline with a labelled reason (or fails loudly by decision).

### P2-KNOW-01 — Weak abstention
- **Files:** `knowledge/retrieve.py:110-115,147`; `api/routes_decisions.py:157-181`.
- **Acceptance:** similarity/score floor and an out-of-scope test set (not only fake product codes); report abstention
  precision/recall in the R-study.

### P2-PRIV-01 — Quarantined personal data retained and exposed
- **Files:** `onboarding/csv_import.py:198-202`, `onboarding/service.py:93-95,102-108,204-206`.
- **Acceptance:** cells flagged as personal data are redacted before storage; viewers never see raw rejected rows;
  documented retention; test.

### P2-API-01 — No body-size limit before parsing (PLAUSIBLE)
- **Files:** `api/routes_onboarding.py:53-56`, `api/app.py` (no size middleware), no proxy limits in `infra/`.
- **Acceptance:** request body limit enforced before multipart parsing (ASGI middleware or proxy); test with an
  oversized unauthenticated POST → 413.

### P2-FE-03 … P2-FE-08 — Web robustness
- P2-FE-03: no ESLint config/binary (`apps/web/package.json`); `eslint-disable` comments reference rules that never
  run; no vitest/jest; `tsconfig.json` excludes `e2e`. Acceptance: ESLint (incl. react-hooks) + unit test runner in CI.
- P2-FE-04: `find apps/web/app -name error.tsx -o -name global-error.tsx -o -name not-found.tsx` → none.
  Acceptance: route-level and global error boundaries with tests forcing a render error.
- P2-FE-05: `app/(app)/runs/page.tsx:37-40` posts `/agent-runs` without `idempotencyKey`; same for forecasts, exports,
  deletion, onboarding, alert ack; `approvals/page.tsx:106-107` retry/reconcile ignore the intent key.
  Acceptance: every mutating call uses one key per user intent; e2e double-click test creates one run.
- P2-FE-06: error → endless `<Loading/>` or empty state (`admin/page.tsx:48,64,92,96`; `approvals/page.tsx:65,77`;
  `forecast/page.tsx:227-228`; `research/page.tsx:44`; `settings/page.tsx:73`; `(app)/page.tsx:167-179`).
  Acceptance: shared error state component used on every query.
- P2-FE-07: `components/onboarding.tsx:90,103,120`; `app/(app)/layout.tsx:165`. Acceptance: keyed component, error UI.
- P2-FE-08: `components/vitals-reporter.tsx:9-21`. Acceptance: observers registered once; route attached at report time.

### P2-QA-01 — Order-dependent E2E
- **Evidence:** P0-E12 (fail under 6 workers) and P0-E13 (pass alone); `apps/web/e2e/helpers.ts:30-46`; five specs use
  the reference case; `playwright.config.ts` sets no `workers`, `retries: 0`. Fixed sleeps in `consistency.spec.ts:12,19`,
  `resilience.spec.ts:118`, `vitals.spec.ts:52,73`; position selectors (`tbody tr.first()`).
- **Acceptance:** per-test isolated SKU/tenant or serial project for stateful specs; three consecutive full local runs
  with default workers pass.

### P2-PERF-01 — Throughput and mobile LCP (recorded, not re-run)
- Sources: `docs/operations/load-test.md`, `docs/operations/web-vitals.md`, D-035. Acceptance: ARC-07 met on the
  declared profile (EXT-04); overview mobile LCP ≤ 2.5 s throttled.

### P3-DOC-01 — Numeric drift (VERIFIED)
| Claim | README | PROJECT_STATUS / TASKS | Measured (Phase 0) |
|---|---|---|---|
| Backend tests | 296 | 330 passed + 6 skipped | 336 passed, 6 skipped (P0-E04) |
| Browser tests | 102 | 107 passed, 1 skipped | 116 collected (P0-E12) |
| Forced-RLS tables | 34 | 30 | 38 (P0-E14) |
| CI jobs | — | "all 7 jobs" | 8 jobs (P0-E17) |
Acceptance: numbers generated from CI artifacts or removed from prose.

### P3-DOC-02 — Contradictions (VERIFIED)
- Root `DECISIONS.md` "Authorisation scope recorded: No deployments …" vs D-050 (Vercel deployment).
- `PROJECT_STATUS.md` "Current task: Session 3 complete" after session-4 sections.
- README "Not production-ready: enterprise sign-in (OIDC) … outstanding" vs local Keycloak OIDC verified (D-039).
- `optimisation/supplylens_opt/leadtime_demand.py:30-31`, `docs/research/results.md:198-199` say real-data validation
  needs licensed files although UCI is ingested (PLAUSIBLE drift).
Acceptance: single source of truth; contradictions removed.

### P3-PLAN-06, P3-ML-02, P3-ONB-01, P3-SEC-03, P3-CI-01, P3-FE-09
See summary rows; file references: `planner.py:203-204,246-248`; `scenario.py:72`; `replenishment.py:7-8,138-144`;
`forecasting/service.py:129-130`; `ml/supplylens_ml/tcn.py:125-128`; `evaluations/simulation_study.py:50,59`;
`onboarding/csv_import.py:121-125`; `onboarding/service.py:36-52,139-150,212-250`; `api/oidc.py:93-99,163-187`;
`api/routes_decisions.py:288-290`; `.github/workflows/ci.yml` (`uses: …@v4/@v6`); `infra/docker/*.Dockerfile`.

---

## Phase 1 resolution notes (2026-10-22/23)
Statuses above point to evidence in EVIDENCE.md (P1-E..). What each fix changed, and what remains:

- **P0-SEC-01** — `supplylens/demo.py` (locked operations; `release_stale_orders`), `authz.py` (`Actor.require` refuses
  locked operations in `demo`), `api/routes_core.py` (release on demo sign-in). Remaining: dev-login and per-account
  mutation rate limits for anonymous visitors; per-visitor sandboxes (not required by the acceptance criteria met).
- **P1-SEC-02** — `config.py` (`admin_database_url` optional, `owner_database_url`, `maintenance`, demo/production
  refusal), `db.py`, `migrations/env.py`, `hosting/setup.py`, `scripts/vercel/build_api.py` (entrypoint scrubs owner
  variables unless the setup token is set), `scripts/render/env.py` / `start.sh` (`--serve`). Remaining: Vercel still
  injects the Neon owner variables into both services at process start; removing or scoping them is an owner action in
  the Vercel/Neon integration settings.
- **P0-PLAN-01** — `optimisation/supplylens_opt/planner.py` (two-pass lexicographic solve; explanation for any
  shortfall), `agent/graph.py` (`checks.warnings` shortfall; `shortfall_unmet` issue), `api/schemas.py`
  (`ChecksRef.warnings`), web approvals/runs pages show the warning.
- **P1-PLAN-02** — `Need.required_units_by_lead_time` + `required_for()` in the planner, per-offer constraint, validator
  checks the chosen lead time; scenario and agent assess each distinct lead time.
- **P1-ACT-01** — `actions/service.py::approve` resets a FAILED outbox row (same operation key, attempts=1 ⇒ lookup
  first) and refuses while a dispatch is active.
- **P1-ACT-02** — `planning/positions.py` counts QUEUED/SUBMITTED/UNKNOWN_OUTCOME/CONFIRMED payload lines as open supply;
  `actions/service.py::accept_remote_order` + `POST /api/v1/actions/{id}/accept-remote` (approver ≠ preparer) books the
  target's lines and reconciles. Remaining: pending drafts are not counted (by decision D-056); two drafts for one need
  can still both be approved if neither has been approved when the other is.
- **P2-REL-01/02** — `jobs.py` (`expire_exhausted`, resilient heartbeat), migration 0009 (unique draft per run+supplier;
  alert kind `job_failed`), `agent/graph.py` handles the conflict. Remaining (P2-REL-03): serial worker loop, outbox
  re-claim cap.
- **P2-PLAN-03/04/05** — `planning/scenario.py`, `agent/graph.py` (`known = min(cutoff, eff)`),
  `leadtime_demand.py` (`ordinals` ⇒ calendar lags), `planning/demand_history.py`, scenario `excluded_for_conflict`.
  Remaining: CSV-imported terms still carry a user-supplied `known_at` with no system recorded-at.
- **P1-FE-02** — approvals receipts keyed by SKU@location. Remaining: inventory table, 3D scene and floor plan still key
  by SKU (moved to Phase 4 with P1-FE-01).


---

## Phase 3 resolution notes (2026-10-23) — performance, scalability, backend reliability
Evidence P3-E.. in EVIDENCE.md; full record in phases/PHASE-03.md; product decisions D-068 … D-072.

- **Historical collapse at 4→5 retrieval req/s** — **not reproducible on the Phase 3 machine** (Apple M4 Pro, 12 cores):
  before any change it served 5 req/s at retrieval p95 256 ms and saturated near 8–9 req/s (P3-E04). The 2026-10-21
  result came from a 4 vCPU Xeon; the two are not comparable and no claim is made for the declared 8 vCPU profile.
- **PERF-P3-01/02** — migration 0010 (`chunk_vectors`, forced RLS, per-tenant copy, transactional rewrite of chunks),
  `knowledge/retrieve.py` (vector top-n on the narrow table), all writers (`knowledge/ingest.py`, `ingest/cuad.py`,
  `ingest/acord.py`), readers (`alerts.py`, `lifecycle.py` export keeps the `chunks.ndjson` format).
- **PERF-P3-03/04/05, SEC-P2-11** — `api/admission.py`, `api/app.py` (gates, lifespan thread pool, 503 handlers),
  `db.py` (statement_timeout, pool_timeout), `config.py`. Web: `lib/api.ts`, `app/providers.tsx`,
  `components/connection-banner.tsx` (busy banner, Retry-After-aware retries).
- **PERF-P3-06** — `routes_core.py` inventory paging, `routes_decisions.py` documents paging, `schemas.Inventory`
  (total, offset, next_offset), inventory page note when truncated.
- **PERF-P3-07** — `metrics.py`, `GET /metrics` (token), `deps.actor` records the authorised workspace.
- **P2-REL-03** — `actions/service.py` (`OUTBOX_MAX_ATTEMPTS` dead letter), `supplylens_worker/main.py`
  (`tenant_tick`, per-workspace isolation, `DISPATCH_PER_TICK`, worker statement timeout off).

---

## Phase 4 resolution notes (2026-10-23) — frontend, UX and end-to-end journeys
Evidence P4-E.. in EVIDENCE.md; record in phases/PHASE-04.md; product decisions D-073 … D-077.
- Shell: `app/(app)/layout.tsx` (workspace reconciliation, no-workspace screen, sign-out errors, shell boundaries),
  `app/providers.tsx` (401 → sign-in with return path; busy retries), `lib/nav.ts` (safe return path), `app/login/page.tsx`.
- Boundaries: `app/error.tsx`, `app/(app)/error.tsx`, `app/global-error.tsx`, `app/not-found.tsx`, `components/crash.tsx`,
  `components/safe-boundary.tsx`.
- Data states: `components/ui.tsx` (`QueryError`, `TabList`, `TabPanel`) used across all screens.
- Mutations: `lib/api.ts` default per-intent keys. Drafts: `lib/draft.ts`. Vitals: `components/vitals-reporter.tsx`.
- Inventory per location: `routes_core.py` INVENTORY_SQL, `routes_ops.py` detail text, inventory/floor plan/3D/forecast/palette.
- Documents: `knowledge/upload.py`, `POST /api/v1/documents`, Policies "Add a document" and clause-label viewer.
- Tests: `tests/test_phase4_web_api.py` (5), `apps/web/{lib,components}/*.test.ts(x)` (19), `e2e/workflows.spec.ts` (20),
  `e2e/fixtures.ts` (reference-case lock), cross-browser projects in `playwright.config.ts`, CI lint/unit/browsers.

---

## Phase 4B resolution notes (2026-10-23) — visual UI, UX and asset quality gate
Record in phases/PHASE-04B.md (§2 has the screen, fix and before/after screenshot per issue); evidence P4B-E..; decisions
D-078 … D-080. All **FIXED** and pinned by a test that fails on the previous code unless noted.
- **UI-4B-01** sign-in clipped on phone/tablet — `app/login/page.tsx`; `e2e/ui-quality.spec.ts` "sign-in fits the screen".
- **UI-4B-02** sticky header covered a third of a phone screen — `app/(app)/layout.tsx`, `app/globals.css`; "header scrolls away".
- **UI-4B-03** phone section strip clipped, no current section — `SectionsMenu` in `layout.tsx`; "sections menu …" + visual baseline.
- **UI-4B-04** seven tables overflowed on phones; ledger figures touching — `components/ui.tsx` `TableScroll`, value/research/forecast/onboarding; "wide tables scroll inside a labelled region".
- **UI-4B-05** market told Contract research to switch to itself; clock rail empty without reason — `api/routes_market.py`, `components/clock-rail.tsx`; `tests/test_phase4b.py`, "no operational date …".
- **UI-4B-06** runs Mode select overflowed on phones — `runs/page.tsx` (seen in screenshots; covered by the no-overflow layout tests).
- **UI-4B-07** £0 materiality without a selling price (misleading) — `api/routes_ops.py`, `exceptions/page.tsx`; `tests/test_phase4b.py`.
- **UI-4B-08** loading overview called UCI Research fictional and without sales data — `app/(app)/page.tsx`; "the overview does not call a workspace fictional …".
- **UI-4B-09** empty warehouse and "Snapshot — ·" under error/empty/offline; empty floor plan on phones — `inventory/page.tsx`, `app/(app)/page.tsx`; "inventory that fails to load …".
- **UI-4B-10** version comparison/reader opened off-screen below xl — `policies/page.tsx`; "opening a version comparison …" (also asserts where it lands).
- **UI-4B-11** anchors/focus landed under the 176 px tablet header (144 px reserved) — `layout.tsx` measures `--header-h`; probe P4B-E10.
- **UI-4B-12** charts animated despite reduced motion — `components/chart-impl.tsx`; visual baselines (reduced motion) would drift otherwise.
- **UI-4B-13** duplicate exceptions request on first load — `exceptions/page.tsx`; after-probe shows no aborted request.
- **Open, low:** UI-4B-R1 (Contract research clock rail shows empty date inputs, now explained), UI-4B-R2 (offline before
  first load: skeleton and an empty "0 of 0" table header). **Process:** Linux visual baselines reviewed and
  committed (P4B-E13); CI compares from then on (P4B-E14). **Illustrations:** A02/A13/A16 stay withheld (D-040
  reconfirmed); replacement briefs await owner approval (PHASE-04B §8); nothing generated.
- **QA-4B-01 — FIXED (measurement, target unchanged):** the lab INP proxy missed 200 ms on CI only (224 ms /inventory;
  later 232 ms on `/`, run 40019830966), always on the two 3D pages, never locally. Cause: the vitals tests ran in the same
  CI step as the Firefox/WebKit journeys on a 4-vCPU runner, so they measured the runner's load. Evidence: every slow entry
  is presentation delay with 0 ms in handlers; with all 12 local cores busy the same interactions took 0.7–1.7 s **with or
  without WebGL** (so neither the 3D scene nor the app code is the variable); alone they read 24–40 ms (desktop) and
  40–80 ms (throttled phone). Fix: `vitals-desktop`/`vitals-mobile` projects run alone, one test at a time, in their own CI
  step after the other suites (`playwright.config.ts`, `ci.yml`); acceptance evidence reads both results files. Targets
  and the median-of-3 rule did not change (QA-E04, QA-E05).
- **QA-4B-02 — FIXED (test and product):** J4 failed on WebKit in CI with two versions labelled "v1" (run 40019830966).
  Cause, from the CI trace and Playwright's source: `fill` focuses the field, then types with a separate keyboard command;
  a frame after the first upload the Policies reader took focus (UI-4B-10's reveal), so the "v2" keystrokes went nowhere
  and the amendment was saved as "v1". A second cause found while reproducing: two runs started in the same millisecond
  uploaded identical text and the API refused it as a duplicate. Fixes: unique stamp; J4 asserts the label before
  submitting; see FE-4B-14 for the product fix (QA-E01…E03).
- **FE-4B-14 — FIXED (regression from Phase 4B):** after adding a document the reader stole focus and scrolled the page
  up (621 px desktop, 746 px phone) while the user carried on in the form. The reveal now happens only when the user opens
  a version, a comparison or a citation, and only if focus is still where the click left it (`policies/page.tsx`).
  Pinned by `ui-quality.spec.ts` "after adding a document, focus and scroll stay with the form" (fails on the old build).
- **DOC-4B-15 (open, P3):** the API accepts a second version with the same label in one document (how the J4 failure
  stored two "v1"s). Proposal: refuse a duplicate `version_label` per document with 409.

## Phase 5 resolution notes (2026-10-23/24) — AI/ML, retrieval, optimisation, MLOps
Detail and numbers: `phases/PHASE-05.md`, `docs/research/results.md` (F1 2.1.0, F2, S2, R3).
- **ML-P5-01** — `ml/supplylens_ml/panel.py` (dates as `datetime64[D]`; `_dates` reads legacy integers in their unit).
  F1 2.1.0 (`F1-20261023T180239Z`) registered; TCN 2.0.0 retired in the local registry. Hosted demo unaffected (no trained models).
- **P2-ML-01 / ML-P5-02 / P3-ML-02** — `forecasting/service.py` (`FALLBACK_CODES`, `_baseline_points`, `_verified_bytes`),
  `ml/supplylens_ml/tcn.py` (`torch.load(BytesIO)`), `evaluations/simulation_study.py` (recorded-hash checks).
- **MLOps** — `forecasting/governance.py` (promotion gate, enforced in `routes_ops.set_model_status`),
  `forecasting/monitor.py` + `GET /api/v1/models/monitoring` (admin.read).
- **P2-KNOW-01 / KNOW-P5-01** — `knowledge/retrieve.py` (`answer_support`, constants fitted by R3), evidence route and
  Policies page messages; `tests/test_api.py` updated to the ambiguity behaviour.
- **P3-PLAN-06 (part)** — `optimisation/supplylens_opt/planner.py`.
- **FE-P5-01 / QA-P5-01** — `apps/web/app/(app)/research/page.tsx` (`StudyCard`), `apps/web/app/(app)/forecast/page.tsx`;
  `apps/web/e2e/layout.spec.ts` and `a11y.spec.ts` now compare with the configured viewport width.

## Phase 6 resolution notes (2026-10-24) — ERP integration and operational excellence
Detail: `phases/PHASE-06.md`, `docs/operations/erp-integration.md`, `slo.md`, `service-management.md`, runbook.
- **ERP-P6-01…04** — `integrations/contract.py` (error classes), `registry.py`, `connector.py` (circuit breaker, probe),
  `actions/service.py` (`_pause`, `failure_kind`, lookup failures paused, `_lookup` 503); migration 0011.
- **ERP-P6-05** — `integrations/sync.py` (order status, receipt feed, overdue), `actions/service.py` (`book_receipt`,
  `release_open_units`, `cancel_order`), route `POST /actions/{id}/cancel-order`; sandbox `cancel`, `post_receipt`,
  `cancel_by_supplier`, `set_connector`.
- **OPS-P6-01** — `api/app.py` (OperationalError → 503 `database_unavailable`).
- **OPS-P6-02** — `operations.py`, `routes_ops.py` (`/ops/health`, `/ops/reconciliation`, `/ops/connector/test`),
  worker heartbeat (`worker_heartbeats`), `metrics.py` gauges, `apps/web/components/operations.tsx` on Administration.
- Found during verification and fixed before commit: reading connector state created a row, so a deleted workspace left
  one behind (caught by `tests/test_lifecycle.py`); reads are now read-only (`test_reading_connector_state_never_creates_a_row`).
- **Not done:** a real ERP adapter (EXT-02); ERP inventory/supplier pull (needs vendor schemas); WAL-archiving alert;
  external uptime probe and paging (P1-OPS-01).

