# Agent handoff — decisions

Durable record of design decisions and trade-offs that later sessions must respect. The full historical log
(D-001 … D-050) lives in the repository-root [`DECISIONS.md`](../../DECISIONS.md) and is **not** duplicated here;
this file (a) lists the standing decisions that constrain the production-readiness program, as read from that log,
and (b) records decisions made by the handoff program itself (prefix `PD-`).

Labels: **VERIFIED** = confirmed against code or a command in this repository; **RECORDED** = stated in the
root decision log, not re-verified; **INFERRED** = reasoning from code, not executed.

## Standing owner decisions that constrain every phase (from root DECISIONS.md)

| Ref | Decision | Consequence for the program | Label |
|---|---|---|---|
| D-004, D-041 | No generative LLM; extractive answers and a deterministic LangGraph agent | "AI Engineering" maturity cannot be raised by adding generative inference unless the owner reverses D-041. Agent ablations (ML-006) stay not run. | RECORDED; agent determinism VERIFIED in `services/api/src/supplylens/agent/graph.py` (no model client imported) |
| D-005 | Local `bge-m3` via Ollama for embeddings; lexical fallback | Hosted demo has no embeddings (lexical-only, labelled degraded) | RECORDED |
| D-009 | `tenants`, `users`, `memberships` are control-plane tables without RLS, read-only to the app role | Verified: 38 of 44 public tables FORCE RLS; the 6 without are control-plane (`alembic_version`, `auth_sessions`, `memberships`, `tenant_deletions`, `tenants`, `users`) | VERIFIED (pg_class query, EVIDENCE.md P0-E14) |
| D-017, D-018 | Dev sign-in via signed HttpOnly cookie + CSRF header; `?ws=` workspace only on GET | Stateless sessions; dev sessions cannot be revoked server-side (security review F-06) | VERIFIED (`api/deps.py`) |
| D-035 | Full-text search keeps RLS and accepts a sequential scan per tenant | Retrieval cost grows linearly with a tenant's chunks; load target met at 4 req/s, not 5 | RECORDED |
| D-037 | Work is pushed straight to `main` (no PR flow) | No branch protection / review gate is evidenced. Revisit before any team or customer use. | RECORDED |
| D-039 | Identity = local Keycloak (OIDC code + PKCE), not qualified against a corporate IdP | One platform-wide IdP; roles come from a `<slug>:<role>` claim | VERIFIED (`api/oidc.py`) |
| D-043 | Declared pilot scale: 60 SKUs per run | Hard product limit; enterprise scale is out of scope until revisited | RECORDED |
| D-049 | Production profile fails closed (no dev auth, no default secrets, Secure cookies, OIDC required) | Verified in `config.py::_fail_closed` | VERIFIED |
| D-050 | Public demo on Vercel (Next.js + FastAPI services, Neon), `demo` profile with public role accounts, inline jobs | Demo accounts are shared and writable, including `tenant_admin` (see ISSUES P0-SEC-01) | VERIFIED (hosted `/api/v1/auth/dev-users`, 2026-10-22) |

