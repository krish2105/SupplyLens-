# Agent handoff — status

**Read this first.** Then `ISSUES.md` (what to fix), `DECISIONS.md` (constraints), `EVIDENCE.md` (what was proven and
how), `phases/PHASE-NN.md` (per-phase record). Update this file at the end of every phase; keep older phase rows.

## Current position
| Field | Value |
|---|---|
| Current phase | **Phase 1 — complete for its delivered scope** (core correctness and procurement safety). Phase 2 **not started**; start only on the owner's instruction. |
| Branch | `main` (protected: required checks lint, secrets-and-dependencies, backend, contracts-and-web; no force-push/deletion; admins exempt) |
| Code commit | `037e42b` — "Phase 1: demo lockdown, owner credentials out of serving, procurement correctness"; the handoff/docs commit follows it (see `git log`) |
| CI on code commit | GitHub Actions run 39831397239: **8/8 jobs success** |
| Database schema | migration head **0009** (local test DBs and the hosted Neon database) |
| Hosted demo | https://supplylens-self.vercel.app — redeployed 2026-10-23 from `037e42b` (CLI deploy), lockdown verified live (EVIDENCE P1-E14) |
| Local scratch state | DB `supplylens_p0e2e` (now at 0009) and dir `storage_p0e2e/` (git-ignored) for isolated E2E; safe to drop. Launch configs `p0-api`, `p0-worker`, `p0-web` in a local, git-excluded launch config start the stack on it |

## Phase log
| Phase | Dates (UTC) | Outcome | Record |
|---|---|---|---|
| 0 | 2026-10-22 | Baseline: static checks and builds green; pytest 336/6 skipped; Playwright 113 / 1 order-dependent failure / 2 skipped; 2 P0, 10 P1, 18 P2, 8 P3, 10 external blockers | `phases/PHASE-00.md` |
| 1 | 2026-10-22/23 | Both P0s fixed (demo lockdown verified live; coverage-first planning); P1 fixed: PLAN-02, ACT-01, ACT-02, SEC-02 (residual), FE-02 (approvals part), PROC-01 (partial); P2 fixed: REL-01, REL-02, PLAN-03/04/05, FE-05 (part); docs reconciled. pytest 374/6 skipped; Playwright 114/2 skipped ×2; CI 8/8; 3 new findings (P2-QA-02, P3-OPS-02, P3-FE-10) | `phases/PHASE-01.md` |

## Open P0/P1 after Phase 1
- P0: none open.
- P1 open: P1-FE-01 (workspace default), P1-FE-02 remainder (inventory/3D keys), P1-IAM-01 (identity model; needs
  EXT-01), P1-OPS-01 (production platform), P1-SAAS-01 (SaaS plumbing; owner scope decision), P1-PROC-01 remainder
  (admins exempt; e2e not required), P1-SEC-02 residual (owner must scope Neon integration variables).

## Blockers
- External: EXT-01 … EXT-10 (unchanged; see ISSUES.md).
- Local: Docker daemon (colima) not running — local compose smoke and Keycloak tests not run (CI compose-smoke green).

## Next actions (Phase 2 proposal — awaiting owner go-ahead)
1. Stabilise CI e2e (P2-QA-02 lab-vitals thresholds on shared runners; P2-QA-01 shared fixture), then require `e2e`.
2. Approval-time warning when another committed order already covers the same SKU (remaining D-056 risk).
3. Remaining planning/ML: P2-ML-01 (trained-model service test, artifact fallback), P3-PLAN-06, P3-ML-02.
4. Owner actions: scope Neon variables away from the web service; decide on Git-triggered Vercel builds (P3-OPS-02).

## Notes for the next session
- Re-verify HEAD and CI before trusting anything here (`git rev-parse HEAD`, `gh run list --limit 3`).
- Hosted schema changes: temporary `SUPPLYLENS_SETUP_TOKEN` → deploy → `/setup/schema` → remove → redeploy (PD-009,
  `docs/operations/hosted-demo.md`). Rebuild the bundle first: `uv run python scripts/vercel/build_api.py --storage build/hosted-storage`.
- New migrations must bump `HEAD` in `tests/test_rehearsals.py`.
- Run Playwright against a production build on an isolated DB (PD-002); `e2e/global-setup.ts` now also settles CONFIRMED
  and UNKNOWN_OUTCOME test orders.
- Root `NEXT_SESSION.md` records the owner's commit-authorship preference; check it before committing.
