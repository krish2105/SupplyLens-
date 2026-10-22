"""Goods-receipt imports and per-location order lines.

* import_batches.kind gains 'receipts' (ERP receipt feed for the open-order ledger, audit S12).
* purchase_order_lines is unique per action, SKU and location (NULLS NOT DISTINCT), so one order can carry the same SKU
  for several locations (SKU-location planning, audit S21).

Revision ID: 0008
Revises: 0007
"""
from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    op.execute("ALTER TABLE import_batches DROP CONSTRAINT import_batches_kind_check")
    op.execute("ALTER TABLE import_batches ADD CONSTRAINT import_batches_kind_check "
               "CHECK (kind IN ('sales', 'stock', 'terms', 'receipts'))")
    op.execute("ALTER TABLE purchase_order_lines DROP CONSTRAINT purchase_order_lines_tenant_id_action_id_sku_id_key")
    op.execute("ALTER TABLE purchase_order_lines ADD CONSTRAINT purchase_order_lines_action_sku_location_key "
               "UNIQUE NULLS NOT DISTINCT (tenant_id, action_id, sku_id, location_id)")


def downgrade() -> None:
    # Receipt batches are records of booked goods: refuse rather than drop them.
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM import_batches WHERE kind = 'receipts') THEN
        RAISE EXCEPTION 'refusing to roll back 0008: receipt import batches exist; export them first';
      END IF;
    END $$""")
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM purchase_order_lines GROUP BY tenant_id, action_id, sku_id HAVING count(*) > 1) THEN
        RAISE EXCEPTION 'refusing to roll back 0008: orders carry one SKU for several locations';
      END IF;
    END $$""")
    op.execute("ALTER TABLE purchase_order_lines DROP CONSTRAINT purchase_order_lines_action_sku_location_key")
    op.execute("ALTER TABLE purchase_order_lines ADD CONSTRAINT purchase_order_lines_tenant_id_action_id_sku_id_key "
               "UNIQUE (tenant_id, action_id, sku_id)")
    op.execute("ALTER TABLE import_batches DROP CONSTRAINT import_batches_kind_check")
    op.execute("ALTER TABLE import_batches ADD CONSTRAINT import_batches_kind_check "
               "CHECK (kind IN ('sales', 'stock', 'terms'))")
