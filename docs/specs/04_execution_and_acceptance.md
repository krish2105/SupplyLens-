# 4 Execution and acceptance

## Purpose and authority

This chapter turns the product and technical requirements into a repeatable engineering workflow. Use it alongside the master prompt. The application has not been implemented by this document pack. Requirement targets are proposed release conditions; the evidence register begins with every result marked not run.

The implementation agent should work within the selected project and available tools, inspect before changing existing files, and preserve the user's datasets. Routine local development is authorized by the launch request. A specific external action must have the applicable authority and permissions. A blocked deployment, unavailable credential, or absent customer dataset does not prevent independent local work. Prepare the exact payload or deployment plan before requesting missing authorization.

## Recommended repository structure

Use one repository with these responsibilities. Preserve equivalent established conventions if the folder already contains a project.

| Location | Responsibility |
| --- | --- |
| apps/web/ | Next.js application, routes, components, chart and 3D views |
| services/api/ | FastAPI service, business modules, authorization and versioned endpoints |
| services/worker/ | Durable ingestion, training, indexing and execution jobs |
| packages/contracts/ | Generated frontend types and shared API contract fixtures |
| ml/ | Dataset adapters, feature pipelines, model training and evaluation |
| optimisation/ | Inventory state, constraints, objective definitions and simulation |
| evaluations/ | Frozen task sets, retrieval labels, ablations and experiment runners |
| tests/ | Unit, integration, tenant-isolation, recovery and browser journeys |
| data/raw/ | Immutable source files or documented references to an approved store |
| data/processed/ | Versioned derived datasets with source lineage |
| knowledge/raw/ | Original supplier and policy documents |
| artifacts/ | Model artifacts, reports and evidence with retention rules |
| docs/specs/ | The implementation specification and source register |
| docs/operations/ | Installation, deployment, recovery and user guides |
| infra/ | Container definitions and the qualified deployment configuration |
| execution_pack/ | The original launch documents and templates |

Do not create application modules that are merely empty placeholders to satisfy this map. Group closely related packages where it keeps imports and deployment simpler. Keep raw files, secrets, model caches and customer exports out of source control. Use a documented artifact store for large model weights; retain checksums and retrieval instructions.

## First session deliverables

Inspect files and tool capabilities. Create a data inventory with only metadata needed for qualification; do not dump sensitive rows into logs or chat. Record runtime choices and verify official package compatibility. Write a concise plan and start a thin working path that spans the database, API and browser.

Implement the first development commands and actually run them. Provide equivalent commands for environment diagnostics, dependency installation, database migration, local startup, development import, baseline training, smoke tests and browser tests. Commands are part of the future implementation deliverable; this pack does not pretend that those scripts exist already.

The first useful demonstration is a validated import visible in the inventory or sales screen, a baseline prediction tied to that import, a deterministic planning result, and a persisted decision record. If the real source supports only sales forecasting, the inventory part uses an isolated, explicitly marked fixture. Build the genuine data adapter and identify which missing fields prevent operational claims.

## A concrete reference scenario

Use the supplied policy_change_scenario.json as a test fixture. It is deliberately synthetic and contains no real supplier terms. Keep it separate from research datasets and live tenant records.

One product requires 30 units by 22 October 2026. No units are available or already inbound. The purchasing budget is USD 180. Supplier A charges USD 5 per unit, has a 10-unit order increment, and can deliver by the deadline. Its original minimum order was 20 units. A known amendment becomes effective on 20 October and changes the minimum to 40 units. Supplier B charges USD 6 per unit, has a 10-unit minimum and a 5-unit increment, and can also deliver by the deadline. All relevant constraints and prices are specified; this fixture is a deterministic procurement calculation, not a learned forecast experiment.

At the 19 October decision time, the applicable original policy allows an order of 30 units from A for USD 150. At the 20 October decision time, A's minimum requires a USD 200 order, exceeding the budget. B can supply 30 units for USD 180, so the new feasible minimum-cost plan is B. The fixture's amendment is known before its effective date, allowing the test to distinguish knowledge time from effective time.

Required behaviour: the evidence panel identifies the appropriate policy version; the optimiser returns the correct feasible action; charts and tables show the same scenario; the 3D view displays the selected product; the previous approval is invalidated when its input state is revised; an edited payload needs fresh validation; and replaying the same execution request does not create a second order. Final success requires reading the saved order and reconciling its quantities and supplier.

If the amendment has not yet been observed at a historical knowledge cutoff, the backtest must not use it. The scenario fixture includes a delayed-knowledge variant for this purpose. When two active policies conflict and precedence is unresolved, return a review-required state with the conflicting sources. Do not invent a source hierarchy to make the problem solvable.

## Reference acceptance scenarios

