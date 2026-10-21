# 2 Architecture and agent execution

## Purpose and delivery standard

Build SupplyLens as a working decision-support product for demand planning, inventory exceptions, and procurement review. The release must connect user-supplied data, independently trained forecasting models, evidence retrieval, constrained planning, and a reviewable action workflow. A multinational-company pilot is the intended application context; it is not a claim of certified security, validated savings, global-scale capacity, or completed enterprise integration. Maintain a readiness register distinguishing IMPLEMENTED, VERIFIED_LOCALLY, VERIFIED_IN_SANDBOX, VERIFIED_LIVE_READ_ONLY, BLOCKED_CONFIGURATION, and NOT_IMPLEMENTED. Evidence must accompany every readiness claim.

Proceed autonomously with routine local scaffolding, migrations against development databases, data profiling, reversible edits, training within already authorized resources, tests, and fixes. Do not repeatedly request approval for these activities. External mutations, contacting suppliers, creating live purchase orders, deploying publicly, or spending outside an authorized budget require a concrete, scoped authorization. Prepare the exact proposed action and evidence first. Missing credentials must not stop the unaffected local product work.

Organize delivery as P0 (complete product in a controlled environment), P1 (enterprise pilot readiness), and P2 (qualified production readiness). These are evidence gates, not mandatory human-approval checkpoints. Continue all authorized work across phases. Keep PROJECT_STATUS.md, TASKS.md, DECISIONS.md, and EVIDENCE_INDEX.md current with completed capabilities, next executable work, verification paths, and specific blockers. Do not claim a later readiness level merely because all screens render.

## One coherent implementation stack

Use one repository containing a Next.js App Router frontend in strict TypeScript; a FastAPI application using Pydantic contracts, SQLAlchemy, Alembic, and psycopg; Python ML/DL modules; LangGraph orchestration; Google OR-Tools CP-SAT planning; and a separately running Python worker. PostgreSQL with pgvector is the sole application database. Use PostgreSQL full-text search alongside vector similarity. Start with the supported stable PostgreSQL release verified during bootstrap; do not select a release candidate merely because it is newer. Pin resolved package versions and container digests after a compatibility smoke test, retaining lockfiles and a dependency manifest. [A1-A6]

Use the repository responsibility map in the Execution and acceptance chapter. Ingestion belongs with the API/worker domain services; feature preparation and training belong under ml/; experiment runners belong under evaluations/. The API and worker import the same domain services, validation, tools, and authorization functions. They are separate processes so expensive work does not block requests, not separate product microservices. Keep scheduling, job leases, outbox records, model metadata, and agent checkpoints in PostgreSQL. Do not introduce Redis, Kafka, an additional vector database, Neo4j, Kubernetes, or a hosted model registry without a measured requirement and an architecture decision record.

Use a storage interface for raw files, reports, and model artifacts: a content-addressed, tenant-scoped local volume in development; the pilot's approved object store when configured. Store metadata and hashes in PostgreSQL. Do not place multi-gigabyte artifacts in normal database rows. Docker Compose should start web, API, worker, and PostgreSQL, with a migration job and explicit health checks. An optional GPU worker uses the same task protocol and codebase.

## Canonical business data and provenance

Before implementing business calculations, inspect the supplied folder and produce a machine-readable data inventory. Preserve original files. Record dataset ID, tenant, source system, file hash, extraction timestamp, license/use status, schema version, row count, quality issues, and mapping decisions. Column mapping may be AI-assisted, but ingestion must execute deterministic, versioned transformations. Quarantine ambiguous units, invalid dates, orphan IDs, and incompatible currencies. Do not invent supplier relationships, costs, stock positions, or company joins to make a screen look complete.

Define typed canonical entities: tenant; user membership; business unit; location; SKU; SKU-location; supplier; supplier-SKU offer; sales/order line; return/cancellation; inventory snapshot; inventory movement; purchase order and line; shipment/receipt event; commercial policy; document/version/chunk; dataset version; feature snapshot; model version; forecast run; scenario; recommendation; approval; agent run; tool execution; integration binding; and outbox event. Distinguish missing values from zero and observed quantities from imputed quantities.

Every business row requires tenant_id, immutable internal ID, schema_version, created_at, updated_at, source_record_id where available, ingestion_batch_id, and a row version. Use tenant-scoped natural-key uniqueness and composite tenant/entity foreign keys. External identifiers are qualified by source system. Avoid global uniqueness on customer-provided IDs that could expose another tenant's existence.

