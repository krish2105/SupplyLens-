"""Core schema: tenancy, datasets, sales, simulated operations, forecasting, knowledge,
actions, jobs, outbox, agent runs, audit, and the sandbox ERP.

Every tenant-owned table has RLS enabled and forced. The app role is not the owner
and has no BYPASSRLS, so policies apply to it. Missing tenant context matches no rows.

Revision ID: 0001
Revises:
"""
from alembic import op

revision = "0001"
down_revision = None

TENANT_TABLES = [
    "datasets", "quarantine", "products", "locations", "sales_lines",
    "return_lines", "sales_daily", "assumption_sets", "suppliers", "inventory_positions",
    "documents", "document_versions", "chunks", "supplier_terms", "model_versions",
    "forecast_runs", "forecast_points", "plan_runs", "agent_runs", "agent_events",
    "actions", "approvals", "idempotency_keys", "outbox", "jobs", "audit_events",
]

SCHEMA = r"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE tenants (
  id uuid PRIMARY KEY,
  slug text NOT NULL UNIQUE,
  name text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('research', 'demo', 'customer')),
  description text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id uuid PRIMARY KEY,
  email text NOT NULL UNIQUE,
  display_name text NOT NULL,
  is_dev_account boolean NOT NULL DEFAULT false,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE memberships (
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  user_id uuid NOT NULL REFERENCES users(id),
  role text NOT NULL CHECK (role IN ('viewer', 'planner', 'approver', 'tenant_admin')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, user_id)
);

-- A dataset row is one immutable ingested source file (a dataset version).
CREATE TABLE datasets (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  name text NOT NULL,
  source_kind text NOT NULL CHECK (source_kind IN ('public', 'user_supplied', 'generated')),
  license text NOT NULL,
  source_url text,
  file_name text NOT NULL,
  sha256 text NOT NULL,
  bytes bigint NOT NULL,
  schema_version text NOT NULL,
  status text NOT NULL CHECK (status IN ('PROFILING', 'INGESTING', 'READY', 'FAILED')),
  report jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, sha256)
);

CREATE TABLE quarantine (
  id bigserial PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  dataset_id uuid NOT NULL REFERENCES datasets(id),
  source_sheet text NOT NULL,
  source_row integer NOT NULL,
  reason text NOT NULL,
  raw jsonb NOT NULL
);
CREATE INDEX quarantine_ds ON quarantine (tenant_id, dataset_id);

CREATE TABLE products (
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  sku_id text NOT NULL,
  description text NOT NULL DEFAULT '',
  unit text NOT NULL DEFAULT 'unit',
  source_kind text NOT NULL,
  dataset_id uuid REFERENCES datasets(id),
  first_sale date,
  last_sale date,
  PRIMARY KEY (tenant_id, sku_id)
);

CREATE TABLE locations (
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  location_id text NOT NULL,
  name text NOT NULL,
  kind text NOT NULL,
  is_schematic boolean NOT NULL DEFAULT true,
  value_kind text NOT NULL,
  PRIMARY KEY (tenant_id, location_id)
);

CREATE TABLE sales_lines (
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  dataset_id uuid NOT NULL REFERENCES datasets(id),
  source_sheet text NOT NULL,
  source_row integer NOT NULL,
  invoice text NOT NULL,
  sku_id text NOT NULL,
  quantity integer NOT NULL,
  unit_price_minor bigint NOT NULL,
  currency char(3) NOT NULL,
  invoiced_at timestamp NOT NULL,
  customer_id text,
  country text,
  PRIMARY KEY (tenant_id, dataset_id, source_sheet, source_row)
);

CREATE TABLE return_lines (LIKE sales_lines INCLUDING ALL);
ALTER TABLE return_lines ADD COLUMN return_kind text NOT NULL;

-- Gold: fulfilled positive units per day. Days without rows inside a product's active
-- span mean "no recorded sales", not observed zero demand.
CREATE TABLE sales_daily (
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  dataset_id uuid NOT NULL REFERENCES datasets(id),
  sku_id text NOT NULL,
  location_id text NOT NULL,
  day date NOT NULL,
  units integer NOT NULL CHECK (units >= 0),
  PRIMARY KEY (tenant_id, dataset_id, sku_id, location_id, day)
);

CREATE TABLE assumption_sets (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  name text NOT NULL,
  version integer NOT NULL,
  params jsonb NOT NULL,
  rationale text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, name, version)
);

CREATE TABLE suppliers (
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  supplier_id text NOT NULL,
  name text NOT NULL,
  source_kind text NOT NULL,
  value_kind text NOT NULL,
  PRIMARY KEY (tenant_id, supplier_id)
);

