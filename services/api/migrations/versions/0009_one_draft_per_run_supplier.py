"""One purchase-order draft per agent run and supplier (audit P2-REL-02); alert kind job_failed (P2-REL-01).

The investigator checks for an existing draft before preparing one, but the check and the insert are separate
transactions: two executions of the same run (a lease lost to a stalled heartbeat) could both prepare a draft for the
same supplier. A unique index makes the database the arbiter; the agent treats a conflict as "already prepared".
Alerts gain the kind 'job_failed' for jobs whose lease expired on their last attempt.
Rollback drops the index and loses no data; it refuses while job_failed alerts exist (they are operational records).

Revision ID: 0009
Revises: 0008
"""
from alembic import op

revision = "0009"
down_revision = "0008"


KINDS = "'stale_data', 'failed_reconciliation', 'budget_exhausted', 'model_unavailable'"


def upgrade() -> None:
    op.execute("CREATE UNIQUE INDEX actions_one_draft_per_run_supplier ON actions "
               "(tenant_id, agent_run_id, (payload->>'supplier_id')) WHERE agent_run_id IS NOT NULL")
    op.execute("ALTER TABLE alerts DROP CONSTRAINT alerts_kind_check")
    op.execute(f"ALTER TABLE alerts ADD CONSTRAINT alerts_kind_check CHECK (kind IN ({KINDS}, 'job_failed'))")


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM alerts WHERE kind = 'job_failed') THEN
        RAISE EXCEPTION 'refusing to roll back 0009: job_failed alerts exist; resolve and export them first';
      END IF;
    END $$""")
    op.execute("ALTER TABLE alerts DROP CONSTRAINT alerts_kind_check")
    op.execute(f"ALTER TABLE alerts ADD CONSTRAINT alerts_kind_check CHECK (kind IN ({KINDS}))")
    op.execute("DROP INDEX IF EXISTS actions_one_draft_per_run_supplier")