Represent quantities with decimal precision and explicit unit-of-measure codes. Store pack size and unit conversions with effective dates and provenance; prohibit converting weight to units without an approved SKU-specific mapping. Store monetary amount, ISO currency, and tax/freight treatment separately. Use decimal arithmetic, explicit rounding, and a dated exchange-rate source for conversions. Preserve original and converted amounts; never silently add different currencies.

Store event time and ingestion time separately in UTC, plus the business timezone and reporting calendar. Define business-date boundaries, fiscal periods, lead-time units, and snapshot cutoffs. Inventory availability requires a reconciled snapshot plus subsequent movements; sales history alone cannot establish on-hand stock. Corrections are versioned adjustments linked to the original event. Deduplicate source events with stable business keys; record late arrivals and recompute only affected downstream versions.

## Typed APIs and durable user interactions

Use versioned REST endpoints under /api/v1 and a generated OpenAPI TypeScript client. Pydantic request/response models are the source of truth for transport contracts. Separate persistence models from public response DTOs. Validate enums, amounts, units, time ranges, IDs, pagination, and allowed transitions on the server. Never trust a browser-supplied tenant or role without checking current authenticated membership.

Provide endpoints for import profiling/commit, data quality, inventory exceptions, forecast creation/results, scenario simulation, evidence search, agent runs/events, approval decisions, integration configuration/status, and exports. Long-running requests return HTTP 202 with job_id, run_id, status URL, and trace_id. Stream persisted progress through server-sent events with monotonic event IDs and reconnect cursors. The browser may reconnect without starting a duplicate job. Closing the browser does not cancel accepted work.

Use explicit statuses: QUEUED, RUNNING, WAITING_FOR_APPROVAL, SUCCEEDED, PARTIAL, FAILED, CANCELLED, and UNKNOWN_OUTCOME. Include timestamps, retryability, machine-readable error codes, and actionable messages. Do not convert an empty dataset, unavailable model, or disconnected integration into a successful empty response. Progress percentages must derive from completed work units; otherwise show the current stage.

Require an Idempotency-Key on mutation requests and an expected version or If-Match precondition for edited scenarios, recommendations, and approvals. Bind the key to tenant, route, operation, and canonical request hash. A repeated identical request returns the existing result; a reused key with different content returns a conflict. Use cursor pagination with stable ordering. Restrict export scope and enforce the same permissions as the corresponding interactive view.

## Trained models as accountable product components

Expose forecast models through a shared ForecastService, never through arbitrary LLM-generated Python. The service validates forecast origin, horizon, SKU-location set, features available at the origin, model version, and required data coverage. Its output includes predicted quantity, unit, time bucket, uncertainty interval or calibrated quantiles where supported, model/data versions, training cutoff, and quality flags. Clearly distinguish sales forecasts from unconstrained demand estimates when stockouts or lost sales are unobserved.

Use a compact quantile temporal convolutional network (TCN) as the default trained DL candidate, with seasonal-naive and tree-based forecasting comparisons under the separately defined evaluation plan. Keep architecture, receptive field, loss, quantiles, and training configuration explicit. The serving interface must allow the objectively stronger validated candidate to remain the champion.

Retain reproducible training code, seeds, feature definitions, split manifests, evaluation outputs, and artifact hashes. Register models in PostgreSQL as TRAINING, EVALUATED, CANDIDATE, CHAMPION, RETIRED, or FAILED. Model promotion must depend on the frozen evaluation procedure and approved use scope; a neural model need not replace a better baseline. Record performance by relevant product/location segments, cold-start behavior, uncertainty, latency, and failure cases. Avoid a misleading overall score that hides badly performing segments.

Serving loads only trusted artifacts produced by the controlled training pipeline, verifies hashes, and checks feature-schema compatibility. Do not deserialize arbitrary uploaded model files. Give each forecast an immutable ID; revised data or models create new forecast runs rather than rewriting history. Retraining is a durable, resource-budgeted job. Drift alerts recommend investigation and can queue authorized evaluation; they do not silently promote a model or change procurement behavior.

## Deterministic constrained planning

Implement procurement/inventory planning in OR-Tools CP-SAT with explicit, versioned inputs. Define objective components such as purchase cost, holding cost, shortage penalty, and expedite cost only when their data or scenario assumptions are available. Distinguish measured inputs, estimated parameters, and user-entered assumptions in both the API and UI. CP-SAT uses integer constraints and exposes distinct solution statuses; scale money and quantities explicitly, validate rounding, and prevent integer overflow. [A5]

