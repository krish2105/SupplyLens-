# 1 Product and commercial requirements

Planning edition: 20 October 2026. This chapter specifies work to be built and verified. It does not describe an existing deployment, customer contract, certification or demonstrated commercial result. The intended starting point is an empty project folder; the owner will provide real datasets. Numerical acceptance targets below are proposed engineering targets, not measured performance claims.

## Product charter and buyer

SupplyLens is an inventory planning and procurement execution application that turns operational data, trained forecasts and applicable supplier evidence into reviewable replenishment decisions. Its core business promise is precise: help a planner understand an inventory exception, compare feasible responses, authorize the appropriate action and verify what happened. The application must retain the evidence and financial assumptions behind each decision.

The initial commercial wedge is a replenishment team in a retailer, distributor or spare-parts operation that has usable SKU-location history, stock positions and supplier terms. The implementation must support organizational boundaries from the beginning: tenant, legal entity, business unit, location, warehouse and user role. Choose one operational segment for the first evaluation; design extension points for additional segments without pretending the first model generalizes automatically.

Economic buyer: supply-chain director, operations director or procurement head. Daily users: demand planners, inventory controllers, buyers and approvers. Evaluation stakeholders: finance, enterprise architecture, information security, data owners and model-risk reviewers. System administrators need administration and recovery tools, not authority to make business purchases by default.

The buyer-facing claim is an auditable decision workflow with evaluated forecasting and controlled execution. "Advanced AI" is a description of the implementation, not the commercial benefit. Product differentiation must ultimately be demonstrated against the buyer's current planning process and relevant alternatives. No specification can guarantee that a multinational company will purchase the product.

## The primary workflow

1. Connect and qualify data. Import provided records, identify source ownership, map identifiers and units, reconcile totals, report missing inputs and quarantine invalid records. Preserve original values and provenance. A sales-only dataset may enable forecasting; it does not establish live stock, supplier delivery performance or real purchasing authority.
2. Monitor exceptions. Present projected shortages, excess stock, unreliable arrivals and policy changes with materiality, freshness and uncertainty. Distinguish observed events from predicted events. Let the planner filter by business scope, owner, service priority and decision deadline.
3. Investigate with evidence. The agent retrieves applicable supplier terms, prior decisions and operational records; it calls forecasting and optimization tools. The user sees concise action summaries, sources and tool outcomes, not invented explanations or hidden reasoning transcripts.
4. Compare feasible plans. Show order, transfer, defer and expedite options when supported by data. Display expected cost, service implications, constraints, uncertainty, affected stock and assumptions. An infeasible problem returns a useful constraint explanation rather than an invented plan.
5. Review and authorize. Present the exact line items, recipient system, monetary scope, current source version and policy evidence. Apply the organization's existing approval policy. Distinguish permission to analyze, prepare a draft, create an external draft and commit a purchase.
6. Execute and reconcile. Submit the authorized operation with an idempotency key. After a timeout, check the external system before retrying. Preserve pending and uncertain states. Confirm the authoritative order ID and state before showing success.
7. Learn and measure. Record acceptance, edits, overrides, outcomes and reviewer reasons. Monitor forecast performance and operating results. Changes to models, retrieval configurations or action policies enter a versioned evaluation-and-release process.
## Differentiated product capabilities

Decision evidence. Every actionable recommendation opens a packet containing the data cutoff, forecast version, source documents, applicable policy dates, optimization assumptions, constraint results, proposed action and final outcome. A reviewer can reproduce the calculation or see precisely why reproduction is unavailable.

Policy changes that affect operations. Retain previous document versions and represent publication time, effective time and supersession. A new minimum order quantity or delivery cutoff should trigger re-evaluation of affected pending plans. Approval becomes stale when the approved quantities, prices, constraints or source state change materially; stale approval cannot authorize a different action.

Uncertainty with consequences. Display forecast intervals and the operational consequences of different service targets. Separate uncertainty caused by demand variability, incomplete data and unverified supplier rules. Do not label an LLM's self-reported confidence as a calibrated probability. A model can remain a research candidate if it loses to a simpler baseline.