| ID | Gate | Required result |
| --- | --- | --- |
| EXE-001 | P0 | Bootstrap and documented startup succeed in a clean supported development environment; the report identifies exact versions and commands. |
| EXE-002 | P0 | Raw-file hashes are unchanged after import, feature preparation and training; all modifications reside in derived outputs. |
| EXE-003 | P0 | The reference policy-change scenario produces A 30 units for USD 150 before the amendment and B 30 units for USD 180 after it. |
| EXE-004 | P0 | A document not known at the historical cutoff cannot affect a backtest answer, citation, model input or action. |
| EXE-005 | P0 | An unresolved active-policy conflict yields review required with both sources and no submitted action. |
| EXE-006 | P0 | Selection, filters and scenario changes propagate across the chart, table, 3D scene, evidence and action drawer without mixing run versions. |
| EXE-007 | P0 | A double click and an identical replay produce one persisted sandbox order for one idempotency key; the UI retains the original result. |
| EXE-008 | P0 | A changed quantity, budget, source state or approval expiry prevents reuse of the old approval. |
| EXE-009 | P0 | A timeout after an external success is resolved by reconciliation, with no blind resend while the outcome is unknown. |
| EXE-010 | P0 | Theme reload, narrow viewport, keyboard navigation and WebGL failure leave the full reference workflow usable. |
| EXE-011 | P0 | A prompt-injection instruction embedded in a supplier document cannot change tenant scope, tool permissions, spending limits or the execution destination. |
| EXE-012 | P0 | Every completed requirement has evidence; tests not executed remain not run, and blocked live integrations remain unqualified. |
| EXE-013 | P1 | The selected ERP sandbox passes the same action lifecycle and reconciliation contract using documented target-specific behavior. |
| EXE-014 | P2 | The contracted production workload, supported configuration and operational owner are recorded with the release acceptance and rollback evidence. |

These are test specifications with expected outcomes, not recorded test passes. Add edge cases when an observed risk or implementation requirement justifies them; avoid writing tests that merely repeat the code's internal arrangement.

## Shared terms and calculation rules

An as-of time is the knowledge cutoff for a decision. Effective time is when a policy applies. Event time is when an operational event occurred. Ingestion time is when SupplyLens received it. Preserve all relevant timestamps and use them consistently when replaying decisions. Backdated corrections require a new version; they must not silently rewrite the historical knowledge state.

Available stock, allocated stock, on-order stock and inventory position must have explicit definitions, units and treatment of partial receipts. Maintain an event ledger or another auditable transactional representation. Quantities use an appropriate exact decimal or integer representation for the product's unit. Money uses fixed-precision decimals or integer minor units with currency-specific scale. Store currency codes and conversion provenance; binary floating-point is not the authority for monetary reconciliation.

Use forecast quantiles as alternative uncertainty summaries for the same horizon. The upper and lower quantiles are not separate demand streams to add together. Keep prediction intervals distinct from uncertainty around an evaluation score. Use common demand paths across inventory-strategy comparisons. State whether unmet demand is lost, delayed or backordered; the simulator's assumptions determine the business interpretation.

Store point-in-time snapshots or sufficient versioned inputs to replay an action. Labels, source timestamps and model versions must be available in exported evidence. Redaction and document permissions still apply to exports and traces.

## Persistent progress and handoff

PROJECT_STATUS.md records the currently verified gate, the active task, exact next action, last successful commands, known blockers and running jobs. TASKS.md records requirement IDs, dependencies, work state, evidence and defect severity. DECISIONS.md records consequential choices, accepted assumptions and existing authorization scope. EVIDENCE_INDEX.md links verified claims to artifacts and commands. These are project conventions chosen for this brief, not special file names that every agent environment automatically requires. [O3]

Read the actual working tree before resuming. Preserve verified work and incorporate new user instructions. If a session ends, save useful commands, test output paths, job IDs and an exact restart point. Do not imply that a stopped session continues processing in the background. A fresh agent should be able to recover from the saved files without relying on inaccessible conversational memory.

## Required final application handover

The handover includes runnable source; setup and environment templates; migrations; supported deployment definitions; source and rights register; import reports; model and data cards; saved model weights or approved artifact references; prediction, retrieval, action and business evaluation; browser interaction evidence; accessibility and performance results; identity and tenant-isolation evidence; recovery exercises; integration status; user and administrator instructions; and a release readiness report.

The dissertation package includes research questions, related-work matrix, fixed comparison protocol, dataset and feature definitions, leakage controls, baseline and ablation results, uncertainty, negative results, error taxonomy, compute and inference cost, limitations and reproducibility instructions. The commercial package includes buyer/problem definition, supported capability matrix, pilot charter, deployment/data flow, evidence-based value model, integration scope and support assumptions.

End an implementation session by stating what works, what changed, what was actually verified, what remains blocked, and the exact next action. Avoid replacing the outstanding backlog with a claim of completion.

## Official execution references

[O1] OpenAI, Get started with ChatGPT Work, checked 20 October 2026. learn.chatgpt.com source . Work can use available files and approved tools; local access depends on the environment.

[O2] OpenAI, Projects and chats, checked 20 October 2026. learn.chatgpt.com source . Explains attaching local folders and the distinction between conversation sync and local file access.

[O3] OpenAI, Iterating Development Workflows with Codex, 3 August 2026, checked 20 October 2026. developers.openai.com source . Describes persistent repository instructions and optional planning/context conventions. The workflow and authorization choices in this SupplyLens pack are specific to the user's implementation request.
