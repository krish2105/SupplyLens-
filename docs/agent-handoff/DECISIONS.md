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