Constraints may include available budget, supplier eligibility, minimum order quantity, pack multiples, lead times, warehouse capacity, existing commitments, and maximum exposure. Distinguish hard constraints from soft targets with recorded penalty weights. Missing capacity is not unlimited capacity unless that is an explicit scenario assumption. The optimizer returns status, objective breakdown, input hash, parameter version, run limit, and bound/gap when available. Report FEASIBLE as feasible, not proven optimal; explain infeasibility without inventing a plan.

The LLM may translate a request into a validated scenario draft and explain computed results. It may not alter constraints, invent costs, directly calculate final purchase quantities, or bypass solver validation. Recheck all proposed lines with a separate deterministic validator. Record solver version, seed, worker count, and tie-break rules. Use one solver worker and deterministic limits for reproducibility tests; do not promise identical time-limited solutions across hardware. Simulated savings remain labeled simulation results until a defined real-world pilot establishes otherwise.

## Advanced RAG with permission and time boundaries

Ingest documents asynchronously with content hashes, original filename, source URL where applicable, source entity, language, document type, owner, ACL, classification, valid_from/valid_to, published_at, observed_at, supersedes_version_id, parser version, and embedding version. Retain page/section/table coordinates and extraction-quality flags. Store text and table structure; use a vision/OCR adapter only when necessary and authorized. Treat scanned or unreadable pages as incomplete evidence, not blank facts.

Retrieve through PostgreSQL lexical search and pgvector, merge candidates with reciprocal-rank fusion, and apply a tested reranker. Enforce tenant, document ACL, business scope, effective-date, and knowledge-cutoff conditions inside candidate queries and again before supplying evidence to a model. Historical questions must not use documents that became known later. Distinguish current-policy and as-of modes. Only the isolated read-only R2 research profile may vary effective-date selection over the same authorized documents known at the origin; it disables external adapters and keeps tenant ACLs and historical knowledge cutoffs mandatory. The operational product always uses the full temporal rules. Resolve conflicting versions explicitly, and expose the source dates used.

Describe PostgreSQL full-text ranking as lexical or keyword retrieval. Do not label it BM25 unless an actual BM25 implementation is added, tested, and documented.

Begin with exact vector search for small filtered corpora. Approximate pgvector searches apply filters after index scanning, so restrictive filters can reduce returned candidates. If HNSW is justified, benchmark recall against exact search under tenant/ACL filters; use iterative scans and, when measured isolation/scale requirements warrant them, tenant partitioning. Permissions remain enforced even when recall is poor. Never broaden ACLs to fill a result list. [A3]

Answers return structured claims, citations containing immutable document/version/page IDs, evidence excerpts, calculation references, and unresolved questions. Verify that a cited source supports the adjacent claim and is still accessible to the user. Express uncertainty through evidence coverage and calibrated model outputs; do not display invented "confidence" percentages. Retrieval failure returns a useful abstention or a precise request for missing evidence. Cache keys include tenant, permission revision, corpus/index version, as-of time, query, and model settings; permission changes invalidate cached access.

## Stateful agent  plan  check  approve  execute  verify

Implement one LangGraph controller with typed tools for authorized retrieval, structured analytics, forecast lookup, scenario optimization, policy validation, draft creation, action preparation, and verification. Keep tool arguments constrained to validated business objects. Persist graph checkpoints in PostgreSQL and authorize every thread lookup; an unguessable thread ID alone is not access control. LangGraph distinguishes thread checkpoints from longer-term stores, and in-memory checkpoints do not survive restart. [A4]

Use this explicit flow: ACCEPT  to  PLAN  to  GATHER_EVIDENCE  to  COMPUTE  to  CHECK  to  PREPARE_ACTION  to  WAIT_FOR_APPROVAL, when required  to  COMMIT_OUTBOX  to  EXECUTE  to  VERIFY  to  COMPLETE. Allow bounded loops from CHECK to GATHER_EVIDENCE or COMPUTE. Terminal outcomes include FAILED, CANCELLED, STALE_PLAN, and UNKNOWN_OUTCOME. Persist input/data/model/policy versions, plan steps, tool results, remaining budget, approval binding, and execution IDs. Store concise decision summaries and observable tool events rather than exposing hidden reasoning.

