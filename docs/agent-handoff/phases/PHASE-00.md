# Phase 0 — baseline audit

**Date:** 2026-10-22 (UTC) · **Commit audited:** `9fcbedb19b0831ad2599b5291569dfae309d5b6e` on `main` (= `origin/main`)
· **Working tree:** clean before the audit; the only change made is this `docs/agent-handoff/` folder (plus
git-excluded local launch configs `p0-api`, `p0-worker`, `p0-web`) · **Application behaviour:** unchanged.

Evidence IDs (`P0-E..`) refer to [`../EVIDENCE.md`](../EVIDENCE.md); issue IDs to [`../ISSUES.md`](../ISSUES.md).

## 1. Method
1. Verified git state, remote, CI history and toolchain (P0-E01, P0-E17).
2. Read root docs (`README.md`, `PROJECT_STATUS.md`, `TASKS.md`, `DECISIONS.md`, `NEXT_SESSION.md`,
   `docs/remediation/REGISTER.md`, `docs/acceptance/acceptance_register.csv`, `docs/security/security_review.md`,
   `docs/operations/hosted-demo.md`), CI workflow, compose/Dockerfiles, Vercel/Render configs.
3. Read the security-critical backend directly: `config.py`, `db.py`, `api/app.py`, `api/deps.py`, `authz.py`,
   `api/oidc.py`, `api/routes_core.py`, `api/routes_setup.py`, `hosting/setup.py`, `jobs.py`, worker `main.py`,
   onboarding routes/service, `lifecycle.py` (deletion), migration RLS and SECURITY DEFINER functions.
4. Three read-only sub-reviews (planning/ML/optimisation; web app; retrieval/agent/onboarding/actions/worker). Their
   top findings were re-read in code by the auditing session before being labelled VERIFIED.
5. Ran every safe baseline check available locally (P0-E02 … P0-E16) and read-only probes of the hosted demo
   (P0-E18 … P0-E21).

## 2. Architecture map (VERIFIED against code unless marked)

```
Browser ──HTTPS──► Next.js 16 web (apps/web, all pages "use client", TanStack Query, ECharts, R3F 3D)
                     │ same-origin rewrite /api/* and /health (next.config.ts)  — CSP/HSTS headers
                     ▼
                 FastAPI API (services/api/src/supplylens/api, /api/v1)
                   middleware: back-pressure 503 (per process), trace id, no-store
                   auth: signed cookie sl_session (dev login | OIDC code+PKCE) → Actor(role) → MATRIX
                   CSRF: X-Requested-With header on mutations · Idempotency-Key table · PG token-bucket limits
                     │ app role supplylens_app (NOBYPASSRLS), tenant GUC per transaction (db.tenant_session)
                     ▼
                 PostgreSQL 17 + pgvector — 38 tables FORCE RLS; control plane (tenants/users/memberships) read-only
                   SECURITY DEFINER fns (search_path pinned) for workspace/membership/OIDC/deletion
                   jobs (SKIP LOCKED, 45 s lease, fencing) · outbox · audit_events (append-only) · sandbox_erp schema
                     ▲
                 Worker (services/worker): serial loop over tenants → jobs (agent_run, export, deletion),
                   outbox dispatch to sandbox ERP, run refresh, alerts (webhook optional). Hosted demo: inline jobs.
```

