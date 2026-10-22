# Remediation register (22 CTO-audit findings)

Generated from `register.json`. Audit snapshot: CTO audit of the session-2 snapshot (46/18/12/4 acceptance). Revalidated at `1636381` on 2026-10-22. Code status and verification are separate: *fixed* means the code changed; *verified* names the level of evidence that ran.

| ID | Title | At revalidation | Code | Verification | Tests / evidence | Requirements |
|---|---|---|---|---|---|---|
| F01 | Seasonal-naive point forecasts step backwards after the first week | confirmed | fixed | unit + study rerun | tests/test_seasonal_naive.py (3 new) | — |
| F02 | Forecast window admits days before the selected decision date | confirmed | fixed | unit | tests/test_remediation.py::test_F02_* (5) | — |
| F03 | The Safety buffer slider has no effect under the default policy | confirmed | fixed | unit + e2e | tests/test_remediation.py::test_F03_*<br>apps/web/e2e/remediation.spec.ts F03 | — |
| F04 | Physical capacity is dropped before optimization and validation | confirmed | fixed | PostgreSQL + CP-SAT | tests/test_remediation.py::test_F04_* (4)<br>tests/test_remediation.py::test_F04_capacity_counts_allocated_stock_and_scheduled_receipts_as_occupied | — |
| F05 | Idempotency receipt is written after the side effect | partially corrected | fixed | PostgreSQL + HTTP | tests/test_remediation.py::test_F05_* (2) | — |
| F06 | ERP read-back verification does not compare all approved line fields | confirmed | fixed | PostgreSQL + sandbox | tests/test_remediation.py::test_F06_* (6) | — |
| F07 | Expired approval prevents reconciliation of a possibly committed prior attempt | confirmed | fixed | PostgreSQL + sandbox | tests/test_remediation.py::test_F07_* | — |
| F08 | Explicit zero purchasing budget is replaced by the workspace budget | confirmed | fixed | PostgreSQL + agent | tests/test_remediation.py::test_F08_* (2) | — |
| S09 | Development authentication and insecure deployment defaults must not be exposed | partially corrected | fixed (local) | unit + local Keycloak | tests/test_oidc_keycloak.py::test_production_profile_* | — |
| S10 | Document-level permissions are not consistently enforced on indirect access paths | confirmed | fixed | PostgreSQL + HTTP | tests/test_remediation.py::test_S10_* | — |
| S11 | Approval freshness is not fully revalidated at dispatch | confirmed | fixed | PostgreSQL + sandbox | tests/test_remediation.py::test_S11_* (2) | — |
| S12 | Reconciled orders are not integrated into the next planning inventory position | confirmed | fixed | PostgreSQL + agent | tests/test_remediation.py::test_S12_*<br>tests/test_remediation.py::test_S12_erp_receipt_feed_books_each_receipt_once_and_never_above_open | — |
| S13 | The temporal RAG ablation changes two factors simultaneously | confirmed | fixed | study rerun | artifacts/experiments/R2-20261022T045503Z<br>artifacts/reports/r2_query_level.jsonl | — |
| S14 | Model resolution ignores dataset_id and can select retired versions by family | confirmed | fixed | PostgreSQL | tests/test_remediation.py::test_S14_* | — |
| S15 | Navigation and local state can lose or misrepresent planning context | confirmed | fixed | e2e | apps/web/app/(app)/scenarios/page.tsx<br>apps/web/e2e/remediation.spec.ts S15 | — |
| S16 | UI badges and summaries overstate verification | confirmed | fixed | e2e + API | evaluations/study_registry.json<br>routes_research.py | — |
| S17 | Chart theme refresh and keyboard/overlay behavior need targeted tests | partially corrected | fixed | e2e | apps/web/app/(app)/layout.tsx<br>apps/web/e2e/remediation.spec.ts S17 (theme recolour keeps zoom; radio arrow keys)<br>apps/web/e2e/resilience.spec.ts (WebGL context loss) | — |
| S18 | Onboarding and operational administration remain developer-driven | confirmed | fixed | PostgreSQL + HTTP + e2e | tests/test_onboarding.py (2)<br>e2e/remediation.spec.ts S18 | — |
| S19 | CI omits browser journeys and acceptance claims require requalification | partially corrected | fixed | CI | docs/acceptance/acceptance_register.csv<br>scripts/acceptance_evidence.py<br>.github/workflows/ci.yml job acceptance-evidence | — |
| S20 | Forecast and agent evidence is narrower than the intended product claim | confirmed | fixed | study rerun | ml/configs/forecast_study_v2.json<br>artifacts/experiments/F1-* | — |
| S21 | The current planning grain and fixed limits are a pilot slice, not multi-site enterprise planning | confirmed | fixed | PostgreSQL | tests/test_remediation.py::test_S21_* (2)<br>tests/test_remediation.py::test_S21_multi_location_sku_is_planned_per_location_with_its_own_demand_share<br>tests/test_remediation.py::test_S21_agent_drafts_carry_locations_and_receipts_need_one | — |
| S22 | Non-JSON API errors and failed session checks are not fully handled | confirmed | fixed | e2e | e2e/remediation.spec.ts S22 | — |

