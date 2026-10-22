# Remediation register (22 CTO-audit findings)

Generated from `register.json`. Audit snapshot: CTO audit of the session-2 snapshot (46/18/12/4 acceptance). Revalidated at `1636381` on 2026-10-22. Code status and verification are separate: *fixed* means the code changed; *verified* names the level of evidence that ran.

| ID | Title | At revalidation | Code | Verification | Tests / evidence | Requirements |
|---|---|---|---|---|---|---|
| F01 | Seasonal-naive point forecasts step backwards after the first week | confirmed | open | not run | — | — |
| F02 | Forecast window admits days before the selected decision date | confirmed | open | not run | — | — |
| F03 | The Safety buffer slider has no effect under the default policy | confirmed | open | not run | — | — |
| F04 | Physical capacity is dropped before optimization and validation | confirmed | open | not run | — | — |
| F05 | Idempotency receipt is written after the side effect | partially corrected | open | not run | — | — |
| F06 | ERP read-back verification does not compare all approved line fields | confirmed | open | not run | — | — |
| F07 | Expired approval prevents reconciliation of a possibly committed prior attempt | confirmed | open | not run | — | — |
| F08 | Explicit zero purchasing budget is replaced by the workspace budget | confirmed | open | not run | — | — |
| S09 | Development authentication and insecure deployment defaults must not be exposed | partially corrected | open | not run | — | — |
| S10 | Document-level permissions are not consistently enforced on indirect access paths | confirmed | open | not run | — | — |
| S11 | Approval freshness is not fully revalidated at dispatch | confirmed | open | not run | — | — |
| S12 | Reconciled orders are not integrated into the next planning inventory position | confirmed | open | not run | — | — |
| S13 | The temporal RAG ablation changes two factors simultaneously | confirmed | open | not run | — | — |
| S14 | Model resolution ignores dataset_id and can select retired versions by family | confirmed | open | not run | — | — |
| S15 | Navigation and local state can lose or misrepresent planning context | confirmed | open | not run | — | — |
| S16 | UI badges and summaries overstate verification | confirmed | open | not run | — | — |
| S17 | Chart theme refresh and keyboard/overlay behavior need targeted tests | partially corrected | open | not run | — | — |
| S18 | Onboarding and operational administration remain developer-driven | confirmed | open | not run | — | — |
| S19 | CI omits browser journeys and acceptance claims require requalification | partially corrected | open | not run | — | — |
| S20 | Forecast and agent evidence is narrower than the intended product claim | confirmed | open | not run | — | — |
| S21 | The current planning grain and fixed limits are a pilot slice, not multi-site enterprise planning | confirmed | open | not run | — | — |
| S22 | Non-JSON API errors and failed session checks are not fully handled | confirmed | open | not run | — | — |

## Notes per finding

### F01 — Seasonal-naive point forecasts step backwards after the first week
- **Found at HEAD:** baselines.py and models.seasonal_naive_panel index k seasons back: history 1..70 gives week 2 = 57..63 (probe run at 1636381).

### F02 — Forecast window admits days before the selected decision date
- **Found at HEAD:** replenishment.assess: leadtime basis takes the first N forecast rows regardless of decision_date; other bases and the stockout loop have no lower bound.

### F03 — The Safety buffer slider has no effect under the default policy
- **Found at HEAD:** safety_days only affects basis q50_plus_safety; the default is now leadtime_demand (session 3), so the Scenario slider still has no effect by default.

### F04 — Physical capacity is dropped before optimization and validation
- **Found at HEAD:** scenario.py and agent/graph.py build Need(...) without capacity_units; solver and validator never receive capacity.

### F05 — Idempotency receipt is written after the side effect
- **Found at HEAD:** Session 3 added an atomic INSERT..ON CONFLICT claim before fn (DEF-02). Remaining: work committed before the DONE update re-runs after a crash once the claim lease lapses; agent-run/scenario/forecast retries in the web client use a new key per attempt.

### F06 — ERP read-back verification does not compare all approved line fields
- **Found at HEAD:** actions.service.verify compares supplier, total/currency and a SET of (sku, quantity): prices, units and duplicate lines are not compared.

### F07 — Expired approval prevents reconciliation of a possibly committed prior attempt
- **Found at HEAD:** _dispatch checks approval expiry before the lookup-first retry, so a committed prior attempt can be marked STALE without reading the ERP.

### F08 — Explicit zero purchasing budget is replaced by the workspace budget
- **Found at HEAD:** agent/graph.py accept(): int(inp.get('budget_minor') or default) turns an explicit 0 into the workspace budget.

### S09 — Development authentication and insecure deployment defaults must not be exposed
- **Found at HEAD:** config refuses default secrets only when dev_auth is false; dev_auth defaults to true with no environment profile; compose publishes 8000/3100 on all interfaces.

### S10 — Document-level permissions are not consistently enforced on indirect access paths
- **Found at HEAD:** GET /documents/versions/{id}/labels has no allowed_roles check; agent citation lookup and evidence packets read chunks without a central document-ACL helper.

### S11 — Approval freshness is not fully revalidated at dispatch
- **Found at HEAD:** _approval_valid checks payload hash and expiry only; terms, budget and approver permission are not rechecked before a fresh send.

### S12 — Reconciled orders are not integrated into the next planning inventory position
- **Found at HEAD:** No purchase-order/receipt ledger; _confirm does not change on_order, so the next plan ignores confirmed open supply.

### S13 — The temporal RAG ablation changes two factors simultaneously
- **Found at HEAD:** retrieval_study R2 temporal_off vs temporal_on changes mode AND rerank at once.

### S14 — Model resolution ignores dataset_id and can select retired versions by family
- **Found at HEAD:** resolve_model(family) ignores dataset_id and status; it can return a RETIRED or other-dataset model.

### S15 — Navigation and local state can lose or misrepresent planning context
- **Found at HEAD:** No decision-context fingerprint in the web state; scenario baseline/draft compatibility is not checked.

### S16 — UI badges and summaries overstate verification
- **Found at HEAD:** Policies maps mode=='hybrid' to a VERIFIED_LOCALLY badge; Admin maps outbox DELIVERED to RECONCILED; research headlines are hardcoded strings.

### S17 — Chart theme refresh and keyboard/overlay behavior need targeted tests
- **Found at HEAD:** Session 3 added focus/a11y suites; theme radio group still lacks arrow-key navigation; chart theme refresh untested.

### S18 — Onboarding and operational administration remain developer-driven
- **Found at HEAD:** No upload/map/validate/publish API or UI; data admission is read-only; admin cannot change memberships.

### S19 — CI omits browser journeys and acceptance claims require requalification
- **Found at HEAD:** CI now has lint, secret/dependency scans, backend, contracts, e2e, PITR and compose jobs (session 3). Acceptance claims predating these findings need requalification.

### S20 — Forecast and agent evidence is narrower than the intended product claim
- **Found at HEAD:** F1 uses one test window and is built on the F01 baseline; S1 policy choices were informed by test results.

### S21 — The current planning grain and fixed limits are a pilot slice, not multi-site enterprise planning
- **Found at HEAD:** agent/graph.py plan_steps: skus[:60] silently truncates; queries collapse location.

### S22 — Non-JSON API errors and failed session checks are not fully handled
- **Found at HEAD:** apps/web/lib/api.ts JSON.parse on a non-JSON body (HTML 502) throws SyntaxError instead of ApiError; no request id surfaced.