CREATE TABLE inventory_positions (
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  location_id text NOT NULL,
  zone_id text NOT NULL,
  sku_id text NOT NULL,
  as_of date NOT NULL,
  on_hand integer NOT NULL CHECK (on_hand >= 0),
  allocated integer NOT NULL CHECK (allocated >= 0),
  on_order integer NOT NULL CHECK (on_order >= 0),
  capacity integer,
  value_kind text NOT NULL,
  assumption_set_id uuid REFERENCES assumption_sets(id),
  PRIMARY KEY (tenant_id, location_id, sku_id, as_of)
);

CREATE TABLE documents (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  title text NOT NULL,
  doc_type text NOT NULL,
  supplier_id text,
  source_kind text NOT NULL,
  allowed_roles text[] NOT NULL DEFAULT ARRAY['viewer','planner','approver','tenant_admin']
);

CREATE TABLE document_versions (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  document_id uuid NOT NULL REFERENCES documents(id),
  version_label text NOT NULL,
  file_name text NOT NULL,
  sha256 text NOT NULL,
  storage_key text NOT NULL,
  known_at timestamptz NOT NULL,
  valid_from date NOT NULL,
  valid_to date,
  supersedes_version_id uuid REFERENCES document_versions(id),
  parser_version text NOT NULL,
  embed_model text,
  ingested_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, sha256)
);

CREATE TABLE chunks (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  version_id uuid NOT NULL REFERENCES document_versions(id),
  ordinal integer NOT NULL,
  section text NOT NULL,
  char_start integer NOT NULL,
  char_end integer NOT NULL,
  body text NOT NULL,
  tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', body)) STORED,
  embedding vector(1024)
);
CREATE INDEX chunks_tsv ON chunks USING gin (tsv);
CREATE INDEX chunks_version ON chunks (tenant_id, version_id);

CREATE TABLE supplier_terms (
  term_id text NOT NULL,
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  supplier_id text NOT NULL,
  sku_id text NOT NULL,
  unit_cost_minor bigint NOT NULL CHECK (unit_cost_minor > 0),
  currency char(3) NOT NULL,
  moq integer NOT NULL CHECK (moq >= 1),
  order_multiple integer NOT NULL CHECK (order_multiple >= 1),
  lead_time_days integer NOT NULL CHECK (lead_time_days >= 0),
  valid_from date NOT NULL,
  valid_to date,
  known_at timestamptz NOT NULL,
  document_version_id uuid REFERENCES document_versions(id),
  section text,
  value_kind text NOT NULL,
  source_kind text NOT NULL,
  PRIMARY KEY (tenant_id, term_id)
);

CREATE TABLE model_versions (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  family text NOT NULL,
  version text NOT NULL,
  status text NOT NULL CHECK (status IN ('TRAINING','EVALUATED','CANDIDATE','CHAMPION','RETIRED','FAILED')),
  dataset_id uuid REFERENCES datasets(id),
  training_cutoff date,
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
  artifact_path text,
  artifact_sha256 text,
  code_version text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, family, version)
);