Constrained agent autonomy. Support observe, recommend, draft and execute modes with explicit limits. Read-only investigation may proceed within the user's business scope. Execution requires applicable authority, a current approval when policy demands it, passed constraints and available capacity. Enforce limits in backend services; an agent prompt is not an authorization boundary.

A useful modern interface. Deliver responsive workspaces, saved views, command search, keyboard navigation, light/dark/system themes, clear loading and failure states, accessible tables and source highlighting. A planner can resume a long-running investigation after refreshing or reconnecting. Theme preferences persist without losing filters or work.

Operational 3D. Use a selectable warehouse or location scene tied to actual SKU-location records and scenario results. Selecting an object must reveal the same figures as the table. Provide planned-versus-current views, legends, reduced motion and a full 2D alternative. Do not substitute decorative animation for quantitative evidence. Target WCAG 2.2 AA across ordinary workflows and assess accessibility with both automated and manual review. [B1]

Portfolio decisions. Extend from item-level recommendations to shared budgets, supplier minimums, pack sizes, storage capacity, transfers and approval limits. Multi-echelon planning requires validated location relationships, transfers and lead times. Unsupported constraints must be visible; the application must not silently assume the data exists.

Buyer-controlled operation. Include administration, access review, connector health, model history, tenant consumption limits, retention settings, incident diagnostics and export/offboarding. These functions belong in the product scope, alongside the AI and planning screens.

## Complete functional scope

The final application includes these modules: organization and identity administration; source and dataset management; operational inventory explorer; forecasting and model registry; supplier and policy knowledge; exception inbox; scenario and optimization workspace; conversational investigation; review and approval queue; execution/reconciliation center; 3D inventory view; audit and evidence export; performance and value reporting; deployment administration and operational support.

The product should accommodate multiple currencies, units, calendars and time zones. Preserve transaction currency and distinguish it from reporting currency. Conversions require an explicit rate, source and effective date. Pack/unit conversions must be auditable. Never combine unrelated inventory quantities or financial totals merely because their displayed labels match.

Feature completeness is demonstrated through connected workflows. A chart with hardcoded values, an agent progress animation without a durable run, or a button that only displays a success toast does not satisfy its module. Demonstration fixtures are acceptable for development only when visibly labelled and isolated from supplied data and measured evaluation results.

## P0  P1 and P2 engineering gates

These are cumulative release gates, not task-severity labels or permission to stop at a thin prototype. Track defect severity separately as critical, high, medium or low. All specified capabilities remain in the delivery backlog. A gate is passed by evidence, not by elapsed time or a polished demonstration. Data-dependent and customer-dependent work remains explicitly blocked until its prerequisites exist; it must not be marked complete through simulation.

### P0     Complete controlled product

Build the repository, repeatable local environment, data contracts, tenant boundaries, real-data qualification, baseline and trained ML/DL pipelines, inventory calculations, optimizer, policy retrieval, agent tools, evidence packets, approvals and a sandbox execution adapter. Deliver the full main workflow with a usable interface and functional 3D/2D views. Persist runs and audit events. Include cost limits, stop controls, recovery behavior, export and a deployment candidate.

Exit evidence: clean setup from documentation; real-data import report; reproducible model comparisons; held-out retrieval and action evaluation; tested authorization and tenant separation; reconciled sandbox transactions; failure demonstrations; source/licence register; supported-capabilities matrix. P0 proves an integrated controlled system, not operational ROI or enterprise production suitability.

### P1     Enterprise pilot readiness

Qualify a defined deployment for a named pilot scope. Complete enterprise identity integration, role mapping, buyer-approved data flow, tenant retention policy, production-like backups and restore, observability, integration contract tests and a real target-system sandbox connector. Introduce genuine operational records in read-only shadow mode before enabling delegated writes. Establish pilot objectives, measurement method, support ownership and an exit plan.