| Domain | Where | What it is | Real vs simulated |
|---|---|---|---|
| Frontend | `apps/web` (15 app screens + login; 17 build routes) | Next.js 16.4.2, React 19, Tailwind 4, ECharts 6, three/R3F, ⌘K palette, themes | Real UI; no ESLint/unit tests (P2-FE-03) |
| API | `services/api/src/supplylens/api` (9 routers) | FastAPI, Pydantic v2, OpenAPI → `packages/contracts/api.d.ts` (drift-checked) | Real |
| Database | `services/api/migrations/versions/0001…0008` | Alembic; RLS policy `tenant_id = current_setting('app.tenant_id')` USING + WITH CHECK | Real (P0-E14/E15) |
| Background work | `jobs.py`, `services/worker/.../main.py`, `actions/service.py` outbox | PG queue with leases/fencing; outbox with lookup-first retry and read-back verify | Real; gaps P2-REL-01..03 |
| Forecasting | `ml/supplylens_ml` (LightGBM quantile, quantile TCN in subprocess, seasonal naive), `forecasting/service.py` | Hash-verified artifacts, replay guard, baseline fallback | Trained on real UCI sales; artifacts local-only (git-ignored); hosted demo = baseline only |
| Replenishment / optimisation | `optimisation/supplylens_opt` (CP-SAT planner, validator, lead-time-demand, temporal terms) | Integer money, MOQ/multiples, budget, capacity, explanations | Real solver; inputs simulated for UCI (D-013); P0-PLAN-01, P1-PLAN-02 |
| Retrieval | `knowledge/` (PG full-text + pgvector bge-m3 via Ollama, RRF, supersession rerank, ACL, abstention) | Two-clock temporal filtering on documents | Real; synthetic contracts + public CUAD/ACORD; abstention weak (P2-KNOW-01) |
| Agent | `agent/graph.py` (LangGraph) | Deterministic state machine, no LLM (D-041) | Real, deterministic |
| ERP integration | `integrations/sandbox_erp.py` | Local simulator in the same PG (`sandbox_erp` schema) with fault injection | **Simulated only**; no real connector (EXT-02) |
| AuthN | dev login (`routes_core.py`), OIDC (`oidc.py`, Keycloak realm in `infra/keycloak`) | Stateless signed cookie; OIDC sessions rechecked every 60 s via refresh token | OIDC verified only against local Keycloak (RECORDED) |
| AuthZ / tenancy | `authz.py` MATRIX (viewer, planner, approver, tenant_admin), RLS, document ACL (`knowledge/acl.py`) | Membership re-read per request | Real |
| Onboarding | `onboarding/` CSV (sales, stock, terms, receipts) upload → map → validate → quarantine → publish | 5 MB / row limits | Real; P2-PRIV-01 |
| Lifecycle | `lifecycle.py` export + certified deletion | Owner engine only for re-applying deletions after restore | Real |
| Infra | `docker-compose.yml` (dev profile, loopback ports, WAL archive), `infra/docker/*.Dockerfile`, `render.yaml` (unused), `vercel.json` + `scripts/vercel/build_api.py` (live demo) | — | No IaC/staging/prod (P1-OPS-01) |
| CI | `.github/workflows/ci.yml` — 8 jobs | lint, secrets+deps, backend (PG17), contracts+web build, e2e, PITR drill, compose smoke, acceptance evidence | Green on HEAD (P0-E17) |
| Research | `evaluations/`, `artifacts/experiments/*/metrics.json`, `evaluations/study_registry.json` | F1, S1, R1/R2/C1, InventoryBench, AGT | Numbers not recomputed in Phase 0 |
| Hosted demo | https://supplylens-self.vercel.app (Vercel services + Neon) | `environment=demo`, dev login on, inline jobs, lexical retrieval, baseline forecasts | Live (P0-E18); P0-SEC-01, P1-SEC-02 |

## 3. Baseline results

| Check | Result | Evidence |
|---|---|---|
| `uv lock --check` | pass | P0-E02 |
| `ruff check .` | pass | P0-E03 |
| pytest (real PG 17) | **336 passed, 6 skipped** (Keycloak) | P0-E04 |
| contract drift | pass | P0-E05 |
| `tsc --noEmit` | pass | P0-E06 |
| `next build` | pass, 17 routes | P0-E07 |
| gitleaks (history) | no leaks | P0-E08 |
| pip-audit / npm audit | 0 known vulns | P0-E09/E10 |
| Playwright (isolated DB, 6 workers) | **113 passed, 1 failed, 2 skipped**; the failure is order-dependent and passes alone | P0-E12/E13, P2-QA-01 |
| Docker compose smoke | **not run locally** (daemon down); CI job green on HEAD | PD-003, P0-E17 |
| PITR / restore drills, load test, Keycloak tests, research reruns | **not run** | EVIDENCE "Not run" |
| GitHub CI on HEAD | 8/8 jobs success (run 39813602236) | P0-E17 |
| Hosted demo | up, security headers present, public `tenant_admin` | P0-E18…E21 |

## 4. Backlog (P0–P3) — see ISSUES.md for reproduction and acceptance criteria
- **P0 (2):** P0-SEC-01 public demo admin takeover; P0-PLAN-01 default shortfall ⇒ "order nothing".
- **P1 (10):** P1-PLAN-02 lead-time sizing; P1-ACT-01 STALE re-approval 500; P1-ACT-02 unreconciled orders invisible
  to planning / CONFIRMED dead-end; P1-SEC-02 owner DSN in hosted runtime; P1-FE-01 workspace default; P1-FE-02
  receipts per location; P1-IAM-01 identity model; P1-OPS-01 no production platform; P1-SAAS-01 no SaaS plumbing;
  P1-PROC-01 unprotected `main`.
- **P2 (18):** reliability (REL-01..03), temporal/planning (PLAN-03..05), ML test gap (ML-01), retrieval abstention
  (KNOW-01), privacy (PRIV-01), body limit (API-01), web robustness (FE-03..08), E2E isolation (QA-01),
  performance (PERF-01).
- **P3 (8):** docs drift/contradictions, planner/ML/onboarding minor defects, security hygiene, CI pinning, UI polish.
- **External blockers (10):** EXT-01 … EXT-10.

Separation of evidence: **verified findings** = rows labelled VERIFIED; **plausible risks needing investigation** =
P2-REL-02, P2-API-01, P2-ML-01 (fallback part), P3-ONB-01 (NUL byte); **external blockers** = EXT-*; **unavailable
evidence** = see §6.

## 5. Seven-category scores (evidence-weighted judgement, 0–100; rules in DECISIONS PD-006)