CREATE TABLE forecast_runs (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  model_version_id uuid NOT NULL REFERENCES model_versions(id),
  dataset_id uuid NOT NULL REFERENCES datasets(id),
  origin date NOT NULL,
  horizon integer NOT NULL CHECK (horizon BETWEEN 1 AND 90),
  status text NOT NULL,
  sku_ids text[] NOT NULL,
  quality_flags jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE forecast_points (
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  run_id uuid NOT NULL REFERENCES forecast_runs(id),
  sku_id text NOT NULL,
  day date NOT NULL,
  q10 double precision NOT NULL,
  q50 double precision NOT NULL,
  q90 double precision NOT NULL,
  PRIMARY KEY (tenant_id, run_id, sku_id, day)
);

CREATE TABLE plan_runs (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  as_of timestamptz NOT NULL,
  request jsonb NOT NULL,
  input_hash text NOT NULL,
  status text NOT NULL,
  result jsonb NOT NULL,
  created_by uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE agent_runs (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  status text NOT NULL,
  mode text NOT NULL CHECK (mode IN ('observe', 'recommend', 'draft', 'execute')),
  input jsonb NOT NULL,
  state jsonb NOT NULL DEFAULT '{}'::jsonb,
  budget jsonb NOT NULL,
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE agent_events (
  seq bigserial PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  run_id uuid NOT NULL REFERENCES agent_runs(id),
  node text NOT NULL,
  kind text NOT NULL,
  summary text NOT NULL,
  data jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX agent_events_run ON agent_events (tenant_id, run_id, seq);

CREATE TABLE actions (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  kind text NOT NULL CHECK (kind IN ('purchase_order_draft')),
  status text NOT NULL CHECK (status IN ('PENDING_APPROVAL','APPROVED','REJECTED','STALE','QUEUED',
                                         'SUBMITTED','UNKNOWN_OUTCOME','CONFIRMED','RECONCILED','FAILED')),
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  evidence jsonb NOT NULL,
  versions jsonb NOT NULL,
  total_minor bigint NOT NULL,
  currency char(3) NOT NULL,
  environment text NOT NULL DEFAULT 'sandbox',
  prepared_by uuid NOT NULL REFERENCES users(id),
  agent_run_id uuid REFERENCES agent_runs(id),
  row_version integer NOT NULL DEFAULT 1,
  external_ref text,
  status_reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE approvals (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  action_id uuid NOT NULL REFERENCES actions(id),
  decision text NOT NULL CHECK (decision IN ('APPROVED', 'REJECTED')),
  payload_hash text NOT NULL,
  versions jsonb NOT NULL,
  max_spend_minor bigint NOT NULL,
  reason text,
  approver_id uuid NOT NULL REFERENCES users(id),
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE idempotency_keys (
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  key text NOT NULL,
  route text NOT NULL,
  request_hash text NOT NULL,
  status_code integer NOT NULL,
  response jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, key)
);

CREATE TABLE outbox (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  action_id uuid NOT NULL REFERENCES actions(id),
  operation_id text NOT NULL,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  status text NOT NULL CHECK (status IN ('PENDING','IN_FLIGHT','DELIVERED','UNKNOWN_OUTCOME','FAILED')),
  attempts integer NOT NULL DEFAULT 0,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  lease_owner text,
  lease_expires_at timestamptz,
  fencing_token bigint NOT NULL DEFAULT 0,
  last_error text,
  external_ref text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, operation_id),
  UNIQUE (tenant_id, action_id)
);

CREATE TABLE jobs (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  kind text NOT NULL,
  payload jsonb NOT NULL,
  status text NOT NULL CHECK (status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
  attempts integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 3,
  run_after timestamptz NOT NULL DEFAULT now(),
  lease_owner text,
  lease_expires_at timestamptz,
  fencing_token bigint NOT NULL DEFAULT 0,
  result jsonb,
  error text,
  created_by uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX jobs_ready ON jobs (tenant_id, status, run_after);

CREATE TABLE audit_events (
  id bigserial PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  actor_id uuid REFERENCES users(id),
  action text NOT NULL,
  entity text NOT NULL,
  entity_id text NOT NULL,
  detail jsonb NOT NULL DEFAULT '{}'::jsonb,
  at timestamptz NOT NULL DEFAULT now()
);

-- Sandbox ERP: stands in for an external purchasing system. It is deliberately outside
-- tenant RLS (it is "another system") and deduplicates on the caller's idempotency key.
CREATE SCHEMA sandbox_erp;
CREATE TABLE sandbox_erp.purchase_orders (
  po_number text PRIMARY KEY,
  idempotency_key text NOT NULL UNIQUE,
  caller_ref text NOT NULL,
  supplier_id text NOT NULL,
  lines jsonb NOT NULL,
  total_minor bigint NOT NULL,
  currency char(3) NOT NULL,
  status text NOT NULL DEFAULT 'OPEN',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE SEQUENCE sandbox_erp.po_seq START 100001;
CREATE TABLE sandbox_erp.fault_injection (
  idempotency_key text PRIMARY KEY,
  mode text NOT NULL CHECK (mode IN ('timeout_after_commit', 'fail_before_commit'))
);
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            f"WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
    op.execute("GRANT USAGE ON SCHEMA public, sandbox_erp TO supplylens_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO supplylens_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA sandbox_erp TO supplylens_app")
    op.execute("GRANT DELETE ON sandbox_erp.fault_injection TO supplylens_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public, sandbox_erp TO supplylens_app")
    # Control-plane tables are readable but not writable by the app role.
    # Memberships are control-plane: readable (to resolve a user's tenants at sign-in) but
    # changed only by the owner/admin tooling, never by ordinary application requests.
    op.execute("REVOKE INSERT, UPDATE, DELETE ON tenants, users, memberships FROM supplylens_app")
    # Audit trail is append-only for the application role.
    op.execute("REVOKE UPDATE, DELETE ON audit_events FROM supplylens_app")


def downgrade() -> None:
    op.execute("DROP SCHEMA sandbox_erp CASCADE")
    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP TABLE IF EXISTS memberships, users, tenants CASCADE")