Exit evidence: accepted pilot charter, mapped and reconciled source data, identity lifecycle test, connector compatibility report, restore exercise, monitored load results, documented model limitations, no unresolved critical release defects, and trained users. A pilot should initially require explicit review for consequential writes. This is a deployment decision for the actual buyer environment, not a blanket "enterprise-ready" badge.

### P2     Qualified production scope

Complete the contracted deployment and integration coverage, lifecycle provisioning, organizational scale requirements, scoped action limits, tested disaster recovery, monitored service objectives, dependency management, incident response, support commitments and security verification. Validate multi-location and coupled planning at the agreed scale. Support change management, tenant export/deletion, rollback and continuity when an LLM or connector is unavailable.

Exit evidence: buyer acceptance against an agreed workload and capability matrix; independent review where required; passed operational rehearsals; supported infrastructure and staffing; documented service terms; rollback and offboarding tests; and observed production or controlled rollout evidence. Capabilities such as private networking, customer-managed keys, regional residency or multi-region recovery are qualified individually. Do not claim certifications, continuous availability or support coverage that has not been obtained and staffed.

## Measurable business and product acceptance register

Each item needs a test/evidence path, environment, result, date and accountable reviewer. "Zero" below means zero observed failures in the declared test suite, not a guarantee against all future failures.

| ID | Gate | Acceptance evidence |
| --- | --- | --- |
| BUS-001 | P0 | Every imported dataset has owner, source, rights status, schema version, hash, time coverage and original-versus-derived classification; unknown rights block external redistribution. |
| BUS-002 | P0 | Reconciliation accounts for 100% of input rows as accepted, transformed or quarantined; sample monetary and quantity totals reconcile within explicitly documented rounding tolerances. |
| BUS-003 | P0 | A capability report identifies missing stock, supplier, price, calendar and policy fields; missing fields disable affected operational claims rather than create invented defaults. |
| BUS-004 | P0 | Each released model has training/validation/test cutoffs, code and data versions, baseline comparisons and limitations; the selected operational model is justified by recorded evaluation. |
| BUS-005 | P0 | Every proposed external action carries an immutable evidence-packet ID, exact payload, business scope, source version, forecast version and constraint result. |
| BUS-006 | P0 | Invalid quantities, exceeded budgets, missing authority and stale approvals are rejected in 100% of their release scenarios; no rejected action reaches the adapter. |
| BUS-007 | P0 | Duplicate submissions and timeout-after-success tests create exactly one external sandbox order per business idempotency key; unresolved outcomes remain pending. |
| BUS-008 | P0 | Refresh, worker restart and network interruption preserve run state and user work in tested scenarios; recovery neither loses approved work nor duplicates actions. |
| BUS-009 | P0 | All selected 3D objects, table rows and detail views agree on identifiers, units, quantities and scenario version; every core task has a keyboard-accessible 2D route. |
| BUS-010 | P0 | Light/dark/system themes persist across reloads; critical contrast, focus, error and motion checks pass for the documented supported browsers and viewport sizes. |
| BUS-011 | P1 | Unauthorized cross-tenant and cross-business-unit access produces zero data disclosure in API, search, export, background-job and document-retrieval tests. |
| BUS-012 | P1 | Corporate sign-in, role changes and deactivation pass a recorded lifecycle test; deactivated users cannot start new actions after the configured revocation interval. |
| BUS-013 | P1 | The connector proves create/read/reconcile, pagination, rate-limit recovery, schema drift detection and version compatibility in the buyer's sandbox. |
| BUS-014 | P1 | A restore rehearsal recovers database, documents, model metadata and required keys within the agreed recovery objectives; restored records reconcile with the selected recovery point. |
| BUS-015 | P1 | On an agreed reference workload, publish p50/p95/p99 latency, batch completion time, failure rate, resource usage and cost; approve capacity only for that measured workload. |
| BUS-016 | P1 | At least five representative end-to-end user tasks are observed with business users; record completion, time, errors and unresolved usability issues against the current process. |
| BUS-017 | P1 | The pilot scorecard fixes baseline windows, business segments, service constraints and success criteria before outcomes are inspected. |
| BUS-018 | P1 | Alerts for stale data, failed reconciliation, exhausted budgets and unavailable models are triggered in rehearsals and reach the designated operational queue. |
| BUS-019 | P2 | Every production permission maps to an owner-approved role/action matrix; separation of preparation, approval and execution is verified for designated high-impact actions. |
| BUS-020 | P2 | Deployment rollback, connector outage, LLM outage and failed migration rehearsals complete without unaccounted orders or silent loss of audit evidence. |
| BUS-021 | P2 | Security verification records applicable versioned requirements, evidence and findings; no unresolved critical or unmitigated high-severity release finding remains. |
| BUS-022 | P2 | Provisioning, transfer and deprovisioning work for the contracted identity integration; role changes propagate to retrieval and execution, not merely navigation menus. |
| BUS-023 | P2 | Tenant export and deletion exercises include operational records, documents, vectors, caches and documented backup-retention treatment; export counts reconcile. |
| BUS-024 | P2 | Contracted service objectives, support hours, escalation ownership and incident communication routes are staffed and exercised; observed service reports distinguish commitments from results. |
| BUS-025 | P2 | Pricing and unit economics use measured ingestion, storage, inference, compute, integration and support consumption; forecasts state their volume and utilization assumptions. |
| BUS-026 | P2 | Customer-facing materials label each claim as tested capability, simulated estimate, pilot observation or production observation and link to supporting evidence. |