Repository-level instructions recorded in `NEXT_SESSION.md` (not re-verified as owner instructions; treat as the
owner's stated preference until told otherwise): commits are authored as the owner and must not mention any AI
assistant; Playwright runs against a production build (`next start`), not the dev server.

## Program decisions (this handoff program)

| ID | Date (UTC) | Decision | Reason | Trade-off |
|---|---|---|---|---|
| PD-001 | 2026-10-22 | Handoff files live in `docs/agent-handoff/` and are the durable memory for later sessions; root `PROJECT_STATUS.md`, `TASKS.md`, `EVIDENCE_INDEX.md`, `DECISIONS.md` are left untouched in Phase 0 | User instruction: preserve existing records; Phase 0 must not change behaviour | Two sets of status documents exist; Phase 1 should reconcile root docs with the verified numbers in ISSUES P3-DOC-01 |
| PD-002 | 2026-10-22 | Phase 0 browser E2E ran against an isolated database `supplylens_p0e2e` (migrated, bootstrapped without UCI, synthetic e2e fixture) and storage dir `storage_p0e2e`, not the developer's `supplylens` database | The suite's global setup cancels open Demo orders; running it on the dev DB mutates local data | Matches CI's data shape (synthetic fixture), not the real UCI data |
| PD-003 | 2026-10-22 | Local Docker compose smoke test not run in Phase 0 (Docker daemon/colima not running); CI `compose-smoke` job on HEAD is cited instead | Starting the VM and building images (PyTorch layer) is slow and out of a read-only audit's scope | Local compose evidence is CI-only for this commit |
| PD-004 | 2026-10-22 | Destructive behaviours on the live hosted demo were **not** exercised (membership removal, workspace creation); findings about them are from code plus the public account listing | Probing would damage a shared public demo | Those findings are VERIFIED from code, not from a live reproduction |
| PD-005 | 2026-10-22 | Severity scale: P0 = must fix before any real customer data or public exposure (security, data loss, integrity); P1 = blocks a credible production pilot / SaaS launch; P2 = important robustness, scale or quality gap; P3 = polish, documentation, hygiene | Shared scale for later phases | — |
| PD-006 | 2026-10-22 | Scores in PHASE-00 are evidence-weighted judgements, not measurements; a category cannot exceed 60 while a P0 in it is open, and "Real MVP"/"Real SaaS" cannot exceed 50 without real-customer evidence (pilot, ERP, IdP) | Prevents score inflation from local-only evidence | Scores will move slowly until external blockers clear |
| PD-007 | 2026-10-22 | The request "do the recommended order e2e, then Phase 1" was executed as: step 1 (safety fixes) end to end including the hosted demo, then Phase 1 (core correctness: steps 2–3). Steps 4–7 (web robustness, privacy/retrieval, production platform, identity/SaaS) were not started | The Phase 1 brief says to stop after Phase 1 and not begin Phase 2 | Some web P1s (P1-FE-01, inventory part of P1-FE-02) stay open |
| PD-008 | 2026-10-22 | Product decisions taken in Phase 1 are recorded in the root decision log as D-051 … D-060 (demo lockdown, owner credentials, coverage-first planning, lead-time requirement, cutoff-bounded replays, committed supply and mismatch acceptance, re-approval key, job failure and draft uniqueness, calendar lags, scenario conflicts) | One project decision log; this file keeps program-level decisions | — |
| PD-009 | 2026-10-22 | Hosted schema changes go through the temporary setup token (add sensitive variable → deploy → `/setup/schema` → remove → redeploy); the serving function otherwise never holds owner credentials | Follows from D-052 | Two production deploys per migration |
| PD-010 | 2026-10-22 | Branch protection requires only the deterministic CI jobs and exempts admins | e2e has timing flakes (P2-QA-02); owner pushes directly (D-037) | Admin pushes are still not gated; tighten after P2-QA-02 |
| PD-011 | 2026-10-23 | Before Phase 2, Git pushes were made to deploy on Vercel (P3-OPS-02) at the owner's request ("push e2e so Vercel takes it") | Every later phase can verify the live demo from a push | The api service's documents are now committed under deploy/vercel-api/hosted_storage |
| PD-012 | 2026-10-23 | Phase 2 security decisions are D-061 … D-067 in the root log; the finding-by-finding report is phases/PHASE-02.md | One decision log | — |
| PD-013 | 2026-10-23 | Dependabot pull requests are proposals: none is merged without review (several are major versions, e.g. TypeScript 7, actions v7/v8) | A security tool must not silently change the toolchain | Open PRs accumulate until reviewed |

| PD-014 | 2026-10-23 | Phase 3 followed the owner's performance brief ("PERFORMANCE, SCALABILITY AND BACKEND RELIABILITY"), not the web-robustness scope proposed in the hand-over prompt, as that prompt itself directs when the owner gives a different brief. The web-robustness items (P1-FE-01, P1-FE-02 rest, P2-FE-03…08, P2-QA-01/02, P3-FE-09/10) stay PENDING; only the web changes overload handling needed were made (busy banner, Retry-After retries, truncation note) | The owner pasted both briefs in one message; the hand-over prompt yields to an owner brief | Web robustness moves to the next phase |
| PD-015 | 2026-10-23 | Phase 3 benchmarks ran on the owner's laptop (Apple M4 Pro, 12 cores, 24 GB, macOS; API, PostgreSQL 17.11, embedding stub and driver on one machine), before and after on the same data, driver, durations and machine. The 2026-10-21 4 vCPU results are reported beside them, never compared as like for like | Only this hardware was available; the declared 8 vCPU / 32 GiB profile (EXT-04) was not | No production or declared-profile claim; real embedding latency excluded (stub) |
| PD-016 | 2026-10-23 | Migration 0010 reaches the hosted database through the temporary setup token (PD-009) at deploy time; the serving code does not depend on it for lexical-only retrieval, so the demo keeps working between the push and the migration | Schema changes must not wait for a manual window, and the serving function must not hold owner credentials | Two production deploys for this push |
| PD-017 | 2026-10-23 | Phase 4 followed the owner's brief "Frontend, UX and complete E2E workflows", which covers the web-robustness items deferred by PD-014 plus the twelve user journeys | Owner brief | — |
| PD-018 | 2026-10-23 | The local disposable database `supplylens_p0e2e` was polluted by a Phase 4 test draft (receipts booked on the shared reference SKU are permanent). Because the owner's standing instruction forbids dropping databases, it was left as it is and a new CI-equivalent disposable database `supplylens_p4ci` (bootstrap with `SUPPLYLENS_UCI_ZIP=/nonexistent`, then `seed_e2e_fixture.py`) was created; `supplylens_p4e2e` (same, but with the real UCI data) also exists as local scratch. Launch configs `p4-api`, `p4-worker` | No-drop rule; reproducible test data | Three local test databases |
| PD-019 | 2026-10-23 | Journeys that change stock for good (receipts) run in a freshly onboarded workspace created through the product's own imports (e2e/helpers.ts `onboardWorkspace`), never in the shared Demo reference case | Receipts are an append-only ledger | One new workspace per run on a disposable stack |
| PD-020 | 2026-10-23 | Firefox could not be launched on this machine (the bundled Firefox build exits "Could not find profile folder" on macOS 27, even started directly); Firefox journeys run in CI only. No physical device was used: "mobile" means Chromium Pixel 7 and WebKit iPhone 13 emulation | Environment | Local cross-browser evidence is Chromium and WebKit |
| PD-021 | 2026-10-23 | The owner declined, for now, to add the `e2e` job to the required checks on `main` ("Not yet"), after the first fully green five-browser run (P4-E15) | Owner decision | A red browser run does not block merges; it still fails the CI run and is recorded |