Authorize every tool call server-side against the current actor, tenant, role, scope, and run mode. Read-only analysis, local drafts, and permitted simulations can proceed automatically. External writes require a previously granted execution policy covering that operation or explicit action approval. Approval records must bind the immutable action hash, affected tenant/environment, integration, destination, line quantities/units, currency, maximum spend, authorizer, expiry, and relevant versions. Significant edits or changed business state invalidate approval and require a refreshed action preview.

Before committing an action, recheck current permissions, stock/commitment versions, supplier eligibility, budget, policy versions, approval expiry, and integration readiness. Use database constraints and transaction isolation/locking appropriate to the invariant. A screenshot or natural-language "approved" message is insufficient without a validated approval record. Restrict self-approval where the pilot's procurement policy requires separation of duties.

Bound runs by maximum tool calls, elapsed time, model tokens, retries, and spend. Defaults should be conservative and visible in configuration. Stop and preserve a recoverable result when a limit is reached. A failed verifier cannot be overruled by persuasive model prose. The visible result must distinguish prepared, approved, submitted, confirmed, and reconciled actions.

## Durable worker  outbox  idempotency  and reconciliation

Create jobs transactionally with the business request. Workers claim ready jobs using short PostgreSQL transactions and FOR UPDATE SKIP LOCKED, with ordered eligibility, a lease, heartbeat, attempt counter, fencing token, and retry schedule. PostgreSQL documents SKIP LOCKED as suitable for queue-like consumption, not a general consistent business-data snapshot. Keep external calls outside long database transactions. A sweeper recovers expired leases; updates require the current fencing token. [A2]

The dispatcher enumerates only tenants assigned to its service principal through narrowly scoped control-plane metadata, then claims jobs inside that tenant's RLS context. Job payloads preserve the originating actor and execution scope; reauthorize them on resume. Do not give the worker unrestricted database-owner credentials merely to simplify queue discovery.

Persist each side-effect intent in an outbox in the same transaction that records the approved action. Assign a stable operation ID, payload hash, tenant/integration scope, and external idempotency key where supported. Dispatchers may deliver more than once. Require idempotent local consumers and adapter-specific duplicate protection. Do not claim universal exactly-once execution across PostgreSQL and an external ERP.

If a remote write times out after submission, record UNKNOWN_OUTCOME and reconcile by operation ID, idempotency key, or external reference. Do not blindly replay a non-idempotent purchase order creation. Query the external system, inspect its recorded state, and link the confirmed object before resuming. If the provider cannot disambiguate the result, require manual reconciliation with the evidence preserved. Compensation is a new authorized business action, not a fictional rollback of an external transaction.

Use capped exponential backoff with jitter for retryable failures, permanent-failure classification, and a dead-letter review queue. Cancellation is cooperative; check it before each expensive task and before dispatch. A cancellation request after a remote side effect requires reconciliation. A worker restart, duplicate webhook, expired lease, or browser refresh must not produce a second purchase order in supported idempotent scenarios. Durable work must not depend on a FastAPI in-process background callback. [A6]

## Identity  tenancy  RBAC  and data protection

For a configured enterprise pilot, use OIDC authorization-code flow with PKCE through a maintained identity library and the organization's provider, such as Microsoft Entra ID. Keep browser sessions in secure, HttpOnly cookies; keep access/refresh tokens server-side. The Next.js server proxies API requests with an access token issued for the FastAPI resource. FastAPI validates signature, issuer, audience, expiry, and required scopes using trusted provider metadata and key rotation. Do not accept an ID token as an API access token. Microsoft identifies the resource through the access token's audience claim. [A7]

Define Viewer, Planner, Approver, Tenant Administrator, and integration-service roles with an explicit operation matrix. Tenant administration does not automatically authorize procurement spend. Resolve active memberships from server-controlled records. Recheck permission at execution time, not only when a job was submitted. Protect sessions, approval endpoints, and mutations against CSRF, enforce exact CORS origins, and rate-limit costly endpoints per tenant and actor.

Enable and force PostgreSQL RLS on tenant-owned tables, including documents, chunks, jobs, approvals, and execution records. Use a non-owner application role without BYPASSRLS; keep migrations and backups under separate restricted credentials. Set validated tenant context transaction-locally and reset pooled connection state. Provide USING and WITH CHECK policies, fail closed when context is absent, and test direct database access as the actual runtime role. PostgreSQL owners and BYPASSRLS roles can bypass ordinary RLS, so table flags alone are insufficient. [A1]

