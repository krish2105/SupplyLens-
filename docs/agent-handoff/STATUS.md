# Agent handoff — status

**Read this first.** Then `PROGRESS.md` (cross-phase map and remaining order), `ISSUES.md` (what to fix),
`DECISIONS.md` (constraints), `EVIDENCE.md` (what was proven and how), `phases/PHASE-NN.md` (per-phase record). To start a
new session, paste the prompt in `NEXT_SESSION_PROMPT.md`. Update this file at the end of every phase; keep older rows.

## Current position
| Field | Value |
|---|---|
| Current phase | **Phase 5 complete** (2026-10-24): AI/ML, retrieval, optimisation and MLOps (owner brief). Panel-date defect fixed (ML-P5-01, the TCN's weekday inputs were constant) and F1 re-run as 2.1.0; trained-model fallbacks, verified artifact loading, promotion gate, monitoring/shadow/drift report; decision-level study S2 (simulated: lower MAE did not lower cost); answer-support/ambiguity rules with study R3. No generative model; purchasing unchanged (deterministic, approval-gated). Next: Phase 6 only on the owner's instruction. |
| Branch | `main` (protected: required checks lint, secrets-and-dependencies, backend, contracts-and-web; no force-push/deletion; admins exempt) |
| Code commits | Phase 5: see `git log` after `36f4f9d` (code + Linux Research baselines). Phase 4B: `967ba0b` (changes), `85f9b6b` (Linux screenshot baselines, evidence); evidence commit follows. Phase 4: `bf2c757`, `1f914a8`. Phase 3: `8a0bb4d`, `66cd20a`, `542ca72` |
| CI | Phase 5: see EVIDENCE P5-E15. Phase 4B: `967ba0b` run 39905285613: **8/8 success**, browser suites 217 passed / 8 skipped on five projects (P4B-E11); `85f9b6b` run 39906427424: 8/8, screenshot regression compared on Linux, 42 passed (P4B-E14). Earlier: `98c838a` failed one lab-vitals sample (QA-4B-01) |
| Deploys | Pushes to `main` deploy through the Vercel Git integration **when a file under a service root changes** — backend code changes must re-pin `deploy/vercel-api/source.sha256` (`build_api.py --pin`; CI enforces it). `542ca72` is live at https://supplylens-self.vercel.app (P3-E19) |
| Database schema | migration head **0010** (`chunk_vectors`; Phase 5 added none); local dev DB `supplylens` migrated 0008 → 0010 in Phase 5 (backup taken, P5-E01) and its registry holds TCN 2.1.0 as champion; hosted Neon migrated to 0010 (P3-E17), token removed and redeployed (P3-E18) |
| Dependabot | 7 open PRs opened by the new config (actions, TypeScript 7, web-vitals 6) — proposals, not merged (PD-013) |
| Local scratch state | DB `supplylens_p0e2e` + `storage_p0e2e/` (git-ignored) for the disposable browser stack (launch config sets `SUPPLYLENS_E2E_DISPOSABLE=true`; run with `SUPPLYLENS_E2E_ALLOW_DESTRUCTIVE=1`). DB `supplylens_load` (1 GB, migrated to 0010) holds the reference load data; `storage_load/`. **Browser stack now `supplylens_p4ci`** (launch configs `p4-api`, `p4-worker`, `p0-web`; PD-018); `supplylens_p0e2e` keeps polluted reference data, `supplylens_p4e2e` is scratch with real UCI data |

## Phase log
| Phase | Dates (UTC) | Outcome | Record |
|---|---|---|---|
| 0 | 2026-10-22 | Baseline: 2 P0, 10 P1, 18 P2, 8 P3, 10 external blockers; pytest 336/6; Playwright 113/1/2 | `phases/PHASE-00.md` |
| 1 | 2026-10-22/23 | Both P0s and five P1s fixed; demo lockdown live; pytest 374/6; Playwright 114/2 ×2; CI 8/8 | `phases/PHASE-01.md` |
| 2 | 2026-10-23 | Git pushes deploy (P3-OPS-02). Security: 10 findings fixed (fixture safety, revocable sessions, body cap and sign-in throttle, error disclosure, PII redaction, supply-chain pins, IdP outage, parser 500s, 404 consistency); 3 new open (retrieval ceiling, audit tamper-evidence, retention). pytest 398/6; Playwright 114/2; no certification claimed | `phases/PHASE-02.md` |
| 3 | 2026-10-23 | Performance (owner brief): historical 5 req/s collapse not reproducible on the M4 Pro; vectors moved to `chunk_vectors` (0010), admission classes/queue/workspace share, statement and pool timeouts → 503, bounded listings, `/metrics`, outbox dead letter, worker isolation. Same machine before → after: retrieval p95 256 → 157 ms at 5/s; 16/s fully served (p95 442 ms) vs ~8/s before. pytest 414/6; Playwright 116/2. Laptop, stubbed embedder: not the declared profile | `phases/PHASE-03.md` |
| 4 | 2026-10-23 | Frontend/UX/E2E (owner brief): 12 journeys pass; document upload added (journey 4); P1-FE-01/02, P2-FE-03…08, P2-QA-01/02, P3-FE-10 fixed; ESLint + Vitest + typed e2e in CI; Firefox/WebKit/iPhone projects. pytest 419/6; Playwright 174/4 locally (Firefox CI-only) | `phases/PHASE-04.md` |
| 4B | 2026-10-23 | Visual/UX gate (owner brief): 166 captures × before/after (17 screens, 16 states, 2 themes, 3 widths); 13 defects fixed (phone navigation and header, sign-in, tables, misleading £0 materiality, loading/empty labels, empty 3D under errors, off-screen reader, tablet anchors, chart motion, duplicate request); illustrations: 13 reused, A02/A13/A16 withheld with briefs. pytest 421/6; Playwright 191/7 locally; 42 screenshot baselines | `phases/PHASE-04B.md` |
| 5 | 2026-10-23/24 | AI/ML, retrieval, optimisation, MLOps (owner brief): ML-P5-01 (P1) fixed and F1 2.1.0 (TCN − LightGBM −0.20 [−0.46, +0.03], no clear difference; corrects 2.0.0); P2-ML-01, ML-P5-02, P3-ML-02, KNOW-P5-01 fixed; P2-KNOW-01 partly; promotion gate + monitoring endpoint; S2: no cost benefit from lower MAE (simulated); R3: ambiguity 0/4 → 3/4, out-of-scope 0/26 → 10/26 at a cost on reworded questions; phone overflow on Research/Forecast fixed and its test made able to fail. pytest 447/6; Playwright 191/7 locally; 42 screenshot baselines | `phases/PHASE-05.md` |

## Open P0/P1 after Phase 5
- P0: none open. Phase 5 found and fixed one P1 (ML-P5-01); no other P0/P1 status changed.
- P1 open: P1-IAM-01 (needs EXT-01), P1-OPS-01, P1-SAAS-01, P1-PROC-01 remainder,
  P1-SEC-02 residual (owner must scope the Neon integration variables).

## Blockers
- External: EXT-01 … EXT-10 unchanged; corporate IdP qualification and penetration test remain **not performed**.
- Local: Docker daemon (colima) not running — no local compose smoke, image scan or Keycloak tests.

## Next actions (Phase 6 proposal — awaiting owner go-ahead)
0. Owner decisions: the rationing objective when the budget binds (PLAN-P5-01); A02/A13/A16 image briefs (PHASE-04B §8);
   whether to fund human review of retrieval questions (EXT-06) and a pilot (EXT-03).
1. Planning/ML depth: PLAN-P5-01 after the decision; P3-PLAN-06 rest; ML-P5-05 (zero-aware interval calibration under a
   new frozen protocol); KNOW-P5-03 (new frozen task set); P2-REL-03.
2. Data protection carried from the old Phase 5 proposal: SEC-P2-12, SEC-P2-13, P3-SEC-03 (nonce CSP), P2-PRIV-01
   backfill, P3-ONB-01 rest, D-056 duplicate-draft warning, PERF-P3-09 (with the retrieval studies re-run).
3. Watch QA-4B-01 (lab INP on CI) and FE-P4-08.
4. Review the Dependabot PRs; owner: scope Neon variables; branch-protection admin exemption.

## Notes for the next session
- Re-verify HEAD and CI before trusting anything here (`git rev-parse HEAD`, `gh run list --workflow ci.yml --branch main`).
- A push to `main` deploys production. Hosted schema changes still need the temporary setup token (PD-009,
  `docs/operations/hosted-demo.md`); after changing `uv.lock`, run `python3 scripts/vercel/build_api.py --pin`.
- pytest refuses non-local or non-`_test` databases; the browser suite refuses to reset data unless the stack is proven
  disposable (D-065).
- New migrations must bump `HEAD` in `tests/test_rehearsals.py` (now 0010).
- Never import torch in the pytest process (D-023): Phase 5 tests run torch code in a child process.
- Superseded experiments are listed with reasons in `evaluations/study_registry.json`; the Research page shows reviewed
  headlines only from there.
- Root `NEXT_SESSION.md` records the owner's commit-authorship preference; check it before committing.
