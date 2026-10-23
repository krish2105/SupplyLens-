# Prompt to start the next working session

Paste everything inside the fence into a new session that has this repository checked out (or can clone it).

```text
SUPPLYLENS — CONTINUE THE PRODUCTION-READINESS PROGRAM FROM PHASE 6
Repository: https://github.com/krish2105/SupplyLens-  (branch main)
Last hand-over: the Phase 5 commits after 36f4f9d (Phases 0–5 and 4B are complete for their delivered scope; check the
latest CI run on main before trusting this).

Act as a Principal Software Engineer and QA lead. You are continuing a multi-phase program; previous sessions left a
durable record in docs/agent-handoff/. Do not rely on any chat history: the repository is the only source of truth.

1. RESTORE CONTEXT (no code changes yet)
   - Verify: git rev-parse HEAD; git status; git log --oneline -12; gh run list --workflow ci.yml --branch main --limit 3;
     gh pr list (Dependabot PRs are expected and unmerged).
   - Read in this order: docs/agent-handoff/STATUS.md, PROGRESS.md, ISSUES.md, DECISIONS.md, EVIDENCE.md,
     phases/PHASE-00.md … PHASE-05.md and PHASE-04B.md; then root NEXT_SESSION.md, PROJECT_STATUS.md, DECISIONS.md (D-001…D-087),
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
     Expected baseline: 447 passed, 6 skipped (Keycloak); web: `npm --prefix apps/web run lint` (0 warnings), `test` (19),
     `typecheck`. Browser suite: see STATUS.md (disposable stack `supplylens_p4ci`, run with SUPPLYLENS_E2E_ALLOW_DESTRUCTIVE=1;
     `--project desktop --project mobile --project webkit --project mobile-safari` → 191 passed, 7 skipped). Screenshot
     regression: `npx playwright test --project visual` (42 baselines per platform, darwin locally, linux in CI). CI: 217
     passed, 8 skipped on five projects + 42 visual. Migration head 0010.
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
   - Lab Web Vitals targets stay as they are; QA-4B-01 (one CI sample of INP 224 ms on /inventory) is open, not waived.
   - Illustrations: do not generate images. A02/A13/A16 stay withheld until the owner approves the briefs in
     PHASE-04B.md §8.
   - Generative inference stays disabled (D-041) unless the owner says otherwise. Purchasing stays deterministic and
     approval-gated; model monitoring recommends, it never promotes, rolls back or orders by itself.
   - Never import torch in the pytest process (D-023); run torch code in a child process as tests/test_phase5_ml.py does.
   - Research results: label every number by kind (historical backtest, simulation, offline evaluation with generated
     labels, real outcome — there are none yet). Do not re-tune on a test half; superseded runs go to
     evaluations/study_registry.json with a reason. A lower MAE is not a business benefit (S2 showed the opposite).
   - External evidence (corporate IdP, ERP sandbox, pilot users, penetration test, certification) stays BLOCKED or
     UNVERIFIED until it really happens.

4. PHASE 6 — PLANNING DEPTH AND DATA PROTECTION (unless the owner gives a different phase brief, follow theirs instead)
   First ask the owner for the rationing objective when the budget binds (PLAN-P5-01); do not choose it yourself.
   Scope from ISSUES.md: PLAN-P5-01 (after that decision, re-run S2 under a new frozen config), P3-PLAN-06 rest, ML-P5-05
   (zero-aware interval calibration under a new frozen protocol), KNOW-P5-03 (new frozen task set), P2-REL-03;
   SEC-P2-12 (tamper-evident audit), SEC-P2-13 (retention jobs), P3-SEC-03 (nonce CSP), P2-PRIV-01 backfill, P3-ONB-01
   rest, D-056 duplicate-draft warning, PERF-P3-09 (ANN/halfvec only with the retrieval studies re-run), FE-P4-08,
   QA-4B-01. Reproduce first, test, keep API compatibility. Any UI you touch keeps the Phase 4B gate green (ui-quality
   spec, visual project, axe, no overflow against the configured viewport).

5. COMPLETION
   - Update docs/agent-handoff/STATUS.md, ISSUES.md (status + evidence id per issue), EVIDENCE.md (exact commands and
     results, P6-E01…), DECISIONS.md, PROGRESS.md, and create docs/agent-handoff/phases/PHASE-06.md (findings, fixes,
     files changed and why, tests run with results, remaining risks, next actions).
   - Commit and push; confirm CI and the Vercel deploy; run only non-destructive live checks.
   - Finish with a concise summary: fixes, commands and results, failures, blockers, next actions.
   - STOP after Phase 6. Do not begin Phase 7.

Later phases (for orientation only; see PROGRESS.md): 7 production platform and operations (incl. PERF-P3-08/10, the declared
load profile); 8 identity and SaaS (owner decisions and a corporate IdP first).
```
