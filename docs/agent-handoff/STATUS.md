# Agent handoff — status

**Read this first.** Then `ISSUES.md` (what to fix), `DECISIONS.md` (constraints), `EVIDENCE.md` (what was proven and
how), `phases/PHASE-NN.md` (per-phase record). Update this file at the end of every phase; keep older phase rows.

## Current position
| Field | Value |
|---|---|
| Current phase | **Phase 2 — complete for its delivered scope** (enterprise security hardening; checkpoint list in PHASE-02 §5). Phase 3 **not started**; start only on the owner's instruction. |
| Branch | `main` (protected: required checks lint, secrets-and-dependencies, backend, contracts-and-web; no force-push/deletion; admins exempt) |
| Code commits | `ec6c208` (Git pushes deploy on Vercel), `1813f43` (Phase 2 security fixes); the handoff/docs commit follows (see `git log`) |
| CI on `1813f43` | run 39836268410: **8/8 jobs success** (EVIDENCE P2-E13) |
| Deploys | **Every push to `main` now deploys** (Vercel Git integration). `1813f43` is live at https://supplylens-self.vercel.app; session revocation and demo lockdown verified live (P2-E15, P2-E16) |
| Database schema | migration head **0009** (unchanged in Phase 2) |
| Dependabot | 7 open PRs opened by the new config (actions, TypeScript 7, web-vitals 6) — proposals, not merged (PD-013) |
| Local scratch state | DB `supplylens_p0e2e` + `storage_p0e2e/` (git-ignored) for the disposable browser stack; its local launch config sets `SUPPLYLENS_E2E_DISPOSABLE=true`. Run the suite with `SUPPLYLENS_E2E_ALLOW_DESTRUCTIVE=1` |

## Phase log
| Phase | Dates (UTC) | Outcome | Record |
|---|---|---|---|
| 0 | 2026-10-22 | Baseline: 2 P0, 10 P1, 18 P2, 8 P3, 10 external blockers; pytest 336/6; Playwright 113/1/2 | `phases/PHASE-00.md` |
| 1 | 2026-10-22/23 | Both P0s and five P1s fixed; demo lockdown live; pytest 374/6; Playwright 114/2 ×2; CI 8/8 | `phases/PHASE-01.md` |
| 2 | 2026-10-23 | Git pushes deploy (P3-OPS-02). Security: 10 findings fixed (fixture safety, revocable sessions, body cap and sign-in throttle, error disclosure, PII redaction, supply-chain pins, IdP outage, parser 500s, 404 consistency); 3 new open (retrieval ceiling, audit tamper-evidence, retention). pytest 398/6; Playwright 114/2; no certification claimed | `phases/PHASE-02.md` |

## Open P0/P1 after Phase 2
- P0: none open.
- P1 open: P1-FE-01, P1-FE-02 remainder, P1-IAM-01 (needs EXT-01), P1-OPS-01, P1-SAAS-01, P1-PROC-01 remainder,
  P1-SEC-02 residual (owner must scope the Neon integration variables).

## Blockers
- External: EXT-01 … EXT-10 unchanged; corporate IdP qualification and penetration test remain **not performed**.
- Local: Docker daemon (colima) not running — no local compose smoke, image scan or Keycloak tests.

## Next actions (Phase 3 proposal — awaiting owner go-ahead)
1. PHASE-02 §5 security checkpoint items (per-tenant retrieval ceiling, distributed sign-in throttle, retention jobs,
   tamper-evident audit, nonce CSP, Docker digests).
2. Stabilise CI e2e (P2-QA-01/02) and require it in branch protection.
3. Review the Dependabot PRs (majors need code changes and full CI).
4. Owner: scope Neon variables away from the web service; decide on admin exemption from branch protection.

## Notes for the next session
- Re-verify HEAD and CI before trusting anything here (`git rev-parse HEAD`, `gh run list --workflow ci.yml --branch main`).
- A push to `main` deploys production. Hosted schema changes still need the temporary setup token (PD-009,
  `docs/operations/hosted-demo.md`); after changing `uv.lock`, run `python3 scripts/vercel/build_api.py --pin`.
- pytest refuses non-local or non-`_test` databases; the browser suite refuses to reset data unless the stack is proven
  disposable (D-065).
- New migrations must bump `HEAD` in `tests/test_rehearsals.py`.
- Root `NEXT_SESSION.md` records the owner's commit-authorship preference; check it before committing.
