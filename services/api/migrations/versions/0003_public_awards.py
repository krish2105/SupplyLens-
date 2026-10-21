"""World Bank IPF contract awards (public, CC BY 4.0) as tenant-scoped reference data.

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.execute("""
    CREATE TABLE public_awards (
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      dataset_id uuid NOT NULL REFERENCES datasets(id),
      source_row integer NOT NULL,
      wb_contract_number text,
      supplier_id text,
      supplier text,
      supplier_country text,
      borrower_country text,
      region text,
      procurement_category text,
      procurement_method text,
      project_id text,
      project_name text,
      contract_description text,
      signing_date date,
      fiscal_year integer,
      amount_usd numeric(18,2),
      review_type text,
      PRIMARY KEY (tenant_id, dataset_id, source_row)
    )""")
    op.execute("CREATE INDEX public_awards_supplier ON public_awards (tenant_id, supplier_id)")
    op.execute("CREATE INDEX public_awards_cat ON public_awards (tenant_id, procurement_category, fiscal_year)")
    op.execute("CREATE INDEX public_awards_supplier_trgm ON public_awards USING gin (to_tsvector('simple', coalesce(supplier,'')))")
    op.execute("ALTER TABLE public_awards ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public_awards FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON public_awards USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
               "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON public_awards TO supplylens_app")


def downgrade() -> None:
    op.execute("DROP TABLE public_awards")