## Notes per finding

### F01 — Seasonal-naive point forecasts step backwards after the first week
- **Found at HEAD:** baselines.py and models.seasonal_naive_panel index k seasons back: history 1..70 gives week 2 = 57..63 (probe run at 1636381).
- **Resolution:** Both implementations index the last observed season; F1/S1 rerun under protocol 2.0.0; v1 artifacts marked superseded in evaluations/study_registry.json.

### F02 — Forecast window admits days before the selected decision date
- **Found at HEAD:** replenishment.assess: leadtime basis takes the first N forecast rows regardless of decision_date; other bases and the stockout loop have no lower bound.
- **Resolution:** Window is decision_date < day <= decision_date + window; gaps rejected; summed bases reject short forecasts; stockout walk bounded; callers forecast from min(cutoff, decision date).

### F03 — The Safety buffer slider has no effect under the default policy
- **Found at HEAD:** safety_days only affects basis q50_plus_safety; the default is now leadtime_demand (session 3), so the Scenario slider still has no effect by default.
- **Resolution:** ScenarioInput rejects controls that do not apply; result lists applied controls; UI disables non-applicable sliders with the reason.

### F04 — Physical capacity is dropped before optimization and validation
- **Found at HEAD:** scenario.py and agent/graph.py build Need(...) without capacity_units; solver and validator never receive capacity.
- **Resolution:** Residual capacity is passed as Need.capacity_units in scenario and agent; uncapped need and capacity-capped units are reported. Capacity 10/need 10/MOQ 12/pack 6 is INFEASIBLE or explicit shortfall. Headroom counts allocated stock and scheduled receipts as occupied space.

### F05 — Idempotency receipt is written after the side effect
- **Found at HEAD:** Session 3 added an atomic INSERT..ON CONFLICT claim before fn (DEF-02). Remaining: work committed before the DONE update re-runs after a crash once the claim lease lapses; agent-run/scenario/forecast retries in the web client use a new key per attempt.
- **Resolution:** Services mark the idempotency key DONE inside the business transaction (supplylens/idempotency.py); web client reuses one key per user intent (lib/api.ts intentKey).

### F06 — ERP read-back verification does not compare all approved line fields
- **Found at HEAD:** actions.service.verify compares supplier, total/currency and a SET of (sku, quantity): prices, units and duplicate lines are not compared.
- **Resolution:** Read-back compares line multisets (SKU, qty, unit, price, value), supplier, currency, total, need-by and status; sandbox has five read-back faults.

### F07 — Expired approval prevents reconciliation of a possibly committed prior attempt
- **Found at HEAD:** _dispatch checks approval expiry before the lookup-first retry, so a committed prior attempt can be marked STALE without reading the ERP.
- **Resolution:** Retries look the operation up before any approval check; a committed order is reconciled without a second execute call.

### F08 — Explicit zero purchasing budget is replaced by the workspace budget
- **Found at HEAD:** agent/graph.py accept(): int(inp.get('budget_minor') or default) turns an explicit 0 into the workspace budget.
- **Resolution:** None inherits the workspace budget, 0 stays 0, negatives rejected; the decision stores its budget and edits revalidate against it.

### S09 — Development authentication and insecure deployment defaults must not be exposed
- **Found at HEAD:** config refuses default secrets only when dev_auth is false; dev_auth defaults to true with no environment profile; compose publishes 8000/3100 on all interfaces.
- **Resolution:** SUPPLYLENS_ENVIRONMENT=production refuses dev sign-in, default secrets, owner DB credentials, insecure cookies and missing OIDC; compose ports bind to 127.0.0.1.
- **Blockers / remaining:** Verified locally and on the hosted demo (demo profile); a corporate IdP and production TLS deployment are not qualified.

### S10 — Document-level permissions are not consistently enforced on indirect access paths
- **Found at HEAD:** GET /documents/versions/{id}/labels has no allowed_roles check; agent citation lookup and evidence packets read chunks without a central document-ACL helper.
- **Resolution:** knowledge/acl.py: require_version on direct reads, redact() on terms, runs, events and action evidence; agent citations filtered by role. Structured term values stay visible (D-044).

### S11 — Approval freshness is not fully revalidated at dispatch
- **Found at HEAD:** _approval_valid checks payload hash and expiry only; terms, budget and approver permission are not rechecked before a fresh send.
- **Resolution:** A fresh send rechecks hash, expiry, approver rights, action state, spend and terms; changes route to STALE (review).