## Integration delivery contract

Use a canonical operational model behind versioned adapters. Start with file import and a sandbox adapter; implement one genuine ERP connector completely before advertising broad compatibility. The supported-systems matrix must name product, deployment type, API version, tested operations, authentication method, rate limits, custom-field support and known exclusions.

Microsoft documents purchase-order create/update operations and a separate receive-and-invoice action in Business Central. Treat these as materially different authorities. A procurement-planning authorization does not imply authority to post receipts or invoices. [B2] For SAP, qualify the buyer's exact S/4HANA edition, release and enabled purchase-order service against the current documentation. Record deprecated endpoints and the supported replacement before implementing an adapter. [B3]

Define source-of-truth ownership for orders, inventory, supplier masters and approvals. Reconcile external changes and partial receipts. Handle cancelled lines, split deliveries, unit conversions, backdated updates and source corrections. Keep connector credentials out of prompts and documents. Webhooks need authentication, replay protection and deduplication; polling needs checkpoints and backfill. Use optimistic concurrency or equivalent source-version checks before writes.

The integration handover includes mapping tables, fixture cases, sandbox evidence, credential-rotation instructions, recovery procedure and ownership. Production integration is incomplete until operations staff can distinguish a failed request from an uncertain outcome and reconcile it without creating another order. Before live side effects, verify the target environment, authorized operation, credentials, delegated limits, applicable approval and recovery procedure. Reuse valid existing authorization; do not ask for approval at every phase. A project launch instruction does not itself grant corporate spending authority.

## Deployment and support model

Ship one well-supported deployment model first, with repeatable infrastructure configuration and separate development, staging and production environments. Record whether the qualified installation is vendor-hosted, isolated for a buyer, or buyer-managed. Do not equate containerization with private-cloud readiness. Validate networking, identity, encryption, backups, secrets, region, logging and operational ownership in the selected environment.

OIDC provides an interoperable authentication layer; it does not by itself provide user provisioning or business authorization. SCIM addresses identity provisioning and management. Design both responsibilities explicitly and support SAML when the contracted identity integration requires it. [B4, B5]

Set recovery point and recovery time objectives from the business impact of losing records or interrupting planning. Test restoration with realistic dependencies, including keys and document stores. NIST's contingency-planning guidance provides a useful structure for relating business impact to recovery priorities. [B6]