Protect graph checkpoints through a tenant-aware persistence wrapper and verified thread ownership; harden generated checkpoint tables or their access path explicitly rather than assuming framework defaults provide tenant isolation. Scope object storage, signed download links, logs, caches, exports, and background jobs consistently. Keep secrets out of repositories, frontend bundles, prompts, model inputs, telemetry, and exception bodies. Use environment/secret-manager references with rotation support.

Treat retrieved documents and tool output as untrusted data. They cannot change system rules, grant permissions, request secrets, or introduce tools. Disable arbitrary shell/Python execution and unrestricted SQL in the deployed agent. Use allowlisted structured tools, parameterized queries, bounded result sizes, upload type/size/decompression limits, and parser isolation. An HTTP connector must restrict destinations and defend against private-network/metadata-address access and redirect abuse. Document retention, deletion, model-provider data handling, and audit access before enabling a real-data pilot.

## Integration adapters and honest operating modes

Define a typed adapter contract: capabilities(), health(), validate_credentials(), fetch_changes(cursor), preview_action(), execute(operation_id, payload), lookup_operation(), and reconcile(). Each adapter declares supported entities, pagination, rate limits, permissions, webhook validation, idempotency behavior, and failure semantics. Persist external/internal identifier mappings and incremental-sync cursors. Verify webhook signatures and reject stale/replayed events. Separate read credentials from write permissions where supported.

Ship a file adapter and deterministic sandbox business-system adapter first. Implement an actual ERP connector only against its official documented API and available credentials. A branded button or stub is not an integration. Display DISABLED, NOT_CONFIGURED, CONFIGURED_UNVERIFIED, VERIFIED_READ_ONLY, LIVE_WRITE_AUTHORIZED, DEGRADED, or UNKNOWN_OUTCOME with the last successful check and supported capabilities. Never fabricate live health, completed orders, supplier responses, or synchronized records.

Separate execution mode from data provenance. Offline mode uses supplied local data and verified available local models; if model weights are unavailable, disclose that limitation and retain deterministic analytics. Sandbox mode permits reversible test actions against a simulator or provider sandbox. Live read-only mode permits authorized real-system ingestion. Live write mode requires scoped authorization, permissions, tested reconciliation, and configured limits. Use separate provenance fields: source_kind records user-supplied, public or generated origin; value_kind records observed, derived, forecast, assumed or simulated values. Imported is an ingestion state, not a guarantee that a value was observed. The UI uses the corresponding provenance labels consistently. Synthetic fixtures may test code but may not count as evidence of real business savings or model accuracy.

## Observability and operational evidence

Instrument HTTP requests, worker jobs, retrieval, model calls, optimizer runs, and adapters with correlated OpenTelemetry traces. Record structured logs and metrics with request_id, run_id, job_id, operation_id, model/data/policy versions, timing, status, and redacted error category. Restrict tenant identifiers and sensitive payloads; avoid high-cardinality or confidential metrics labels. OpenTelemetry's traces, metrics, and logs support investigation; observability must not become a second uncontrolled copy of customer data. [A8]

Track queue age, lease expiry, retry count, dead-letter count, UNKNOWN_OUTCOME age, sync freshness, forecast drift, retrieval coverage, approval waiting time, model tokens/cost, latency, and verified task success. Build an operator view with retry/reconcile controls gated by role. Set retention and export policies for audit records; append-only application permissions do not imply cryptographic immutability. Record who changed configuration, promoted models, granted approvals, and executed actions.

Document database and artifact backup/restore, migration rollback strategy, dependency updates, incident triage, and a release rollback. Test restoration into an isolated environment and verify artifact hashes and a representative business workflow. Rebuildable embeddings are not a substitute for backing up source documents and approvals. Preserve completed verification evidence, benchmark hardware, software versions, test seeds, and known limitations in the release report.

## Measurable acceptance gates

All numerical values below are PROPOSED TARGETS, not measured achievements or contractual service levels. Record actual results and the exact test profile. A failed security/integrity gate blocks the affected live capability; a missed performance target requires an explicit limitation and remediation plan, never a fabricated pass.

ARC-01  -  A clean checkout starts web, API, worker, database, migrations, and health checks using the documented local command. No external service or paid API is silently required. Local smoke tests use explicitly labelled deterministic providers; the real LLM and embedding paths require available model weights or an authorized provider and separate verification. Restarting processes preserves accepted jobs and completed runs.

