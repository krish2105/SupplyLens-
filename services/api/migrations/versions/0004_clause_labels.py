"""Expert clause labels (CUAD) attached to document versions.

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.execute("""
    CREATE TABLE clause_labels (
      id bigserial PRIMARY KEY,
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      version_id uuid NOT NULL REFERENCES document_versions(id),
      category text NOT NULL,
      char_start integer NOT NULL,
      char_end integer NOT NULL,
      text text NOT NULL,
      source text NOT NULL
    )""")
    op.execute("CREATE INDEX clause_labels_version ON clause_labels (tenant_id, version_id, category)")
    op.execute("ALTER TABLE clause_labels ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE clause_labels FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON clause_labels USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
               "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON clause_labels TO supplylens_app")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE clause_labels_id_seq TO supplylens_app")


def downgrade() -> None:
    op.execute("DROP TABLE clause_labels")