Monitor API availability, data freshness, queue age, reconciliation failures, forecast drift, document age, authorization failures and tenant cost. An unavailable LLM should leave inventory views, existing evidence and deterministic planning usable where possible. Define how time-sensitive exceptions route to people.

Support materials include installation, upgrade, rollback, backup/restore, identity setup, connector recovery, data correction, incident response and user training. Offer only support hours that an actual team can cover. Twenty-four-hour service requires an on-call arrangement and escalation capacity; it is not a checkbox in the interface.

## Commercial packaging and rights

Prepare an evaluation package containing product scope, architecture, data-flow diagram, deployment choices, integration matrix, security-response workbook, subprocessors, model/data cards, licence inventory, pilot scorecard and sample evidence packet. NIST AI RMF can organize AI risk-management work; it is voluntary guidance, and the current site notes ongoing revision. Refer to versioned practices and evidence, without representing alignment as certification. [B7]

Maintain separate rights records for customer data, third-party datasets, source code, model weights, hosted model services, embeddings, documents and 3D assets. Public availability does not establish commercial redistribution rights. The user's supplied dataset is not automatically authorized for external model-provider upload; record the allowed processing locations and providers. Customer records should not train shared models without explicit contractual permission and an implemented data-separation policy.

Use a pricing hypothesis that a buyer can evaluate: a platform subscription tied to a declared planning volume, a separate implementation/integration scope, and clear support/deployment options. Measure SKU-location series, active locations, ingestion volume, storage, forecast refreshes and agent consumption before selecting tiers. Include budgets, usage visibility and predictable handling of overages. Do not invent a market price or imply that a token markup establishes sustainable margins.

Use OWASP ASVS as a versioned source of applicable application-security requirements and verification evidence. Its current project page identifies 5.0.0 as stable. Security review is scoped evidence, not a certification badge or proof that vulnerabilities can never exist. [B8]

## Business value and ROI measurement

Keep three evidence classes separate: retrospective forecast results, simulated operational outcomes and observed customer outcomes. A replay study can estimate replenishment effects under stated costs and demand assumptions. It cannot establish cash savings realized by a company that never used the recommendations.

Build a value ledger with source, unit, period, baseline, intervention, assumptions and evidence for each benefit or cost. Candidate benefits are reduced planner handling time, lower excess inventory carrying cost, fewer stockout-related contribution losses, reduced expediting and fewer policy errors. Candidate costs are implementation, integration, compute, model inference, storage, support, training, supervision and exception handling.

Use formulas transparently:

- Period net benefit = attributable operating benefit minus incremental operating cost.
- ROI = (attributable benefit minus total incremental cost) divided by total incremental cost, for the same stated period.
- Inventory carrying-cost benefit = attributable reduction in average inventory value multiplied by the applicable carrying-cost rate and period fraction.
- Labour benefit = verified time reduction multiplied by a justified loaded hourly cost; report whether it represents redeployed capacity or an actual expense reduction.
Do not double-count inventory cash release as recurring profit, or use recovered revenue as recovered margin. Do not count avoided stockouts and recovered sales separately when they represent the same benefit. Show low/base/high assumptions and sensitivity to service targets, supplier delays, carrying costs and model costs.

For a pilot, fix the comparison before measurement. Prefer a staged rollout or comparable product/location groups where practical; report seasonality, promotions, assortment changes and other confounders. Finance reviews definitions and reconciliation. Success requires acceptable service and policy outcomes alongside cost improvement; reducing stock by failing to serve customers is not success.

## Pilot and production evidence

A pilot charter names business scope, users, data owners, integration owner, support contacts, duration, authority limits, baseline, service constraints and exit criteria. Begin in shadow mode: recommendations are compared with actual planner decisions, with reasons captured. Move to reviewed drafts and then bounded execution only after applicable tests and owner authorization.

Maintain an evidence register throughout the pilot. Include data defects, model misses, policy retrieval errors, rejected plans, overrides, uncertain external outcomes, customer-reported issues and cost. A narrow successful demonstration is useful but does not substitute for representative coverage. Preserve negative results and explain corrective changes.

