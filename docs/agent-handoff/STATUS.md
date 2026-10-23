# Agent handoff — status

**Read this first.** Then `PROGRESS.md` (cross-phase map and remaining order), `ISSUES.md` (what to fix),
`DECISIONS.md` (constraints), `EVIDENCE.md` (what was proven and how), `phases/PHASE-NN.md` (per-phase record). To start a
new session, paste the prompt in `NEXT_SESSION_PROMPT.md`. Update this file at the end of every phase; keep older rows.

## Current position
| Field | Value |
|---|---|
| Current phase | **Phase 4 complete** (2026-10-23): frontend, UX and end-to-end journeys (owner brief, PD-017); all 12 journeys pass (PHASE-04 §1). Next: Phase 5, only on the owner's instruction. |
| Branch | `main` (protected: required checks lint, secrets-and-dependencies, backend, contracts-and-web; no force-push/deletion; admins exempt) |
| Code commits | Phase 4: see `git log` after `55e0b1c`. Phase 3: `8a0bb4d`, `66cd20a`, `542ca72` |
| CI | Phase 4 push: EVIDENCE P4-E12. Phase 3: runs 39857106309 and 39858808675, 8/8 |
| Deploys | Pushes to `main` deploy through the Vercel Git integration **when a file under a service root changes** — backend code changes must re-pin `deploy/vercel-api/source.sha256` (`build_api.py --pin`; CI enforces it). `542ca72` is live at https://supplylens-self.vercel.app (P3-E19) |
| Database schema | migration head **0010** (`chunk_vectors`); hosted Neon migrated to 0010 (P3-E17), token removed and redeployed (P3-E18) |
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

## Open P0/P1 after Phase 4
- P0: none open. (Phase 3 changed no P0/P1 status; P2-PERF-01, P2-REL-03 partially fixed, SEC-P2-11 fixed per process.)
- P1 open: P1-IAM-01 (needs EXT-01), P1-OPS-01, P1-SAAS-01, P1-PROC-01 remainder,
  P1-SEC-02 residual (owner must scope the Neon integration variables).

## Blockers
- External: EXT-01 … EXT-10 unchanged; corporate IdP qualification and penetration test remain **not performed**.
- Local: Docker daemon (colima) not running — no local compose smoke, image scan or Keycloak tests.

## Next actions (Phase 5 proposal — awaiting owner go-ahead)
1. Data protection and retrieval quality (P2-KNOW-01, SEC-P2-11…13, PERF-P3-09); FE-P4-08; propose `e2e` as a required check.
2. Remaining security checkpoint items (distributed sign-in throttle, retention jobs, tamper-evident audit, nonce CSP,
   Docker digests).
3. Performance follow-ups: PERF-P3-08 (compute isolation), PERF-P3-09 (ANN/halfvec with study re-run), the declared
   load profile with real embeddings (EXT-04).
4. Review the Dependabot PRs; owner: scope Neon variables; branch-protection admin exemption.

## Notes for the next session
- Re-verify HEAD and CI before trusting anything here (`git rev-parse HEAD`, `gh run list --workflow ci.yml --branch main`).
- A push to `main` deploys production. Hosted schema changes still need the temporary setup token (PD-009,
  `docs/operations/hosted-demo.md`); after changing `uv.lock`, run `python3 scripts/vercel/build_api.py --pin`.
- pytest refuses non-local or non-`_test` databases; the browser suite refuses to reset data unless the stack is proven
  disposable (D-065).
- New migrations must bump `HEAD` in `tests/test_rehearsals.py` (now 0010).
- Root `NEXT_SESSION.md` records the owner's commit-authorship preference; check it before committing.
