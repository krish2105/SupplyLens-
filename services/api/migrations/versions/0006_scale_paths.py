"""Scale paths found by the ARC-07 reference-profile load test (100,000 chunks, 1,000,000 sales rows).

* chunks.embedding is stored inline (STORAGE PLAIN). A 1024-d float4 vector is 4 KB, so the default (EXTENDED) put every
  vector in TOAST and an exact cosine scan paid ~16 buffer touches per row; measured exact-search time fell from 610 ms to
  210 ms at 100,000 chunks. chunks.body and chunks.tsv become STORAGE MAIN: with a 4 KB inline vector in the row, EXTENDED
  would push them out of line (and compress them), and full-text search under row-level security must read and match the
  tsvector of every row of the tenant (the GIN index cannot be used there, see ARC-07 report), which cost 3.1 s per query at
  100,000 chunks against 0.24 s inline. Existing rows are rewritten tenant by tenant (row-level security still applies).
* sales_daily (tenant_id, day): the 28-day recent-sales aggregate behind inventory and exceptions was a full table scan.
* supplier_terms (tenant_id, sku_id): the per-SKU term count and term lookups were sequential scans.

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.execute("""ALTER TABLE chunks ALTER COLUMN embedding SET STORAGE PLAIN,
                  ALTER COLUMN body SET STORAGE MAIN, ALTER COLUMN tsv SET STORAGE MAIN""")
    op.execute("""
    DO $$
    DECLARE t uuid;
    BEGIN
      FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        -- the cast round-trip and the concatenation force new, inline datums (the generated tsv is recomputed);
        -- float4 -> real[] -> vector is lossless
        UPDATE chunks SET embedding = embedding::real[]::vector, body = body || '';
      END LOOP;
    END $$""")
    op.execute("CREATE INDEX sales_daily_tenant_day ON sales_daily (tenant_id, day)")
    op.execute("CREATE INDEX supplier_terms_tenant_sku ON supplier_terms (tenant_id, sku_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS supplier_terms_tenant_sku")
    op.execute("DROP INDEX IF EXISTS sales_daily_tenant_day")
    op.execute("""ALTER TABLE chunks ALTER COLUMN embedding SET STORAGE EXTENDED,
                  ALTER COLUMN body SET STORAGE EXTENDED, ALTER COLUMN tsv SET STORAGE EXTENDED""")
