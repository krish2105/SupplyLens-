# Prompt to start the next working session

Paste everything inside the fence into a new session that has this repository checked out (or can clone it).

```text
SUPPLYLENS — CONTINUE THE PRODUCTION-READINESS PROGRAM FROM PHASE 7
Repository: https://github.com/krish2105/SupplyLens-  (branch main)
Last hand-over: the Phase 6 commits after e9ed389 (Phases 0–6 and 4B are complete for their delivered scope; check the
latest CI run on main before trusting this).

Act as a Principal Software Engineer and QA lead. You are continuing a multi-phase program; previous sessions left a
durable record in docs/agent-handoff/. Do not rely on any chat history: the repository is the only source of truth.

1. RESTORE CONTEXT (no code changes yet)
   - Verify: git rev-parse HEAD; git status; git log --oneline -12; gh run list --workflow ci.yml --branch main --limit 3;
     gh pr list (Dependabot PRs are expected and unmerged).
   - Read in this order: docs/agent-handoff/STATUS.md, PROGRESS.md, ISSUES.md, DECISIONS.md, EVIDENCE.md,
     phases/PHASE-00.md … PHASE-06.md and PHASE-04B.md; then root NEXT_SESSION.md, PROJECT_STATUS.md, DECISIONS.md (D-001…D-093),
     README.md, docs/operations/hosted-demo.md.
   - Treat every recorded claim as a lead, not proof. Re-check in code what you will rely on. Label statements VERIFIED,
     INFERRED or UNVERIFIED where it matters. Never invent results, files, credentials or evidence.

2. ENVIRONMENT
   - Same machine as before: local PostgreSQL 17 + pgvector, uv, Node, the git-ignored data/, storage/ and model files
     may already exist; check before recreating anything.
   - Fresh machine: follow PROGRESS.md "What is NOT on GitHub" and root NEXT_SESSION.md "Run it". Minimum for tests:
     PostgreSQL 17 + pgvector with roles supplylens_owner / supplylens_app (passwords *_dev) and database supplylens_test
     (copy the CI workflow's "databases and roles" step), then `uv sync`, `npm --prefix apps/web ci`,
     `uv run alembic -c services/api/alembic.ini upgrade head` against supplylens_test, `uv run pytest -q`.
     Expected baseline: 477 passed, 6 skipped (Keycloak); web: `npm --prefix apps/web run lint` (0 warnings), `test` (19),
     `typecheck`. Browser suite: see STATUS.md (disposable stack `supplylens_p4ci`, run with SUPPLYLENS_E2E_ALLOW_DESTRUCTIVE=1;
     `--project desktop --project mobile --project webkit --project mobile-safari` → 175 passed, 7 skipped; then lab vitals
     alone: `--project vitals-desktop --project vitals-mobile --workers 1` → 18 passed). Screenshot
     regression: `npx playwright test --project visual` (42 baselines per platform, darwin locally, linux in CI). CI: 217
     passed, 8 skipped on five projects + 42 visual. Migration head 0011 (the hosted database may still be at 0010: OPS-P6-03).
   - Never point tests at a real database: pytest refuses anything but a local *_test database, and the browser suite
     only resets data on a proven disposable stack (D-065). Do not weaken these guards.

3. RULES THAT CARRY OVER
   - A push to main deploys the public demo (https://supplylens-self.vercel.app) through the Vercel Git integration.
     Push only code that passed ruff, pytest, the contract check, tsc and the web build locally.
   - main is protected (required: lint, secrets-and-dependencies, backend, contracts-and-web). CI has 8 jobs; record the
     run id and result of every push in EVIDENCE.md.
   - Commit as the repository owner: Krishna Mathur <113384784+krish2105@users.noreply.github.com>. Do not mention any AI
     assistant in commits, code or documents (owner instruction in NEXT_SESSION.md).
   - New migrations: bump HEAD in tests/test_rehearsals.py; hosted schema changes need the temporary setup-token
     procedure (DECISIONS PD-009, docs/operations/hosted-demo.md). After changing uv.lock run
     `python3 scripts/vercel/build_api.py --pin` — also after any change to API, worker, ML or optimiser code (it
     refreshes deploy/vercel-api/source.sha256; without it Vercel does not rebuild the api service and CI fails).
   - Hosted data migrations run as Neon's owner, which bypasses row-level security: scope per-tenant copies with an
     explicit tenant predicate (see migration 0010 and its rehearsal).
   - Never disable authentication, row-level security, audit logging, approval enforcement, CSRF, rate limits or the
     demo lockdown to make something pass. Never run destructive actions against the hosted demo or any external system.
   - Do not merge Dependabot PRs without reviewing and testing them (PD-013).
   - Screenshot baselines (apps/web/e2e/visual.spec.ts-snapshots/) change only after you look at the new images and the
     change is intended (D-080). Never run --update-snapshots just to make a run pass. A UI change that alters a
     critical screen needs both darwin and linux baselines refreshed: linux ones come from the CI artifact
     visual-baselines-linux (delete the affected *-linux.png, push, review the recorded images, commit).
   - Lab Web Vitals targets stay as they are. Measure them alone (vitals-* projects, --workers 1): beside other suites they
     measure the machine, not the app (QA-4B-01).
   - Illustrations: do not generate images. A02/A13/A16 stay withheld until the owner approves the briefs in
     PHASE-04B.md §8.
   - No real ERP exists: never claim ERP integration passed; never create real orders without approval. Every adapter goes
     through integrations/contract.py and must pass the conformance suite (tests/test_phase6_erp.py) before it is registered.
   - Serving code must keep working on the previous schema until the hosted database is migrated (D-090).
   - Generative inference stays disabled (D-041) unless the owner says otherwise. Purchasing stays deterministic and
     approval-gated; model monitoring recommends, it never promotes, rolls back or orders by itself.
   - CI has no embedding model: before pushing retrieval changes also run `SUPPLYLENS_OLLAMA_URL=http://127.0.0.1:9 uv run pytest -q`
     (lexical only), as a local Ollama hides differences (QA-P5-02).
   - Never import torch in the pytest process (D-023); run torch code in a child process as tests/test_phase5_ml.py does.
   - Research results: label every number by kind (historical backtest, simulation, offline evaluation with generated
     labels, real outcome — there are none yet). Do not re-tune on a test half; superseded runs go to
     evaluations/study_registry.json with a reason. A lower MAE is not a business benefit (S2 showed the opposite).
   - External evidence (corporate IdP, ERP sandbox, pilot users, penetration test, certification) stays BLOCKED or
     UNVERIFIED until it really happens.

