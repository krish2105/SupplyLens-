"""Reliability and lifecycle: atomic idempotency claims, shared rate limits, alerts, tenant export/deletion,
field Web Vitals.

* idempotency_keys gains a claim state so concurrent identical requests cannot both execute (DEF-02).
* rate_limit_buckets moves token buckets out of process memory into PostgreSQL (DEF-03).
* alerts is the operational queue for stale data, failed reconciliation, exhausted budgets and unavailable models.
* tenant_exports records verified tenant exports; tenant_deletions (control plane) records deletion certificates.
  The app role cannot write control-plane tables, so the final step of a deletion is a narrow SECURITY DEFINER
  function that refuses to act outside the caller's own tenant context or on non-customer workspaces.
* web_vitals stores field measurements (LCP, INP, CLS, FCP, TTFB) reported by the browser.

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"

TENANT_TABLES = ["rate_limit_buckets", "alerts", "tenant_exports", "web_vitals"]
POLICY = ("USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
          "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ADD COLUMN deleted_at timestamptz")

    op.execute("""
    ALTER TABLE idempotency_keys
      ALTER COLUMN status_code DROP NOT NULL,
      ALTER COLUMN response DROP NOT NULL,
      ADD COLUMN state text NOT NULL DEFAULT 'DONE' CHECK (state IN ('IN_PROGRESS', 'DONE')),
      ADD COLUMN claimed_until timestamptz""")

    op.execute("""
    CREATE TABLE rate_limit_buckets (
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      bucket text NOT NULL,
      tokens double precision NOT NULL,
      updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      PRIMARY KEY (tenant_id, bucket)
    )""")

    op.execute("""
    CREATE TABLE alerts (
      id uuid PRIMARY KEY,
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      kind text NOT NULL CHECK (kind IN ('stale_data', 'failed_reconciliation', 'budget_exhausted', 'model_unavailable')),
      severity text NOT NULL CHECK (severity IN ('low', 'medium', 'high')),
      dedupe_key text NOT NULL,
      title text NOT NULL,
      detail jsonb NOT NULL DEFAULT '{}'::jsonb,
      status text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED')),
      occurrences integer NOT NULL DEFAULT 1,
      first_seen timestamptz NOT NULL DEFAULT now(),
      last_seen timestamptz NOT NULL DEFAULT now(),
      resolved_at timestamptz,
      acknowledged_by uuid REFERENCES users(id),
      delivery_status text NOT NULL DEFAULT 'NONE' CHECK (delivery_status IN ('NONE', 'PENDING', 'DELIVERED', 'FAILED')),
      delivery_attempts integer NOT NULL DEFAULT 0,
      next_delivery_at timestamptz,
      delivery_error text,
      delivered_at timestamptz
    )""")
    # One live alert per condition; a resolved condition that recurs opens a new alert.
    op.execute("CREATE UNIQUE INDEX alerts_live ON alerts (tenant_id, dedupe_key) WHERE status <> 'RESOLVED'")
    op.execute("CREATE INDEX alerts_open ON alerts (tenant_id, status, last_seen DESC)")

    op.execute("""
    CREATE TABLE tenant_exports (
      id uuid PRIMARY KEY,
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      status text NOT NULL CHECK (status IN ('QUEUED', 'RUNNING', 'READY', 'FAILED')),
      include_vectors boolean NOT NULL DEFAULT false,
      requested_by uuid NOT NULL REFERENCES users(id),
      file_path text,
      bytes bigint,
      sha256 text,
      manifest jsonb,
      error text,
      created_at timestamptz NOT NULL DEFAULT now(),
      finished_at timestamptz,
      downloaded_at timestamptz
    )""")

    op.execute("""
    CREATE TABLE web_vitals (
      id bigserial PRIMARY KEY,
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      user_id uuid REFERENCES users(id),
      metric text NOT NULL CHECK (metric IN ('LCP', 'INP', 'CLS', 'FCP', 'TTFB')),
      value double precision NOT NULL,
      rating text NOT NULL CHECK (rating IN ('good', 'needs-improvement', 'poor')),
      route text NOT NULL,
      nav_type text,
      at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX web_vitals_metric ON web_vitals (tenant_id, metric, route, at DESC)")

    for t in TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} {POLICY}")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO supplylens_app")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE web_vitals_id_seq TO supplylens_app")
    # Deleting a workspace also removes the sandbox ERP orders created for it (local simulator only).
    op.execute("GRANT DELETE ON sandbox_erp.purchase_orders TO supplylens_app")

    # Control plane: deletion certificates survive the tenant's data. Read-only for the app role.
    op.execute("""
    CREATE TABLE tenant_deletions (
      id uuid PRIMARY KEY,
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      tenant_slug text NOT NULL,
      requested_by uuid NOT NULL REFERENCES users(id),
      export_id uuid,
      completed_at timestamptz NOT NULL DEFAULT now(),
      certificate jsonb NOT NULL
    )""")
    op.execute("GRANT SELECT ON tenant_deletions TO supplylens_app")
    op.execute("GRANT DELETE ON tenant_settings TO supplylens_app")
    # audit_events is append-only for the app role. A workspace deletion must also remove its audit rows, so the one
    # privileged step is this function: it refuses unless the caller's tenant context matches, the workspace is a
    # live customer workspace, and every other tenant table is already empty (the deletion job's own row excepted).
    op.execute("""
    CREATE FUNCTION sl_finalize_tenant_deletion(p_id uuid, p_tenant uuid, p_requested_by uuid, p_export uuid,
                                                p_certificate jsonb) RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
    DECLARE
      t text;
      n bigint;
      audit_rows integer;
    BEGIN
      IF p_tenant IS DISTINCT FROM NULLIF(current_setting('app.tenant_id', true), '')::uuid THEN
        RAISE EXCEPTION 'tenant context mismatch';
      END IF;
      IF NOT EXISTS (SELECT 1 FROM tenants WHERE id = p_tenant AND kind = 'customer' AND deleted_at IS NULL) THEN
        RAISE EXCEPTION 'only live customer workspaces can be deleted';
      END IF;
      FOR t IN SELECT c.relname FROM pg_class c JOIN pg_namespace ns ON ns.oid = c.relnamespace
               JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id' AND NOT a.attisdropped
               WHERE ns.nspname = 'public' AND c.relkind = 'r' AND c.relrowsecurity
                 AND c.relname NOT IN ('audit_events', 'jobs')
      LOOP
        EXECUTE format('SELECT count(*) FROM %I WHERE tenant_id = $1', t) INTO n USING p_tenant;
        IF n > 0 THEN RAISE EXCEPTION 'workspace not empty: % has % rows', t, n; END IF;
      END LOOP;
      DELETE FROM audit_events WHERE tenant_id = p_tenant;
      GET DIAGNOSTICS audit_rows = ROW_COUNT;
      UPDATE tenants SET deleted_at = now() WHERE id = p_tenant;
      DELETE FROM memberships WHERE tenant_id = p_tenant;
      INSERT INTO tenant_deletions (id, tenant_id, tenant_slug, requested_by, export_id, certificate)
        SELECT p_id, p_tenant, slug, p_requested_by, p_export,
               p_certificate || jsonb_build_object('audit_events_deleted', audit_rows)
        FROM tenants WHERE id = p_tenant;
      RETURN audit_rows;
    END $$""")
    op.execute("REVOKE ALL ON FUNCTION sl_finalize_tenant_deletion(uuid, uuid, uuid, uuid, jsonb) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION sl_finalize_tenant_deletion(uuid, uuid, uuid, uuid, jsonb) TO supplylens_app")


def downgrade() -> None:
    # Deletion certificates are legal evidence and live only in this table: never drop them silently.
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM tenant_deletions) THEN
        RAISE EXCEPTION 'refusing to roll back 0005: tenant_deletions holds deletion certificates; export them first';
      END IF;
    END $$""")
    op.execute("REVOKE DELETE ON tenant_settings FROM supplylens_app")
    op.execute("REVOKE DELETE ON sandbox_erp.purchase_orders FROM supplylens_app")
    op.execute("DROP FUNCTION sl_finalize_tenant_deletion(uuid, uuid, uuid, uuid, jsonb)")
    op.execute("DROP TABLE tenant_deletions")
    for t in reversed(TENANT_TABLES):
        op.execute(f"DROP TABLE {t}")
    # In-progress claims have no response; drop them before restoring NOT NULL.
    op.execute("DELETE FROM idempotency_keys WHERE state <> 'DONE' OR response IS NULL")
    op.execute("""
    ALTER TABLE idempotency_keys
      DROP COLUMN claimed_until, DROP COLUMN state,
      ALTER COLUMN response SET NOT NULL, ALTER COLUMN status_code SET NOT NULL""")
    op.execute("ALTER TABLE tenants DROP COLUMN deleted_at")