Production qualification adds sustained observation at the contracted load, recovery evidence, integration ownership, support capacity, security findings closure, release/change policy and customer acceptance. Independent security or assurance work may be required by a buyer and must be commissioned and completed before it is claimed. The application may become a production candidate within the project period; adoption, procurement and certification timelines remain separate from software development.

## Execution backlog and delivery phases

Create traceable epics: ORG identity and tenant boundaries; DATA qualification and pipelines; FCST model training; PLAN optimization; KNOW policy knowledge; AGENT investigation; ACT approval/execution; UX interface and 3D; INT integrations; OPS deployment/reliability; VALUE measurement and commercial evidence. Every backlog item names dependencies, acceptance IDs, an evidence artifact and a completion state: planned, active, implemented, verified or blocked.

Phase 1 establishes repository structure, executable setup, requirements and supplied-data qualification. Phase 2 delivers baselines and trained models with reproducible evaluation. Phase 3 completes inventory, scenario and optimization services. Phase 4 implements document versioning, retrieval evaluation and policy extraction. Phase 5 joins agents, approvals and reconciled sandbox actions into the complete interface. These phases satisfy P0 only when the connected workflow passes its evidence requirements.

Phase 6 adds real connector qualification, enterprise identity, staging operations, restore and load evidence. Phase 7 conducts the controlled pilot and fixes representative failures. These satisfy P1 for the declared environment. Phase 8 finishes contracted production coverage, operational rehearsals, support materials and commercial evidence. Phase 9 is replication, rollout support and residual correction. Maintain documentation and tests alongside each phase rather than postponing them until the interface is finished.

Use the seven-to-nine-month research plan as a scheduling hypothesis. Re-estimate after dataset qualification and the first vertical workflow. A solo developer can build substantial capability, but customer system access, specialist review and staffed operations are external dependencies. Never silently replace an unmet enterprise requirement with a mock or mark a feature verified because its code compiles.

Maintain the canonical handoff files: PROJECT_STATUS.md records the verified release gate, current state and next action; TASKS.md tracks epics, dependencies, severity and acceptance IDs; DECISIONS.md preserves choices, assumptions and authorization scope; EVIDENCE_INDEX.md links each requirement to reproducible commands, artifacts, environment and measured results. Update these files at every work-session handoff. Continue authorized implementation around blocked credentials or unavailable customer inputs. Ask only for a concrete missing decision or permission that truly prevents that action; ordinary reversible engineering work should continue.

## Source register

[B1] W3C, Web Content Accessibility Guidelines 2.2, current Recommendation dated 12 December 2024; checked 20 October 2026. www.w3.org source Supports accessibility target and manual/automated verification context, not a product conformance claim.

[B2] Microsoft Learn, purchaseOrder resource type, updated 21 August 2026; checked 20 October 2026. learn.microsoft.com source Supports distinct create/update and receiveAndInvoice operations.

[B3] SAP Help, Purchase Order API documentation and version-specific migration guidance. help.sap.com source V4 reference: help.sap.com source Qualify the buyer-specific service and API version before implementation.

[B4] OpenID Foundation, OpenID Connect Core 1.0 incorporating errata set 2; checked 20 October 2026. openid.net source

[B5] RFC Editor, RFC 7644, System for Cross-domain Identity Management: Protocol. www.rfc-editor.org source Schema: www.rfc-editor.org source

[B6] NIST SP 800-34 Revision 1, Contingency Planning Guide for Federal Information Systems. csrc.nist.gov source Proposed recovery practices are product requirements, not a claim of government approval.

[B7] NIST AI Risk Management Framework resources, checked 20 October 2026. airc.nist.gov source; www.nist.gov source Voluntary guidance; site notes revision in progress.

[B8] OWASP ASVS project, checked 20 October 2026, stable version listed as 5.0.0. owasp.org source Supports versioned verification requirements, not product certification.
