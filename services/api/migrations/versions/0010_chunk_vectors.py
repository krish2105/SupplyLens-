"""Embeddings move from chunks into chunk_vectors (Phase 3, retrieval cost).

A 1024-d vector is 4 KB, stored inline since 0006, so a chunk row was ~5 KB and the full-text scan (which cannot use its
GIN index under row-level security, D-035) read every vector it never looks at: 782 MB of heap for 100,000 chunks. Both
retrieval queries scanned the whole table, so each search moved about 1.5 GB through the buffer cache. With the vectors in
their own table the lexical scan reads only text and the vector scan only vectors.

chunk_vectors has the same forced row-level security policy as every tenant table and a cascade from chunks. Existing
vectors are copied workspace by workspace under that workspace's context (row-level security applies to the owner too),
then chunks is rewritten without the column (ALTER ... TYPE with USING forces a transactional rewrite; DROP COLUMN alone
leaves the old bytes in place). Rollback copies the vectors back the same way and drops the table.

Revision ID: 0010
Revises: 0009
"""
from alembic import op

revision = "0010"
down_revision = "0009"

POLICY = ("USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
          "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")


def upgrade() -> None:
    op.execute("""CREATE TABLE chunk_vectors (
        chunk_id uuid PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        version_id uuid NOT NULL REFERENCES document_versions(id),
        embedding vector(1024) NOT NULL)""")
    op.execute("ALTER TABLE chunk_vectors ALTER COLUMN embedding SET STORAGE PLAIN")   # inline: no TOAST fetch per row
    op.execute("CREATE INDEX chunk_vectors_version ON chunk_vectors (tenant_id, version_id)")
    op.execute("ALTER TABLE chunk_vectors ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE chunk_vectors FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON chunk_vectors {POLICY}")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON chunk_vectors TO supplylens_app")
    op.execute("""
    DO $$
    DECLARE t uuid;
    BEGIN
      FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        INSERT INTO chunk_vectors (chunk_id, tenant_id, version_id, embedding)
          SELECT id, tenant_id, version_id, embedding FROM chunks WHERE embedding IS NOT NULL;
      END LOOP;
      PERFORM set_config('app.tenant_id', '', true);
    END $$""")
    op.execute("ALTER TABLE chunks DROP COLUMN embedding")
    op.execute("ALTER TABLE chunks ALTER COLUMN ordinal TYPE integer USING ordinal + 0")   # an expression forces the rewrite


def downgrade() -> None:
    op.execute("ALTER TABLE chunks ADD COLUMN embedding vector(1024)")
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding SET STORAGE PLAIN")
    op.execute("""
    DO $$
    DECLARE t uuid;
    BEGIN
      FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        UPDATE chunks c SET embedding = v.embedding FROM chunk_vectors v WHERE v.chunk_id = c.id;
      END LOOP;
      PERFORM set_config('app.tenant_id', '', true);
    END $$""")
    op.execute("DROP TABLE chunk_vectors")