### S12 — Reconciled orders are not integrated into the next planning inventory position
- **Found at HEAD:** No purchase-order/receipt ledger; _confirm does not change on_order, so the next plan ignores confirmed open supply.
- **Resolution:** purchase_order_lines + receipts; planning adds open units and receipts since the snapshot; receipts idempotent; cancellation releases. ERP goods receipts import as CSV (kind receipts), booked once per receipt id, never above the open quantity.

### S13 — The temporal RAG ablation changes two factors simultaneously
- **Found at HEAD:** retrieval_study R2 temporal_off vs temporal_on changes mode AND rerank at once.
- **Resolution:** R2 is a 2x2 factorial (effective-date filter x supersession rerank) with query-level outcomes; the old contrast is labelled combined-pipeline.
- **Blockers / remaining:** Questions remain synthetic and not human-reviewed.

### S14 — Model resolution ignores dataset_id and can select retired versions by family
- **Found at HEAD:** resolve_model(family) ignores dataset_id and status; it can return a RETIRED or other-dataset model.
- **Resolution:** resolve_model scopes by dataset and usable status; retired only for explicit replay.

### S15 — Navigation and local state can lose or misrepresent planning context
- **Found at HEAD:** No decision-context fingerprint in the web state; scenario baseline/draft compatibility is not checked.
- **Resolution:** Scenario results carry a context fingerprint (workspace, clocks, dataset, basis); incompatible or late results are hidden and never compared. Switching workspace clears selected drafts and runs (entity ids belong to their workspace).

### S16 — UI badges and summaries overstate verification
- **Found at HEAD:** Policies maps mode=='hybrid' to a VERIFIED_LOCALLY badge; Admin maps outbox DELIVERED to RECONCILED; research headlines are hardcoded strings.
- **Resolution:** Retrieval mode no longer shown as verification; outbox DELIVERED is not RECONCILED; read-back mismatch has its own label; research headlines come from the reviewed registry with superseded runs listed.

### S17 — Chart theme refresh and keyboard/overlay behavior need targeted tests
- **Found at HEAD:** Session 3 added focus/a11y suites; theme radio group still lacks arrow-key navigation; chart theme refresh untested.
- **Resolution:** Theme switch uses native radios (arrow keys). Chart colours follow the theme without re-creating the chart, the zoom window survives; WebGL context loss and 200%-width reflow were already automated.
- **Blockers / remaining:** Manual screen-reader pass still to do (UX-010).

### S18 — Onboarding and operational administration remain developer-driven
- **Found at HEAD:** No upload/map/validate/publish API or UI; data admission is read-only; admin cannot change memberships.
- **Resolution:** CSV templates (sales, stock, terms), upload/map/validate/quarantine/publish of immutable snapshots, workspace creation, membership admin via SECURITY DEFINER functions.
- **Blockers / remaining:** One target ERP sandbox integration (BC/SAP) not built; no credentials supplied.

### S19 — CI omits browser journeys and acceptance claims require requalification
- **Found at HEAD:** CI now has lint, secret/dependency scans, backend, contracts, e2e, PITR and compose jobs (session 3). Acceptance claims predating these findings need requalification.
- **Resolution:** Acceptance rows touched by the findings were reopened and requalified against this session's tests. Every CI run links each acceptance criterion to its cited tests' results (commit, run id, run URL) as an artifact; rows citing no automated test are reported as such.

### S20 — Forecast and agent evidence is narrower than the intended product claim
- **Found at HEAD:** F1 uses one test window and is built on the F01 baseline; S1 policy choices were informed by test results.
- **Resolution:** Rolling test origins (2011-10-13, 2011-11-10) with refits; 'no clear difference detected' wording; S1 policy choice labelled exploratory.
- **Blockers / remaining:** No untouched holdout remains on UCI; a fresh dataset is needed for a confirmatory test.

### S21 — The current planning grain and fixed limits are a pilot slice, not multi-site enterprise planning
- **Found at HEAD:** agent/graph.py plan_steps: skus[:60] silently truncates; queries collapse location.
- **Resolution:** Declared limit of 60 SKUs per run: explicit lists over it are rejected, implicit scope truncation is reported; multi-location SKUs are excluded with a reason instead of collapsed. SKUs stocked at several locations are planned per location (own stock, capacity, demand share, order line).

### S22 — Non-JSON API errors and failed session checks are not fully handled
- **Found at HEAD:** apps/web/lib/api.ts JSON.parse on a non-JSON body (HTML 502) throws SyntaxError instead of ApiError; no request id surfaced.
- **Resolution:** Client parses by content type, maps gateway HTML to a status message with the trace reference; server returns JSON 500 with a reference; ErrorState distinguishes offline, denied, expired session and server errors.
