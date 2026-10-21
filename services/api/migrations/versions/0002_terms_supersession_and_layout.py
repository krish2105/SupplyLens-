"""Term supersession links and schematic warehouse layout.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.execute("ALTER TABLE supplier_terms ADD COLUMN supersedes_term_id text")
    op.execute("""
    CREATE TABLE warehouse_slots (
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      location_id text NOT NULL,
      slot_id text NOT NULL,
      zone_id text NOT NULL,
      aisle integer NOT NULL,
      rack integer NOT NULL,
      x double precision NOT NULL,
      z double precision NOT NULL,
      sku_id text,
      is_schematic boolean NOT NULL DEFAULT true,
      PRIMARY KEY (tenant_id, location_id, slot_id)
    )""")
    op.execute("ALTER TABLE warehouse_slots ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE warehouse_slots FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON warehouse_slots "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON warehouse_slots TO supplylens_app")
    # Operational settings per tenant (decision date, budget) — tenant-owned, RLS.
    op.execute("""
    CREATE TABLE tenant_settings (
      tenant_id uuid PRIMARY KEY REFERENCES tenants(id),
      operational_as_of timestamptz NOT NULL,
      currency char(3) NOT NULL,
      dataset_id uuid REFERENCES datasets(id),
      assumption_set_id uuid REFERENCES assumption_sets(id),
      planning jsonb NOT NULL DEFAULT '{}'::jsonb
    )""")
    op.execute("ALTER TABLE tenant_settings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_settings FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON tenant_settings "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")
    op.execute("GRANT SELECT, INSERT, UPDATE ON tenant_settings TO supplylens_app")


def downgrade() -> None:
    op.execute("DROP TABLE tenant_settings")
    op.execute("DROP TABLE warehouse_slots")
    op.execute("ALTER TABLE supplier_terms DROP COLUMN supersedes_term_id")
