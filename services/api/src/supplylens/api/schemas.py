"""Response models: the API contract the web client is generated from (packages/contracts/api.d.ts).

Models are tolerant on purpose: `extra="allow"` lets a new field reach clients without a contract change, and
genuinely dynamic payloads (evidence packets, planner output, study metrics) are `dict[str, Any]`. Everything the
interface reads is declared, so renaming or dropping a field fails the TypeScript build instead of the browser.
Fields with defaults are always present in responses (the OpenAPI output schema marks them required).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Out(BaseModel):
    model_config = ConfigDict(extra="allow", protected_namespaces=(), json_schema_serialization_defaults_required=True)


Json = dict[str, Any]


# ------------------------------------------------------------------------------------------ session
class DevUser(Out):
    email: str
    display_name: str
    roles: list[str]


class DevUsers(Out):
    dev_only: bool
    users: list[DevUser]
    notice: str


class UserInfo(Out):
    id: UUID
    email: str
    display_name: str
    is_dev_account: bool


class Membership(Out):
    slug: str
    name: str
    kind: str
    description: str
    role: str


class AuthConfig(Out):
    environment: str
    dev_login: bool
    oidc: bool
    oidc_login_url: str | None = None
    disposable: bool = False      # true only on declared disposable test stacks (the browser suite may reset data)


class Me(Out):
    user: UserInfo
    memberships: list[Membership]


class Ok(Out):
    ok: bool


# ------------------------------------------------------------------------------------------ overview / data
class OverviewSettings(Out):
    operational_as_of: datetime
    currency: str
    dataset_id: UUID | None = None
    planning: Json = {}
    assumption_set_id: UUID | None = None


class OverviewDataset(Out):
    id: UUID
    name: str
    license: str
    source_url: str | None = None
    sha256: str
    created_at: datetime
    totals: dict[str, float] | None = None
    date_span: list[str] | None = None


class AssumptionSetInfo(Out):
    name: str
    version: int
    rationale: str


class Capability(Out):
    capability: str
    status: str
    basis: str | None = None
    note: str


class Overview(Out):
    settings: OverviewSettings | None = None
    dataset: OverviewDataset | None = None
    counts: dict[str, int]
    actions_by_status: dict[str, int]
    assumption_set: AssumptionSetInfo | None = None
    capabilities: list[Capability]


class SheetReport(Out):
    input_rows: int
    accepted: int
    returned: int
    quarantined: int
    quarantine_reasons: dict[str, int] = {}


class DatasetReport(Out):
    totals: dict[str, float] = {}
    sheets: dict[str, SheetReport] = {}
    date_span: list[str] = []
    distinct_skus_accepted: int | None = None
    distinct_customers: int | None = None
    missing_customer_id_rows: int | None = None
    notes: list[str] = []
    doi: str | None = None


class Dataset(Out):
    id: UUID
    name: str
    source_kind: str
    license: str
    source_url: str | None = None
    file_name: str
    sha256: str
    bytes: int
    schema_version: str
    status: str
    created_at: datetime
    report: DatasetReport


class QuarantineSummary(Out):
    reason: str
    n: int


class QuarantineRow(Out):
    id: int
    source_sheet: str
    source_row: int
    reason: str
    raw: Json


class Quarantine(Out):
    summary: list[QuarantineSummary]
    rows: list[QuarantineRow]
    next_cursor: int | None = None


# ------------------------------------------------------------------------------------------ inventory
class InventoryItem(Out):
    sku_id: str
    description: str
    unit: str
    location_id: str
    zone_id: str
    as_of: date
    on_hand: int
    allocated: int
    on_order: int
    capacity: int | None = None
    value_kind: str
    available: int
    avg_daily: float | None = None
    days_of_cover: float | None = None
    health: str
    health_basis: str | None = None
    slot_id: str | None = None
    aisle: int | None = None
    rack: int | None = None
    x: float | None = None
    z: float | None = None
    is_schematic: bool | None = None
    term_count: int


class Inventory(Out):
    effective_date: date | None = None
    items: list[InventoryItem]
    # Paging (Phase 3): `total` items exist; this page starts at `offset`; `next_offset` is null on the last page.
    total: int | None = None
    offset: int = 0
    next_offset: int | None = None


class SalesPoint(Out):
    day: date
    units: int


class ProductInfo(Out):
    sku_id: str
    description: str
    unit: str
    first_sale: date | None = None
    last_sale: date | None = None
    source_kind: str


class ProductSales(Out):
    product: ProductInfo
    value_kind: str
    semantics: str
    daily: list[SalesPoint]
    returns: list[SalesPoint]


class Slot(Out):
    slot_id: str
    zone_id: str
    aisle: int
    rack: int
    x: float
    z: float
    sku_id: str | None = None


class Warehouse(Out):
    location: Json | None = None
    schematic: bool
    note: str
    slots: list[Slot]


# ------------------------------------------------------------------------------------------ terms / documents / evidence
class Term(Out):
    term_id: str
    supplier_id: str
    sku_id: str
    unit_cost_minor: int
    currency: str
    moq: int
    order_multiple: int
    lead_time_days: int
    document_version_id: str | None = None
    section: str | None = None
    value_kind: str
    valid_from: date
    valid_to: date | None = None
    known_at: datetime
    supersedes: str | None = None
    withheld: str | None = None


class IgnoredTerm(Out):
    term_id: str
    supplier_id: str
    sku_id: str
    reason: str


class Terms(Out):
    knowledge_cutoff: datetime
    effective_date: date
    applicable: list[Term]
    ignored: list[IgnoredTerm]
    conflicts: list[list[str]]
    history: list[Json]


class DocumentRow(Out):
    document_id: UUID
    title: str
    doc_type: str
    supplier_id: str | None = None
    source_kind: str
    version_id: UUID
    version_label: str
    file_name: str
    sha256: str
    known_at: datetime
    valid_from: date
    valid_to: date | None = None
    supersedes_version_id: UUID | None = None
    embed_model: str | None = None
    chunks: int


class ChunkInfo(Out):
    id: UUID
    ordinal: int
    section: str
    char_start: int
    char_end: int


class DocumentVersion(Out):
    id: UUID
    document_id: UUID
    version_label: str
    file_name: str
    sha256: str
    known_at: datetime
    valid_from: date
    valid_to: date | None = None
    supersedes_version_id: UUID | None = None
    parser_version: str
    embed_model: str | None = None
    ingested_at: datetime
    title: str
    supplier_id: str | None = None
    source_kind: str
    text: str
    chunks: list[ChunkInfo]
    untrusted_content: bool


class DocumentUploaded(Out):
    document_id: str
    version_id: str
    chunks: int
    embedded: bool
    known_at: datetime


class ClauseLabel(Out):
    category: str
    char_start: int
    char_end: int
    text: str
    source: str


class EvidenceResult(Out):
    chunk_id: str
    document_id: str
    version_id: str
    title: str
    version_label: str
    section: str
    excerpt: str
    char_start: int
    char_end: int
    valid_from: date
    valid_to: date | None = None
    known_at: datetime
    supplier_id: str | None = None
    source_kind: str
    sha256: str
    supersedes_version_id: str | None = None
    score: float
    signals: Json = {}


class Citation(Out):
    document_id: str
    version_id: str
    version_label: str
    section: str
    char_start: int
    char_end: int


class Claim(Out):
    text: str
    citation: Citation


class Answer(Out):
    type: str
    claims: list[Claim]
    abstained: bool
    message: str | None = None


class EvidenceSearch(Out):
    abstain: bool
    results: list[EvidenceResult]
    mode: str
    degraded: str | None = None
    filters: dict[str, str | None]
    reranker: str
    answer: Answer


# ------------------------------------------------------------------------------------------ forecasting / models / scenarios
class ForecastPoint(Out):
    sku_id: str
    day: date
    q10: float
    q50: float
    q90: float


class ForecastRun(Out):
    id: UUID
    model_version_id: UUID
    dataset_id: UUID
    origin: date
    horizon: int
    status: str
    sku_ids: list[str]
    quality_flags: dict[str, str] = {}
    created_by: UUID | None = None
    created_at: datetime
    family: str
    version: str
    label: str
    interval: str
    points: list[ForecastPoint]


class ModelVersion(Out):
    id: UUID
    family: str
    version: str
    status: str
    training_cutoff: date | None = None
    config: Json = {}
    metrics: Json = {}
    artifact_sha256: str | None = None
    code_version: str | None = None
    created_at: datetime


class ScenarioMetrics(Out):
    skus_assessed: int
    skus_not_assessed: int = 0
    skus_needing_order: int
    uncapped_units: int = 0
    capacity_capped_units: int = 0
    units_ordered: int
    spend_minor: int
    shortfall_units: int
    projected_q50_coverage: float | None = None
    metric_note: str


class PlanLine(Out):
    sku_id: str
    supplier_id: str
    term_id: str
    quantity: int
    unit_cost_minor: int
    line_minor: int
    currency: str
    arrival_date: date
    document_version_id: str | None = None
    section: str | None = None


class ChecksRef(Out):
    passed: bool
    issues: list[Json] = []
    warnings: list[Json] = []          # non-blocking findings the approver must see (e.g. a forced shortfall)
    lines_checked: int | None = None
    independent_validator: str | None = None


class SolverInfo(Out):
    name: str
    version: str
    num_workers: int
    random_seed: int
    max_time_s: float


class PlanRequestInfo(Out):
    budget_minor: int
    currency: str
    allow_shortfall: bool
    shortage_penalty_minor: int
    shortage_penalty_value_kind: str | None = None
    needs: list[Json] = []


class PlanOutput(Out):
    """Planner result (OR-Tools CP-SAT) as returned for scenarios; `status` is OPTIMAL, FEASIBLE, INFEASIBLE, ..."""
    status: str
    lines: list[PlanLine] = []
    total_minor: int = 0
    currency: str | None = None
    shortfall: dict[str, int] = {}
    explanation: list[str] = []
    violations: list[str] = []
    objective: Json = {}
    excluded_offers: list[Json] = []
    input_hash: str | None = None
    solver: SolverInfo | None = None
    arrival_warnings: list[Json] = []
    request: PlanRequestInfo | None = None


class ScenarioInputs(Out):
    name: str
    knowledge_cutoff: str
    effective_date: str
    budget_minor: int
    demand_multiplier: float
    supplier_delay_days: int
    replenishment_basis: str = "leadtime_demand"
    safety_days: int | None = None
    coverage_days: int
    service_level: float | None = None
    forecast_origin: str | None = None
    allow_shortfall: bool
    shortage_penalty_minor: int
    currency: str
    sku_ids: list[str] | None = None


class ScenarioTerms(Out):
    applicable: int
    ignored: list[IgnoredTerm]
    conflicts: list[list[str]]
    excluded_for_conflict: list[str] = []     # conflicting terms the scenario did not plan with (P2-PLAN-05)


class ScenarioResult(Out):
    scenario_id: str
    name: str
    inputs: ScenarioInputs
    value_kinds: dict[str, str] = {}
    forecast_run_id: str
    needs: dict[str, Json] = {}
    plan: PlanOutput
    terms: ScenarioTerms
    metrics: ScenarioMetrics
    controls: dict[str, str] = {}
    scope: Json = {}


class ScenarioRow(Out):
    id: UUID
    as_of: datetime
    status: str
    request: Json
    created_at: datetime
    metrics: ScenarioMetrics | None = None
    name: str | None = None


# ------------------------------------------------------------------------------------------ agent runs
class RunCreated(Out):
    run_id: str
    status: str
    status_url: str
    events_url: str


class RunRow(Out):
    id: UUID
    status: str
    mode: str
    input: Json
    created_at: datetime
    updated_at: datetime
    created_by: str
    actions: int


class RunActionRef(Out):
    id: UUID
    status: str
    total_minor: int
    currency: str
    supplier_id: str


class RunBudget(Out):
    max_tool_calls: int
    max_seconds: int
    max_check_loops: int


class RunSettings(Out):
    knowledge_cutoff: str
    effective_date: str
    currency: str
    dataset_id: str | None = None
    planning: Json = {}
    budget_minor: int


class RunForecast(Out):
    available: bool
    run_id: str | None = None
    model_version_id: str | None = None
    origin: str | None = None
    quality_flags: dict[str, str] = {}


class RunTerms(Out):
    applicable: list[Term]
    ignored: list[IgnoredTerm]
    conflicts: list[list[str]]


class RunDetail(Out):
    id: UUID
    status: str
    mode: str
    input: Json
    budget: RunBudget
    created_at: datetime
    updated_at: datetime
    settings: RunSettings | None = None
    forecast: RunForecast | None = None
    plan: PlanOutput | None = None
    checks: ChecksRef | None = None
    terms: RunTerms | None = None
    upcoming_changes: list[Term] | None = None
    needs: dict[str, Json] | None = None
    tool_calls: int | None = None
    actions: list[RunActionRef]


class RunEvent(Out):
    seq: int
    node: str
    kind: str
    summary: str
    data: Json = {}
    created_at: datetime


# ------------------------------------------------------------------------------------------ actions
class PayloadLine(Out):
    sku_id: str
    quantity: int
    unit: str
    unit_cost_minor: int
    line_minor: int
    term_id: str


class PayloadDecision(Out):
    knowledge_cutoff: str
    effective_date: str
    plan_input_hash: str
    agent_run_id: str


class PurchaseOrderPayload(Out):
    """The exact payload an approver approves and the outbox sends (its hash is bound to the approval)."""
    environment: str
    destination: str
    operation: str
    supplier_id: str
    currency: str
    need_by: str
    lines: list[PayloadLine]
    total_minor: int
    decision: PayloadDecision


class CitedClause(Out):
    """A cited clause. Document-derived fields are null and `withheld` is set when the reader's role may not see the
    document (audit S10)."""
    id: str
    section: str | None = None
    body: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    version_label: str | None = None
    valid_from: date
    known_at: datetime
    sha256: str | None = None
    title: str | None = None
    document_version_id: str
    withheld: str | None = None


class EvidenceTerm(Term):
    citation: CitedClause | None = None


class ForecastRef(Out):
    available: bool
    run_id: str | None = None
    model_version_id: str | None = None
    origin: str | None = None


class PlanRef(Out):
    status: str | None = None
    input_hash: str | None = None
    solver: Json | None = None
    objective: Json | None = None
    explanation: list[str] | None = None


class ProvenanceRef(Out):
    stock: str | None = None
    terms: str | None = None
    budget: str | None = None


class EvidencePacket(Out):
    """Everything an approver needs to decide: data cutoff, forecast, cited terms, plan, checks, provenance."""
    data_cutoff: str
    effective_date: str
    forecast: ForecastRef
    terms: list[EvidenceTerm]
    ignored_terms: list[IgnoredTerm] = []
    upcoming_changes: list[Term] = []
    needs: dict[str, Json | None] = {}
    plan: PlanRef
    checks: ChecksRef
    provenance: ProvenanceRef


class ActionRow(Out):
    id: UUID
    status: str
    total_minor: int
    currency: str
    payload: PurchaseOrderPayload
    payload_hash: str
    row_version: int
    external_ref: str | None = None
    status_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    agent_run_id: UUID | None = None
    prepared_by: str


class Approval(Out):
    id: UUID
    decision: str
    payload_hash: str
    max_spend_minor: int
    reason: str | None = None
    approver_id: UUID
    expires_at: datetime
    created_at: datetime


class OutboxInfo(Out):
    operation_id: str
    status: str
    attempts: int
    last_error: str | None = None
    external_ref: str | None = None
    updated_at: datetime


class ActionDetail(Out):
    id: UUID
    tenant_id: UUID
    kind: str
    status: str
    payload: PurchaseOrderPayload
    payload_hash: str
    evidence: EvidencePacket
    versions: Json
    total_minor: int
    currency: str
    environment: str
    prepared_by: UUID
    agent_run_id: UUID | None = None
    row_version: int
    external_ref: str | None = None
    status_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    approvals: list[Approval]
    outbox: OutboxInfo | None = None


class ActionResult(Out):
    """Outcome of approve / reject / reconcile / retry; unused fields are absent."""
    status: str | None = None
    operation_id: str | None = None
    result: str | None = None
    problems: list[str] | None = None
    po_number: str | None = None
    mismatches: list[str] | None = None


class SandboxOrder(Out):
    po_number: str
    idempotency_key: str
    caller_ref: str
    supplier_id: str
    lines: list[Json]
    total_minor: int
    currency: str
    status: str
    need_by: date | None = None
    created_at: datetime


class ReceiptResult(Out):
    status: str
    po_line_id: str
    received_units: int | None = None
    open_units: int | None = None
    quantity: int | None = None


class CancelOpenResult(Out):
    status: str
    released_units: int


class OpenOrderLine(Out):
    action_id: UUID
    external_ref: str
    supplier_id: str
    sku_id: str
    location_id: str | None = None
    ordered_units: int
    received_units: int
    cancelled_units: int
    open_units: int
    status: str
    ordered_on: date
    expected_on: date | None = None


class FaultInjected(Out):
    ok: bool
    operation_id: str
    mode: str


# ------------------------------------------------------------------------------------------ exceptions / admin
class ExceptionItem(Out):
    kind: str
    basis: str
    sku_id: str | None = None
    action_id: str | None = None
    title: str
    detail: str
    severity: str
    materiality_minor: int | None = None
    materiality_basis: str | None = None
    deadline: str | None = None
    value_kind: str


class Exceptions(Out):
    effective_date: date | None = None
    currency: str | None = None
    items: list[ExceptionItem]
    counts: dict[str, int] = {}
    message: str | None = None


class Member(Out):
    email: str
    display_name: str
    active: bool
    is_dev_account: bool
    role: str
    created_at: datetime


class Members(Out):
    members: list[Member]
    role_matrix: dict[str, list[str]]
    note: str


class JobRow(Out):
    id: UUID
    kind: str
    status: str
    attempts: int
    max_attempts: int
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    result_status: str | None = None


class OutboxRow(Out):
    operation_id: str
    status: str
    attempts: int
    last_error: str | None = None
    external_ref: str | None = None
    next_attempt_at: datetime
    updated_at: datetime


class Jobs(Out):
    jobs: list[JobRow]
    outbox: list[OutboxRow]
    usage: Json


class ModelStatusChanged(Out):
    model_id: str
    status: str


class AuditRow(Out):
    id: int
    action: str
    entity: str
    entity_id: str
    detail: Json
    at: datetime
    actor: str | None = None


class Integration(Out):
    name: str
    status: str
    note: str | None = None
    adapter: str | None = None
    version: str | None = None
    operations: list[str] | None = None
    idempotency: str | None = None
    error: str | None = None


class LedgerAssumptions(Out):
    lead_time_days: int
    review_days: int
    z: float
    holding_rate_annual: float
    unit_cost_share_of_price: float
    currency: str
    notes: str


class LedgerLine(Out):
    item: str
    evidence_class: str
    period: str
    baseline_minor: int
    intervention_minor: int
    unit: str
    source: str
    assumptions: LedgerAssumptions


class PolicyOutcome(Out):
    total_cost: float
    fill_rate: float | None = None
    lost_margin: float | None = None
    holding_cost: float | None = None
    stockout_product_days: int | None = None
    avg_inventory_units: float | None = None
    orders_placed: int | None = None


class Value(Out):
    ledger: list[LedgerLine]
    sensitivity: dict[str, dict[str, PolicyOutcome]] | None = None
    inventorybench: Any | None = None
    formulas: list[str]
    disclaimer: str


# ------------------------------------------------------------------------------------------ alerts / lifecycle / vitals
class AlertRow(Out):
    id: UUID
    kind: str
    severity: str
    dedupe_key: str
    title: str
    detail: Json = {}
    status: str
    occurrences: int
    first_seen: datetime
    last_seen: datetime
    resolved_at: datetime | None = None
    delivery_status: str
    delivery_attempts: int
    delivered_at: datetime | None = None
    delivery_error: str | None = None


class Alerts(Out):
    alerts: list[AlertRow]
    open: int


class AlertAck(Out):
    id: str
    status: str


class AlertEvaluation(Out):
    raised: list[str]
    resolved: int
    delivery: dict[str, int]


class ExportManifest(Out):
    tables: dict[str, int]
    documents: Json
    vectors: Json
    caches: Json
    verified: bool | None = None


class ExportRow(Out):
    id: UUID
    status: str
    include_vectors: bool
    bytes: int | None = None
    sha256: str | None = None
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
    downloaded_at: datetime | None = None
    manifest: ExportManifest | None = None


class JobQueued(Out):
    job_id: str
    status: str


class ExportQueued(JobQueued):
    export_id: str


class DeletionQueued(JobQueued):
    deletion_id: str
    certificate_url: str


class DeletionCertificate(Out):
    tenant_slug: str
    completed_at: datetime
    certificate: Json


class VitalMetric(Out):
    metric: str
    route: str
    n: int
    p75: float
    target: float | None = None
    meets_target: bool | None = None


class Vitals(Out):
    window_days: int
    targets: dict[str, float]
    metrics: list[VitalMetric]
    note: str


# ------------------------------------------------------------------------------------------ research / market
class Comparison(Out):
    mean_diff: float
    ci95: list[float]
    n_series: int
    share_a_better: float


class FamilySummary(Out):
    mae: float
    mase: float | None = None
    pinball_mean: float
    coverage_80: float
    width_80: float
    crossing_rate_raw: float
    pinball: dict[str, float]
    mase_undefined_series: int = 0


class FamilySelection(Out):
    config_index: int
    validation_pinball: float
    config: Json = {}


class StudySelection(Out):
    seasonal_naive: FamilySelection
    lightgbm: FamilySelection
    tcn: FamilySelection
    champion_by_validation: str


class StudySeeds(Out):
    tcn: list[int]


class StudyConfig(Out):
    study_id: str
    version: str
    frozen_at: str
    question: str
    validation_origins: list[str]
    test_origin: str
    seeds: StudySeeds


class StudyEnvironment(Out):
    python: str
    platform: str
    torch: str
    tcn_device: str
    lightgbm: str
    commit: str
    hardware: str


class StudyReview(Out):
    """Reviewed status of the served experiment (evaluations/study_registry.json)."""
    status: str
    headline: str | None = None
    notes: str | None = None
    superseded: list[Json] = []


class ForecastStudyReport(Out):
    """The frozen forecasting study (F1), read from its experiment artifact."""
    available: Literal[True]
    experiment_id: str
    cohort_size: int
    test_window: list[str]
    test_origins: list[str] | None = None
    pooled_mae: dict[str, float] | None = None
    study_version: str | None = None
    selection: StudySelection
    summary: dict[str, FamilySummary]
    tcn_seed_mean: dict[str, float]
    tcn_seed_sd: dict[str, float]
    comparisons: dict[str, Comparison]
    pinball_by_horizon: dict[str, dict[str, list[float]]]
    environment: StudyEnvironment
    config: StudyConfig
    dataset_sha256: str
    review: StudyReview | None = None


class StudyMissing(Out):
    available: Literal[False]
    message: str


class Study(Out):
    """Any other study: an open-ended metrics document from its experiment artifact (or a not-available notice)."""
    available: bool
    message: str | None = None
    review: StudyReview | None = None


class MarketYear(Out):
    fiscal_year: int | None = None
    n: int
    usd: float | None = None


class MarketCategory(Out):
    procurement_category: str | None = None
    n: int
    usd: float | None = None


class MarketRegion(Out):
    region: str | None = None
    n: int
    usd: float | None = None


class MarketCountry(Out):
    supplier_country: str | None = None
    n: int
    usd: float | None = None
    suppliers: int


class MarketSupplier(Out):
    supplier_id: str
    supplier: str | None = None
    country: str | None = None
    n: int
    usd: float | None = None
    borrower_countries: int


class Concentration(Out):
    procurement_category: str | None = None
    hhi: float | None = None
    suppliers: int


class MarketMethod(Out):
    procurement_method: str | None = None
    n: int


class MarketSummary(Out):
    available: bool
    message: str | None = None
    dataset: Json | None = None
    filters: dict[str, str | None] | None = None
    by_year: list[MarketYear] = []
    by_category: list[MarketCategory] = []
    by_region: list[MarketRegion] = []
    top_supplier_countries: list[MarketCountry] = []
    top_suppliers: list[MarketSupplier] = []
    concentration_hhi: list[Concentration] = []
    methods: list[MarketMethod] = []
    value_kind: str | None = None
    currency: str | None = None
    notes: list[str] = []


class SupplierHit(Out):
    supplier_id: str
    supplier: str | None = None
    country: str | None = None
    n: int
    usd: float | None = None
    first_award: date | None = None
    last_award: date | None = None
    categories: list[str | None]


class SupplierAward(Out):
    wb_contract_number: str | None = None
    supplier: str | None = None
    supplier_country: str | None = None
    borrower_country: str | None = None
    region: str | None = None
    procurement_category: str | None = None
    procurement_method: str | None = None
    project_id: str | None = None
    project_name: str | None = None
    contract_description: str | None = None
    signing_date: date | None = None
    fiscal_year: int | None = None
    amount_usd: float | None = None


class SupplierDetail(Out):
    supplier_id: str
    awards: list[SupplierAward]
    value_kind: str


class Health(Out):
    status: str
    database: str


# ------------------------------------------------------------------------------------------ onboarding (S18)
class ImportColumn(Out):
    name: str
    kind: str
    required: bool
    description: str
    example: str


class ImportTemplates(Out):
    schema_version: str
    max_bytes: int
    max_rows: int
    templates: dict[str, list[ImportColumn]]


class ImportBatchRow(Out):
    id: UUID
    kind: str
    status: str
    file_name: str
    sha256: str
    rows_total: int
    rows_valid: int
    rows_quarantined: int
    snapshot_sha256: str | None = None
    created_at: datetime
    published_at: datetime | None = None


class ImportBatch(ImportBatchRow):
    header: list[str]
    mapping: dict[str, str | None]
    report: Json
    dataset_id: UUID | None = None
    columns: list[ImportColumn]
    quarantined_sample: list[Json]
    preview: list[Json]


class WorkspaceCreated(Out):
    tenant_id: str
    slug: str
    name: str


class MembershipChanged(Out):
    email: str
    result: str | None = None
