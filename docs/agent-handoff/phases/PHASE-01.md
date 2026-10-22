# Phase 1 — core correctness and procurement safety

**Dates:** 2026-10-22/23 (UTC) · **Start:** `main` @ `8171994` · **Code commit:** `037e42b` · **Scope decision:**
DECISIONS PD-007 (safety fixes end to end, then Phase 1; Phase 2+ not started).

Evidence IDs `P1-E..` are in [`../EVIDENCE.md`](../EVIDENCE.md); issue IDs in [`../ISSUES.md`](../ISSUES.md); product
decisions D-051 … D-060 in the root [`DECISIONS.md`](../../DECISIONS.md).

## 1. Context restored
- Verified branch/commit (`main`, `8171994`, clean) and read STATUS, ISSUES, EVIDENCE, DECISIONS, PHASE-00.
- Re-read the code behind every targeted finding before changing it (planner objective and validator; agent
  compute/check/prepare; scenario; positions; approve/dispatch/confirm; jobs and worker; config/db/hosting entrypoint;
  web approvals/runs). Every Phase 0 claim acted on was re-confirmed in source.

## 2. Critical operations traced (API entry → commit → resulting state)
| Operation | Path | Invariant now enforced | Test |
|---|---|---|---|
| Scenario / plan | `POST /scenarios` → `run_scenario` → `assess` per lead time → `plan` (2-pass CP-SAT) → `validate` → `plan_runs` insert | Shortfall only when a hard constraint binds; each supplier covers its own lead-time requirement; no conflicting term planned; data as known at the cutoff | `test_P0_PLAN_01_*`, `test_P1_PLAN_02_*`, `test_P2_PLAN_03/05_*` |
| Investigation | `POST /agent-runs` (idempotent) → job → worker `execute_run` → GATHER (known-at-cutoff positions incl. committed orders) → COMPUTE → CHECK (warnings/issues) → PREPARE (unique per run+supplier) | No silent shortfall; no double buy while an approved order is in flight; one draft per run and supplier | `test_P0_PLAN_01_agent_*`, `test_P1_ACT_02_*`, `test_P2_REL_02_*` |
| Approval | `POST /actions/{id}/approve` → role, SoD, payload hash, row version, term recheck → approval + outbox (insert or reset of a FAILED row) in one transaction | Re-approval after STALE reuses the operation key; never while a dispatch is active | `test_P1_ACT_01_*` |
| Dispatch | worker `dispatch_once` → lookup-first on retries → fresh-send recheck → sandbox execute → read-back verify → RECONCILED / CONFIRMED / STALE / UNKNOWN | (unchanged, re-verified) one remote order per key | `test_P1_ACT_01_*` (`count_for_key == 1`), existing F05–F07/S11 tests |
| Mismatch resolution | `POST /actions/{id}/accept-remote` → approver ≠ preparer → ledger from the target's lines → RECONCILED, audited | CONFIRMED is no longer a dead end; ledger reflects what the target holds | `test_P1_ACT_02_*accept*` |
| Jobs | `jobs.claim` → `expire_exhausted` first | Exhausted lease ⇒ job FAILED, run FAILED, `job_failed` alert | `test_P2_REL_01_*` |
| Demo access | `Actor.require` | In `demo`, admin.write / tenant.export / tenant.delete refused for every role | `test_P0_SEC_01_*`, live P1-E14 |
| Serving config | `Settings._fail_closed`; Vercel `index.py` | Demo/production never serve with an owner DB URL | `test_S09_*`, `test_P1_SEC_02_*`, live P1-E13 |

## 3. Fixes implemented
| Issue | Severity | Fix | Files |
|---|---|---|---|
| P0-SEC-01 | P0 | Demo lockdown of administration/export/deletion; visitor orders released after 1 h on demo sign-in (audited, system actor) | `services/api/src/supplylens/demo.py` (new), `authz.py`, `api/routes_core.py` |
| P0-PLAN-01 | P0 | Two-pass lexicographic objective (uncovered units, then cost); shortfall explanation; agent warning / `shortfall_unmet` issue; UI shows warnings | `optimisation/supplylens_opt/planner.py`, `agent/graph.py`, `api/schemas.py`, web `approvals`, `runs` |
| P1-PLAN-02 | P1 | `Need.required_units_by_lead_time`; per-offer coverage constraint; validator checks the chosen lead time; scenario/agent assess each lead time | `planner.py`, `validator.py`, `planning/scenario.py`, `agent/graph.py` |
| P1-ACT-01 | P1 | Approve resets a FAILED outbox row (same key, lookup-first) or refuses while a dispatch is active | `actions/service.py` |
| P1-ACT-02 | P1 | Committed-but-unreconciled orders count as open supply; `accept_remote_order` + route; e2e setup settles leftovers | `planning/positions.py`, `actions/service.py`, `api/routes_decisions.py`, `apps/web/e2e/global-setup.ts`, web `approvals` |
| P1-SEC-02 | P1 | Optional owner URL with `owner_database_url`; refusal in demo/production unless `maintenance` or setup token; Vercel entrypoint scrubs owner variables; Render `--serve` mode | `config.py`, `db.py`, `migrations/env.py`, `hosting/setup.py`, `scripts/vercel/build_api.py`, `scripts/render/env.py`, `scripts/render/start.sh` |
| P1-FE-02 (part) | P1 | Receipt quantities and row keys per SKU@location | web `approvals/page.tsx` |
| P1-PROC-01 (part) | P1 | Branch protection: required deterministic checks, no force-push/deletion | GitHub settings (P1-E15) |
| P2-REL-01 | P2 | `expire_exhausted` before every claim; alert kind `job_failed` | `jobs.py`, `alerts.py`, migration 0009, web `exceptions` label |
| P2-REL-02 | P2 | Heartbeat survives transient DB errors; unique draft per run+supplier; agent treats conflict as already prepared | `jobs.py`, migration 0009, `agent/graph.py` |
| P2-PLAN-03 | P2 | Positions, open supply, shares, dependence and capacity read at `min(cutoff, eff)` | `planning/scenario.py`, `agent/graph.py` |
| P2-PLAN-04 | P2 | Calendar-aligned ACF (`ordinals`) | `optimisation/supplylens_opt/leadtime_demand.py`, `planning/demand_history.py` |
| P2-PLAN-05 | P2 | Scenario excludes conflicting terms, reports `excluded_for_conflict` | `planning/scenario.py`, `api/schemas.py` |
| P2-FE-05 (part) | P2 | One idempotency key per investigation start; keys on retry/reconcile | web `runs`, `approvals` |
| P3-DOC-01/02 | P3 | README numbers and status; PROJECT_STATUS current-state section; root DECISIONS scope note superseded by D-050; TASKS/NEXT_SESSION point to the handoff | root docs |

