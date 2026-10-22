# Agent handoff — status

**Read this first.** Then `ISSUES.md` (what to fix), `DECISIONS.md` (constraints), `EVIDENCE.md` (what was proven and
how), `phases/PHASE-NN.md` (per-phase record). Update this file at the end of every phase; keep older phase rows.

## Current position
| Field | Value |
|---|---|
| Current phase | **Phase 0 — complete** (baseline audit). Phase 1 **not started**; start only on the owner's instruction. |
| Branch | `main` (only branch; `origin/main` identical at audit time) |
| Commit audited | `9fcbedb19b0831ad2599b5291569dfae309d5b6e` — "S17 e2e: find the zoomable chart by its zoom control…" |
| Working tree | Clean. The only Phase 0 change is the `docs/agent-handoff/` folder, committed locally on `main` on top of `9fcbedb`; not pushed |
| CI on audited commit | GitHub Actions run 39813602236: 8/8 jobs success |
| Hosted demo | https://supplylens-self.vercel.app — up 2026-10-22, `environment=demo` |
| Local scratch state | DB `supplylens_p0e2e` and dir `storage_p0e2e/` (git-ignored) created for isolated E2E; safe to drop: `psql -h localhost -d postgres -c "DROP DATABASE supplylens_p0e2e WITH (FORCE)"` and `rm -rf storage_p0e2e` |

## Phase log
| Phase | Dates (UTC) | Outcome | Record |
|---|---|---|---|
| 0 | 2026-10-22 | Baseline: all local static checks and builds green; pytest 336/6 skipped; Playwright 113 passed / 1 order-dependent failure / 2 skipped; 2 P0, 10 P1, 18 P2, 8 P3, 10 external blockers registered | `phases/PHASE-00.md` |

## Completed work (Phase 0)
- Repository, environment and CI baseline verified (EVIDENCE P0-E01 … P0-E21).
- Architecture map, backlog, scores and execution order (PHASE-00 §2, §4, §5, §7).
- Handoff files created; no application code, configuration under version control, or data in the `supplylens`
  database was modified.

## Blockers
- External: EXT-01 corporate IdP, EXT-02 ERP sandbox, EXT-03 pilot users, EXT-04 8 vCPU load profile, EXT-05
  screen-reader tester, EXT-06 R2 reviewer, EXT-07 pentest, EXT-08 LLM decision (D-041), EXT-09 dataset licences,
  EXT-10 pricing/SLA/support.
- Local: Docker daemon (colima) not running — needed for a local compose smoke test and Keycloak tests.

## Next actions (Phase 1 proposal — awaiting owner go-ahead)
1. P0-SEC-01: restrict the `demo` profile (no admin writes, workspace creation, imports, export/deletion for dev
   accounts; rate-limit dev-login/mutations; scheduled demo reset); tests; redeploy; read-only live probe.
2. P1-SEC-02: remove the owner DSN from the serving function; refuse to start with one in demo/production.
3. P0-PLAN-01: shortfall opt-in or penalty > unit cost; flag any shortfall; tests at/below/above unit cost.
4. P1-PROC-01: enable branch protection with required CI checks (owner action in GitHub settings).
5. P3-DOC-01/02: reconcile README / PROJECT_STATUS / TASKS / root DECISIONS with measured numbers.

## Notes for the next session
- Re-verify HEAD and CI before trusting anything here (`git rev-parse HEAD`, `gh run list --limit 3`).
- Run Playwright only against a production build and preferably an isolated DB (DECISIONS PD-002); the suite's global
  setup cancels open Demo orders.
- Root `NEXT_SESSION.md` records the owner's commit-authorship preference; check it before committing.
