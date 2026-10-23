"""ERP connector state, receipt/status synchronisation and operational visibility (Phase 6).

* erp_connector_state (per tenant, RLS): connector health as the dispatcher saw it (OK, UNAVAILABLE with a circuit-breaker
  pause, CREDENTIALS_INVALID until a health probe succeeds), plus the receipt-feed cursor and last sync times.
* outbox.failure_kind: why a dispatch stopped (rejected by the target, retries exhausted, interrupted, ...), so a
  business rejection is never retried blindly.
* worker_heartbeats (control plane): every worker records each tick, so the API can report a stopped worker.
* alerts gain kinds erp_connector, erp_sync and overdue_receipt.
* sandbox_erp (the local simulator, "another system"): goods receipts with a feed sequence, an order cancellation
  reason, a connector switch (outage / expired credentials) and the fault mode 'reject'.

Rollback refuses while alerts of the new kinds exist (operational records); the sandbox's receipts are simulator data.

Revision ID: 0011
Revises: 0010
"""
from alembic import op

revision = "0011"
down_revision = "0010"

POLICY = ("USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
          "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")
OLD_KINDS = "'stale_data', 'failed_reconciliation', 'budget_exhausted', 'model_unavailable', 'job_failed'"
NEW_KINDS = "'erp_connector', 'erp_sync', 'overdue_receipt'"
OLD_FAULTS = ("'timeout_after_commit', 'fail_before_commit', 'alter_line_price', 'duplicate_line', 'change_unit', "
              "'change_need_by', 'cancel_after_commit'")


def upgrade() -> None:
    op.execute("""
    CREATE TABLE erp_connector_state (
      tenant_id uuid PRIMARY KEY REFERENCES tenants(id),
      adapter text NOT NULL,
      status text NOT NULL DEFAULT 'OK' CHECK (status IN ('OK', 'UNAVAILABLE', 'CREDENTIALS_INVALID')),
      consecutive_failures integer NOT NULL DEFAULT 0,
      paused_until timestamptz,
      last_error text,
      last_success_at timestamptz,
      last_failure_at timestamptz,
      last_probe_at timestamptz,
      receipts_cursor bigint NOT NULL DEFAULT 0,
      last_receipt_sync_at timestamptz,
      last_order_sync_at timestamptz,
      updated_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("ALTER TABLE erp_connector_state ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE erp_connector_state FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON erp_connector_state {POLICY}")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON erp_connector_state TO supplylens_app")

    op.execute("ALTER TABLE outbox ADD COLUMN failure_kind text CHECK (failure_kind IN "
               "('rejected', 'exhausted', 'interrupted', 'stale'))")

    op.execute("""
    CREATE TABLE worker_heartbeats (
      worker_id text PRIMARY KEY,
      host text NOT NULL,
      started_at timestamptz NOT NULL DEFAULT now(),
      last_tick_at timestamptz NOT NULL DEFAULT now(),
      ticks bigint NOT NULL DEFAULT 0,
      last_error text,
      last_error_at timestamptz
    )""")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON worker_heartbeats TO supplylens_app")

    op.execute("ALTER TABLE alerts DROP CONSTRAINT alerts_kind_check")
    op.execute(f"ALTER TABLE alerts ADD CONSTRAINT alerts_kind_check CHECK (kind IN ({OLD_KINDS}, {NEW_KINDS}))")

    op.execute("ALTER TABLE sandbox_erp.purchase_orders ADD COLUMN status_reason text, "
               "ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now()")
    op.execute("ALTER TABLE sandbox_erp.fault_injection DROP CONSTRAINT fault_injection_mode_check")
    op.execute(f"ALTER TABLE sandbox_erp.fault_injection ADD CONSTRAINT fault_injection_mode_check "
               f"CHECK (mode IN ({OLD_FAULTS}, 'reject'))")
    op.execute("""
    CREATE TABLE sandbox_erp.receipts (
      seq bigserial PRIMARY KEY,
      receipt_id text NOT NULL UNIQUE,
      po_number text NOT NULL REFERENCES sandbox_erp.purchase_orders(po_number),
      sku_id text NOT NULL,
      location_id text,
      quantity integer NOT NULL CHECK (quantity > 0),
      received_on date NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("""
    CREATE TABLE sandbox_erp.connector (
      id smallint PRIMARY KEY CHECK (id = 1),
      available boolean NOT NULL DEFAULT true,
      credentials_valid boolean NOT NULL DEFAULT true
    )""")
    op.execute("INSERT INTO sandbox_erp.connector (id) VALUES (1)")
    op.execute("GRANT SELECT, INSERT ON sandbox_erp.receipts TO supplylens_app")
    op.execute("GRANT SELECT, UPDATE ON sandbox_erp.connector TO supplylens_app")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE sandbox_erp.receipts_seq_seq TO supplylens_app")


def downgrade() -> None:
    guard = ("DO $$ BEGIN IF EXISTS (SELECT 1 FROM alerts WHERE kind IN (" + NEW_KINDS + ")) THEN "  # noqa: S608
             "RAISE EXCEPTION 'refusing to roll back 0011: ERP connector/sync alerts exist; resolve and export them first'; "
             "END IF; END $$")
    op.execute(guard)
    op.execute("DROP TABLE sandbox_erp.connector")
    op.execute("DROP TABLE sandbox_erp.receipts")
    op.execute("DELETE FROM sandbox_erp.fault_injection WHERE mode = 'reject'")
    op.execute("ALTER TABLE sandbox_erp.fault_injection DROP CONSTRAINT fault_injection_mode_check")
    op.execute(f"ALTER TABLE sandbox_erp.fault_injection ADD CONSTRAINT fault_injection_mode_check CHECK (mode IN ({OLD_FAULTS}))")
    op.execute("ALTER TABLE sandbox_erp.purchase_orders DROP COLUMN status_reason, DROP COLUMN updated_at")
    op.execute("ALTER TABLE alerts DROP CONSTRAINT alerts_kind_check")
    op.execute(f"ALTER TABLE alerts ADD CONSTRAINT alerts_kind_check CHECK (kind IN ({OLD_KINDS}))")
    op.execute("DROP TABLE worker_heartbeats")
    op.execute("ALTER TABLE outbox DROP COLUMN failure_kind")
    op.execute("DROP TABLE erp_connector_state")