| Category | Score | Why (strengths → gaps) |
|---|---|---|
| CTO (architecture & engineering) | **66** | Clean layering, forced RLS, contracts drift check, 336 real-DB tests + 116 browser tests, 8-job CI green, rehearsed migrations/PITR → P0-PLAN-01 in core logic, action-state dead-ends (P1-ACT-01/02), serial worker, no IaC/staging, unprotected `main` |
| CEO (product & business) | **38** | Distinctive evidence-grounded positioning, honest research with negative results, live demo → no customers, pilot, pricing or ERP; value numbers simulated; demo can be vandalised |
| COO (operations) | **42** | Runbook, PITR/restore drills, alerts + signed webhook, OTel, back-pressure → no SLOs, on-call, staging/prod, dashboards; load target missed; jobs can stick; support model absent |
| AI Engineering | **58** | Frozen chronological protocol with CIs, hash-verified artifacts, temporal retrieval 2×2 study, agent study, deterministic agent → no generative AI (by decision), lead-time and shortfall planning defects, weak abstention, gappy-ACF, no model monitoring/retraining pipeline, trained path untested |
| Security | **55** (capped ≤60 by open P0) | Forced RLS, non-owner role, CSRF, fail-closed profiles, gitleaks/pip-audit/npm audit clean, 64-case denial matrix → public admin on live demo, owner DSN in runtime, no pentest, no qualified SSO, PII retained in quarantine, unprotected `main` |
| Real MVP | **40** (capped ≤50, PD-006) | End-to-end journey works on synthetic/public data and a live demo → no real user, ERP or IdP; default recommendation wrong for costly items |
| Real SaaS | **28** | Multi-tenant data plane, CSV onboarding, export/deletion → no signup, billing, metering, per-tenant IdP, SLA, production hosting |

These are not measurements; they exist to track movement. Reaching 95+ in CEO, COO, Real MVP and Real SaaS
requires external evidence (EXT-01 … EXT-10) that code changes cannot produce.

## 6. Missing / unavailable evidence
- Local Docker compose run, PITR and restore drills, load test, Keycloak OIDC tests, research reruns (not run; §3).
- Real-data trained-model forecasts through the service (no test; artifacts local-only).
- Whether `SUPPLYLENS_SETUP_TOKEN` is still set on the hosted deployment (P0-E21: indistinguishable 404).
- Field Web Vitals, screen-reader pass, human R2 review, pentest, pilot, ERP, corporate IdP (EXT-*).
- CI logs content (only job conclusions were read).

## 7. Recommended execution order
1. **Phase 1 — Safety hotfixes (small, high value):** P0-SEC-01 (lock demo profile, reset, rate limits),
   P1-SEC-02 (remove owner DSN from serving runtime), P0-PLAN-01 (shortfall default + flagging), P1-PROC-01 (branch
   protection), P3-DOC-01/02 (make status docs truthful). Redeploy demo; verify with read-only probes.
2. **Phase 2 — Decision correctness:** P1-PLAN-02, P2-PLAN-03/04/05, P2-ML-01, P3-PLAN-06; golden tests for each.
3. **Phase 3 — Action & worker reliability:** P1-ACT-01, P1-ACT-02, P2-REL-01/02/03, P3-ONB-01 partial-state bugs.
4. **Phase 4 — Web robustness & QA:** P1-FE-01/02, P2-FE-03…08 (ESLint + unit tests in CI first), P2-QA-01, P3-FE-09.
5. **Phase 5 — Data protection & retrieval quality:** P2-PRIV-01, P2-API-01, P2-KNOW-01, P3-SEC-03, P3-ML-02.
6. **Phase 6 — Production platform & operations:** P1-OPS-01 (IaC, staging, secrets, replicas, SLOs, dashboards),
   P2-PERF-01, P3-CI-01; rerun drills and load test on that environment.
7. **Phase 7 — Identity & SaaS:** P1-IAM-01, P1-SAAS-01 — after owner decisions on SaaS scope; needs EXT-01.
8. **In parallel, owner-driven:** EXT-01 … EXT-10 (IdP, ERP sandbox, pilot users, pentest, pricing/SLA).

Phase 0 stops here; Phase 1 has not been started.

## Status update (2026-10-23, after Phase 2 — `550b427`)
- Both P0s are fixed (P0-SEC-01 verified live; P0-PLAN-01 with tests). Of the 10 P1s: 3 fixed (P1-PLAN-02, P1-ACT-01,
  P1-ACT-02), 3 partially fixed (P1-SEC-02: fixed in code, platform still injects owner variables; P1-FE-02; P1-PROC-01),
  4 open (P1-FE-01, P1-IAM-01, P1-OPS-01, P1-SAAS-01).
- The Phase 0 §7 execution order was followed for steps 1–3; Phase 2 was a security-hardening phase the owner asked for.
  The remaining order is in `../PROGRESS.md`.
- The score table above is the Phase 0 baseline; current scores are in `../PROGRESS.md`.
- The E2E order-dependent failure (P2-QA-01) and the CI lab-vitals flake (P2-QA-02) are still open.