ARC-02  -  Generated TypeScript contracts match committed OpenAPI exactly in CI. Every documented operation has success and invalid-input coverage. Repeated idempotency keys return one operation; conflicting payload reuse is rejected. Concurrent stale updates are rejected in 100% of scripted cases.

ARC-03  -  Golden tests cover at least 30 unit, currency, timezone, return, duplicate-event, late-arrival, and missing-value boundary cases. All pass. Every forecast, plan, and evidence answer resolves to recorded source/data/model/policy versions.

SEC-01  -  Run at least 50 cross-tenant and cross-role denial cases covering APIs, direct RLS queries, vector retrieval, checkpoint access, downloads, exports, streams, and worker execution. Target: zero unauthorized rows, chunks, actions, or metadata disclosures. Revocation is effective on the next protected operation.

ARC-04  -  Evaluate on a frozen, independently checked set of at least 100 representative questions with explicit supporting evidence, including historical, missing-evidence, and conflicting-policy cases. Targets: Recall@10 at least 0.90 on answerable cases and citation-support precision at least 0.95; report per-category results, abstention behavior, denominators, and uncertainty. Permission-denial cases must pass completely.

ARC-05  -  All accepted optimizer outputs satisfy every hard constraint in an independent validator. Infeasible/unknown statuses are never presented as approved recommendations. Reproduction tests preserve inputs and solver settings; deterministic fixtures produce equivalent objective/constraint results.

AGT-01  -  At least 50 frozen business scenarios exercise retrieval, forecasting, optimization, missing data, stale approval, denied action, timeout, and recovery. Target: at least 90% verified task completion on supported scenarios, with zero unauthorized external mutations. Repeat stochastic runs at least three times and publish variation and cost.

AGT-02  -  Inject failure before dispatch, after remote acceptance, before local confirmation, during reconciliation, and after lease expiry, with duplicate deliveries. All scripted cases finish with one verified remote action where idempotency is supported, or an explicit unresolved state. No unknown write is blindly replayed.

ARC-06  -  Proposed lease target: 45 seconds with 10-second heartbeats; recover eligible abandoned work within 60 seconds after worker availability. Complete a backup/restore drill. For read-only pilot analytics, initial planning targets are RPO 24 hours and RTO 4 hours. Live-write order execution requires an operation-preserving recovery design, normally continuous database recovery plus reconciliation against the external system; a daily-backup analytics target is not sufficient to claim no lost orders. Agree and measure the appropriate recovery objectives for each capability.

ARC-07  -  On a declared reference profile of 8 vCPUs, 32 GiB RAM, 100,000 indexed chunks, one million transaction rows, and 20 concurrent interactive users, target p95 metadata reads below 500 ms and p95 retrieval below 2 seconds at 5 retrieval requests/second, excluding external generation. Record cold/warm conditions. Benchmark training, forecasting, optimization, and external-model latency separately; do not hide them in exclusions.

ARC-08  -  Lint, strict type checks, migrations, unit/property tests, real-PostgreSQL integration tests, dependency/secret checks, and Playwright critical journeys pass. Use real RLS/pgvector behavior rather than replacing database tests with mocks. Publish remaining defects and unverified integrations; no unresolved critical security or data-integrity defect may be accepted for a live pilot.

## Source register

[A1] PostgreSQL row-security documentation: default denial, owner/BYPASSRLS behavior, policy checks, and isolation caveats. www.postgresql.org source

[A2] PostgreSQL SELECT documentation: SKIP LOCKED and queue-like consumption. www.postgresql.org source

[A3] pgvector official repository: filtered approximate search, iterative scans, and tenant/index considerations. github.com source

[A4] LangGraph persistence documentation: checkpoints, stores, and persistent PostgreSQL checkpointers. docs.langchain.com source

[A5] Google OR-Tools CP-SAT documentation: integer constraints and explicit solver statuses. developers.google.com source

[A6] FastAPI background-task documentation: in-process background work and heavier worker alternatives. fastapi.tiangolo.com source

[A7] Microsoft Entra access-token documentation: resource ownership and audience. learn.microsoft.com source

[A8] OpenTelemetry observability primer: traces, metrics, and logs. opentelemetry.io source

[A9] Next.js TypeScript documentation. nextjs.org source