Also changed: `tests/test_rehearsals.py` (HEAD constant 0009), `tests/test_remediation.py` and
`tests/test_oidc_keycloak.py` (profile tests for the owner-URL rule), `packages/contracts/*` (regenerated),
`docs/operations/hosted-demo.md` (safeguards, schema-upgrade procedure), `services/api/src/supplylens/hosting/setup.py`
(response label), migration `0009_one_draft_per_run_supplier.py` (new), `tests/test_phase1_correctness.py` (new, 38 tests).

API compatibility: additive only — new route `POST /api/v1/actions/{id}/accept-remote`, new optional response fields
(`checks.warnings`, `terms.excluded_for_conflict`, `needs[*].required_units_by_lead_time`). `SUPPLYLENS_ADMIN_DATABASE_URL`
is now optional; development/test fall back to the published local default. Data preserved: migration 0009 only adds an
index and widens a check constraint; its downgrade refuses to drop `job_failed` alerts.

## 4. Tests executed (all results observed)
| What | Result | Evidence |
|---|---|---|
| Phase 1 regression file | 38 passed | P1-E03 |
| Full backend suite | 374 passed, 6 skipped (Keycloak) | P1-E04 |
| Migration rehearsals | 7 passed | P1-E05 |
| ruff, lockfile, contracts, tsc, next build | pass | P1-E01, E02, E07 |
| Playwright (isolated DB) ×2 | 114 passed, 2 skipped, 0 failed — twice | P1-E08, E09 |
| UI mismatch acceptance | works end to end | P1-E10 |
| Hosted demo: migration, redeploy, lockdown and health probes | pass | P1-E11 … E14 |
| CI on `037e42b` (run 39831397239) | success, 8/8 jobs | P1-E17 |

Failures observed during the phase and resolved: an overflow in a single weighted objective at large prices (replaced
by the two-pass solve); a missing `alerts_kind_check` value (added in 0009); test assumptions about demand shares and
forecast origins (tests corrected, behaviour was right). The CI failure on `8171994` (INP timing) is recorded as P2-QA-02.

## 5. Invariants now covered by repeatable tests
1. With the constraints allowing full coverage, the plan never leaves demand uncovered, whatever the unit cost.
2. A shortfall is always explained and never passes silently (warning to the approver, or review required).
3. The chosen supplier covers the requirement for its own lead time; the validator rejects a line sized for another.
4. A replay never reads stock recorded after its knowledge cutoff.
5. No plan uses a conflicting term.
6. An approved order counts as supply from approval until it is reconciled into the ledger, exactly once.
7. A STALE action can be re-approved and is sent once, under the same operation key.
8. A read-back mismatch is resolved only by an approver other than the preparer, and the ledger reflects the target.
9. A job that died on its last attempt fails its run and raises an alert.
10. The database refuses a second draft for the same run and supplier.
11. In the public demo, no role can administer the workspace, export or delete it.
12. Demo and production never serve with owner database credentials.

## 6. Remaining correctness risks (not fixed in Phase 1)
- **Pending drafts are not supply** (D-056): two drafts for the same need can both be approved if approved close together.
  Mitigation idea: warn at approval when another approved/committed order covers the same SKU since the decision date.
- **P2-REL-03**: serial worker; outbox re-claim has no heartbeat or attempt cap (relies on target-side idempotency).
- **CSV terms `known_at`** is user-supplied (no system recorded-at), so backdated imports change replays.
- **P2-KNOW-01** abstention, **P2-PRIV-01** quarantined personal data, **P2-API-01** body limit, **P2-ML-01**
  trained-model path test — untouched.
- **P1-FE-01** workspace default; inventory/3D single-location keys (rest of P1-FE-02).
- **P2-QA-01/02**: shared-fixture race and lab-vitals thresholds can still fail CI e2e.
- **P1-SEC-02 residual**: Vercel injects owner variables at process start; only the owner can scope them.

## 7. Blockers
External blockers EXT-01 … EXT-10 unchanged. No new blocker. Docker daemon still not running locally.

## 8. Next actions (Phase 2 proposal — not started)
1. Decide P2-QA-02 handling (budget per runner, or move lab vitals to a non-gating job) and P2-QA-01 isolation; then
   add `e2e` to required checks.
2. Phase 2 per PHASE-00 §7: remaining planning/ML items (P2-ML-01, P3-PLAN-06, P3-ML-02) and the approval-time
   duplicate-commitment warning above.
3. Owner: scope the Neon integration variables away from the web service (P1-SEC-02 residual); decide whether
   Git-triggered Vercel builds should be disabled (P3-OPS-02).