4. PHASE 7 — PRODUCTION PLATFORM AND OPERATIONS (unless the owner gives a different phase brief, follow theirs instead)
   First ask the owner for the hosting platform, database tier, budget and on-call decision (P1-OPS-01, docs/operations/
   slo.md); do not choose or spend yourself. Scope: infrastructure as code, staging, secret manager, HA database with
   off-host WAL archive and an archiving alert, ≥ 2 API instances and workers, external uptime probe and paging; rerun
   scripts/recovery_drill.sh and scripts/outage_drill.sh on that platform; PERF-P3-08/10, the declared load profile
   (EXT-04), distributed sign-in throttle, Docker digests. Carried items: see STATUS.md "Next actions".

5. COMPLETION
   - Update docs/agent-handoff/STATUS.md, ISSUES.md (status + evidence id per issue), EVIDENCE.md (exact commands and
     results, P7-E01…), DECISIONS.md, PROGRESS.md, and create docs/agent-handoff/phases/PHASE-07.md (findings, fixes,
     files changed and why, tests run with results, remaining risks, next actions).
   - Commit and push; confirm CI and the Vercel deploy; run only non-destructive live checks.
   - Finish with a concise summary: fixes, commands and results, failures, blockers, next actions.
   - STOP after Phase 7. Do not begin Phase 8.

Later phases (for orientation only; see PROGRESS.md): 8 identity and SaaS (owner decisions and a corporate IdP first).
```
