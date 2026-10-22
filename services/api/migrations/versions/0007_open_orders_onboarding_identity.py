"""Open orders and receipts, CSV onboarding, identity lifecycle, richer sandbox read-back.

* purchase_order_lines is the open-order ledger (audit S12): one row per reconciled order line, keyed to the outbox
  operation and the external purchase-order number. Receipts move units from open to received exactly once
  (receipts.idempotency_key is unique per tenant); cancellation releases the open quantity. Planning adds the open
  quantity of SupplyLens orders dated on or after a stock snapshot (business dates, not wall-clock time: the research
  workspaces run on a simulated clock), and the units received since, to that snapshot.
* import_batches / import_rows hold uploaded CSV files (sales, stock, terms) through map -> validate -> quarantine ->
  publish (audit S18). A published batch is immutable: it records the SHA-256 of its normalised rows.
* users.oidc_subject links a local user to an identity-provider subject; memberships.source says whether a membership
  is managed locally or by identity-provider role claims (audit S09/S18).
* Control-plane writes stay closed to the app role. Four narrow SECURITY DEFINER functions are the only write paths:
  sl_create_workspace, sl_set_membership, sl_upsert_oidc_user and sl_sync_oidc_memberships. Each checks its caller.
* sandbox_erp.purchase_orders gains need_by; fault injection gains read-back faults that make the simulator store an
  order that differs from the request (price, duplicate line, unit, cancellation), for read-back verification tests.

Rollback keeps data. Downgrading moves the four tables and the identity columns' values into schema retired_0007
instead of dropping them, and the next upgrade moves them back, so a release rollback and roll-forward lose no open
orders, receipts, imports or identity links (rehearsed in tests/test_rehearsals.py).

Revision ID: 0007
Revises: 0006
"""
from alembic import op

revision = "0007"
down_revision = "0006"

TENANT_TABLES = ["purchase_order_lines", "receipts", "import_batches", "import_rows"]
POLICY = ("USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
          "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")


def _restore_retired() -> bool:
    """Move tables parked by a previous downgrade back into public. Returns True when they were restored."""
    bind = op.get_bind()
    if bind.exec_driver_sql("SELECT to_regclass('retired_0007.purchase_order_lines')").scalar() is None:
        return False
    for t in ("import_batches", "import_rows", "purchase_order_lines", "receipts"):
        op.execute(f"ALTER TABLE retired_0007.{t} SET SCHEMA public")
    return True


def upgrade() -> None:
    op.execute("ALTER TABLE sandbox_erp.purchase_orders ADD COLUMN need_by date")
    op.execute("ALTER TABLE sandbox_erp.fault_injection DROP CONSTRAINT fault_injection_mode_check")
    op.execute("""ALTER TABLE sandbox_erp.fault_injection ADD CONSTRAINT fault_injection_mode_check CHECK (mode IN (
        'timeout_after_commit', 'fail_before_commit', 'alter_line_price', 'duplicate_line', 'change_unit',
        'change_need_by', 'cancel_after_commit'))""")

    restored = _restore_retired()
    if not restored:
        op.execute("""
        CREATE TABLE purchase_order_lines (
          id uuid PRIMARY KEY,
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          action_id uuid NOT NULL REFERENCES actions(id),
          operation_id text NOT NULL,
          external_ref text NOT NULL,
          supplier_id text NOT NULL,
          location_id text,
          sku_id text NOT NULL,
          ordered_units integer NOT NULL CHECK (ordered_units > 0),
          received_units integer NOT NULL DEFAULT 0 CHECK (received_units >= 0),
          cancelled_units integer NOT NULL DEFAULT 0 CHECK (cancelled_units >= 0),
          ordered_on date NOT NULL,
          expected_on date,
          status text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'PARTIAL', 'RECEIVED', 'CANCELLED')),
          confirmed_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CHECK (received_units + cancelled_units <= ordered_units),
          UNIQUE (tenant_id, action_id, sku_id)
        )""")
        op.execute("CREATE INDEX purchase_order_lines_open ON purchase_order_lines (tenant_id, sku_id) "
                   "WHERE status IN ('OPEN', 'PARTIAL')")
        op.execute("""
        CREATE TABLE receipts (
          id uuid PRIMARY KEY,
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          po_line_id uuid NOT NULL REFERENCES purchase_order_lines(id),
          sku_id text NOT NULL,
          quantity integer NOT NULL CHECK (quantity > 0),
          received_on date NOT NULL,
          recorded_at timestamptz NOT NULL DEFAULT now(),
          idempotency_key text NOT NULL,
          created_by uuid REFERENCES users(id),
          UNIQUE (tenant_id, idempotency_key)
        )""")

        op.execute("""
        CREATE TABLE import_batches (
          id uuid PRIMARY KEY,
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          kind text NOT NULL CHECK (kind IN ('sales', 'stock', 'terms')),
          status text NOT NULL CHECK (status IN ('UPLOADED', 'VALIDATED', 'PUBLISHED', 'REJECTED')),
          file_name text NOT NULL,
          sha256 text NOT NULL,
          bytes integer NOT NULL,
          header text[] NOT NULL,
          mapping jsonb NOT NULL DEFAULT '{}'::jsonb,
          report jsonb NOT NULL DEFAULT '{}'::jsonb,
          rows_total integer NOT NULL DEFAULT 0,
          rows_valid integer NOT NULL DEFAULT 0,
          rows_quarantined integer NOT NULL DEFAULT 0,
          snapshot_sha256 text,
          dataset_id uuid REFERENCES datasets(id),
          created_by uuid NOT NULL REFERENCES users(id),
          created_at timestamptz NOT NULL DEFAULT now(),
          published_at timestamptz,
          published_by uuid REFERENCES users(id),
          UNIQUE (tenant_id, kind, sha256)
        )""")
        op.execute("""
        CREATE TABLE import_rows (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          batch_id uuid NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
          row_no integer NOT NULL,
          raw jsonb NOT NULL,
          normalized jsonb,
          errors text[] NOT NULL DEFAULT '{}',
          PRIMARY KEY (tenant_id, batch_id, row_no)
        )""")
    # Published batches and their rows are immutable for the application role.
    op.execute("""
    CREATE FUNCTION sl_import_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      -- workspace deletion (lifecycle._purge_rows) sets app.purging for its own transaction only
      IF TG_OP = 'DELETE' AND current_setting('app.purging', true) = 'on' THEN
        RETURN OLD;
      END IF;
      -- nested IFs: PL/pgSQL resolves OLD's fields even when an AND's first operand is false
      IF TG_TABLE_NAME = 'import_batches' THEN
        IF OLD.status = 'PUBLISHED' THEN
          RAISE EXCEPTION 'published import batch % is immutable', OLD.id;
        END IF;
      ELSIF EXISTS (SELECT 1 FROM import_batches b WHERE b.id = OLD.batch_id AND b.status = 'PUBLISHED') THEN
        RAISE EXCEPTION 'rows of published import batch % are immutable', OLD.batch_id;
      END IF;
      RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END $$""")
    op.execute("CREATE TRIGGER import_batches_immutable BEFORE UPDATE OR DELETE ON import_batches "
               "FOR EACH ROW EXECUTE FUNCTION sl_import_immutable()")
    op.execute("CREATE TRIGGER import_rows_immutable BEFORE UPDATE OR DELETE ON import_rows "
               "FOR EACH ROW EXECUTE FUNCTION sl_import_immutable()")

    if not restored:
        for t in TENANT_TABLES:
            op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
            op.execute(f"CREATE POLICY tenant_isolation ON {t} {POLICY}")
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO supplylens_app")

    op.execute("ALTER TABLE users ADD COLUMN oidc_subject text UNIQUE, ADD COLUMN deactivated_at timestamptz")
    # Identity-provider sessions (control plane, no tenant): the encrypted refresh token lets the API re-confirm the
    # account with the provider every few minutes, so a deactivation in the provider ends the SupplyLens session.
    op.execute("""
    CREATE TABLE auth_sessions (
      id uuid PRIMARY KEY,
      user_id uuid NOT NULL REFERENCES users(id),
      oidc_subject text NOT NULL,
      refresh_token_enc text,
      created_at timestamptz NOT NULL DEFAULT now(),
      checked_at timestamptz NOT NULL DEFAULT now(),
      revoked_at timestamptz,
      revoked_reason text
    )""")
    op.execute("GRANT SELECT, INSERT, UPDATE ON auth_sessions TO supplylens_app")
    op.execute("ALTER TABLE memberships ADD COLUMN source text NOT NULL DEFAULT 'local' "
               "CHECK (source IN ('local', 'oidc'))")
    if restored:
        op.execute("""UPDATE users u SET oidc_subject = r.oidc_subject, deactivated_at = r.deactivated_at
                      FROM retired_0007.user_identity r WHERE r.id = u.id""")
        op.execute("""UPDATE memberships m SET source = r.source FROM retired_0007.membership_source r
                      WHERE r.tenant_id = m.tenant_id AND r.user_id = m.user_id""")
        op.execute("""UPDATE sandbox_erp.purchase_orders o SET need_by = r.need_by
                      FROM retired_0007.sandbox_need_by r WHERE r.po_number = o.po_number""")
        op.execute("DROP SCHEMA retired_0007 CASCADE")

    # A tenant administrator creates a new customer workspace and becomes its first administrator.
    op.execute("""
    CREATE FUNCTION sl_create_workspace(p_id uuid, p_slug text, p_name text, p_actor uuid) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM memberships m JOIN users u ON u.id = m.user_id JOIN tenants t ON t.id = m.tenant_id
                     WHERE m.user_id = p_actor AND m.role = 'tenant_admin' AND u.active AND t.deleted_at IS NULL) THEN
        RAISE EXCEPTION 'only an active workspace administrator can create a workspace';
      END IF;
      IF p_slug !~ '^[a-z0-9][a-z0-9-]{2,40}$' THEN
        RAISE EXCEPTION 'workspace slug must be 3-41 lowercase letters, digits or hyphens';
      END IF;
      INSERT INTO tenants (id, slug, name, kind, description)
        VALUES (p_id, p_slug, p_name, 'customer', 'Created by CSV onboarding');
      INSERT INTO memberships (tenant_id, user_id, role) VALUES (p_id, p_actor, 'tenant_admin');
      RETURN p_id;
    END $$""")
    # A tenant administrator adds, changes or removes (p_role NULL) a local membership in their own workspace.
    op.execute("""
    CREATE FUNCTION sl_set_membership(p_tenant uuid, p_actor uuid, p_email text, p_role text) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
    DECLARE
      target uuid;
    BEGIN
      IF p_tenant IS DISTINCT FROM NULLIF(current_setting('app.tenant_id', true), '')::uuid THEN
        RAISE EXCEPTION 'tenant context mismatch';
      END IF;
      IF NOT EXISTS (SELECT 1 FROM memberships m JOIN users u ON u.id = m.user_id
                     WHERE m.tenant_id = p_tenant AND m.user_id = p_actor AND m.role = 'tenant_admin' AND u.active) THEN
        RAISE EXCEPTION 'only an active administrator of this workspace can change memberships';
      END IF;
      SELECT id INTO target FROM users WHERE lower(email) = lower(p_email);
      IF target IS NULL THEN RAISE EXCEPTION 'no user with that email'; END IF;
      IF EXISTS (SELECT 1 FROM memberships WHERE tenant_id = p_tenant AND user_id = target AND source = 'oidc') THEN
        RAISE EXCEPTION 'this membership is managed by the identity provider';
      END IF;
      IF target = p_actor AND p_role IS DISTINCT FROM 'tenant_admin' THEN
        RAISE EXCEPTION 'administrators cannot remove or demote themselves';
      END IF;
      IF p_role IS NULL THEN
        DELETE FROM memberships WHERE tenant_id = p_tenant AND user_id = target;
        RETURN 'removed';
      END IF;
      INSERT INTO memberships (tenant_id, user_id, role) VALUES (p_tenant, target, p_role)
        ON CONFLICT (tenant_id, user_id) DO UPDATE SET role = EXCLUDED.role;
      RETURN p_role;
    END $$""")
    # Sign-in through the identity provider: link by subject, else by verified email, else create the user.
    op.execute("""
    CREATE FUNCTION sl_upsert_oidc_user(p_subject text, p_email text, p_name text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
    DECLARE
      uid uuid;
    BEGIN
      SELECT id INTO uid FROM users WHERE oidc_subject = p_subject;
      IF uid IS NULL THEN
        SELECT id INTO uid FROM users WHERE lower(email) = lower(p_email) AND oidc_subject IS NULL;
        IF uid IS NULL THEN
          uid := gen_random_uuid();
          INSERT INTO users (id, email, display_name, oidc_subject) VALUES (uid, lower(p_email), p_name, p_subject);
        ELSE
          UPDATE users SET oidc_subject = p_subject WHERE id = uid;
        END IF;
      END IF;
      UPDATE users SET display_name = p_name, active = true, deactivated_at = NULL WHERE id = uid;
      RETURN uid;
    END $$""")
    # Role claims from the identity provider replace that user's provider-managed memberships. Local memberships are
    # never touched. p_grants: [{"tenant": "<slug>", "role": "<role>"}].
    op.execute("""
    CREATE FUNCTION sl_sync_oidc_memberships(p_user uuid, p_grants jsonb) RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
    DECLARE
      g jsonb;
      tid uuid;
      n integer := 0;
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM users WHERE id = p_user AND oidc_subject IS NOT NULL) THEN
        RAISE EXCEPTION 'not an identity-provider user';
      END IF;
      DELETE FROM memberships WHERE user_id = p_user AND source = 'oidc';
      FOR g IN SELECT * FROM jsonb_array_elements(p_grants) LOOP
        SELECT id INTO tid FROM tenants WHERE slug = g->>'tenant' AND deleted_at IS NULL;
        CONTINUE WHEN tid IS NULL OR g->>'role' NOT IN ('viewer', 'planner', 'approver', 'tenant_admin');
        INSERT INTO memberships (tenant_id, user_id, role, source) VALUES (tid, p_user, g->>'role', 'oidc')
          ON CONFLICT (tenant_id, user_id) DO NOTHING;
        n := n + 1;
      END LOOP;
      RETURN n;
    END $$""")
    # The identity provider reported the account disabled: deactivate locally (sessions stop on the next request).
    op.execute("""
    CREATE FUNCTION sl_deactivate_oidc_user(p_subject text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
    BEGIN
      UPDATE users SET active = false, deactivated_at = now() WHERE oidc_subject = p_subject AND active;
      RETURN FOUND;
    END $$""")
    for fn in ("sl_create_workspace(uuid, text, text, uuid)", "sl_set_membership(uuid, uuid, text, text)",
               "sl_upsert_oidc_user(text, text, text)", "sl_sync_oidc_memberships(uuid, jsonb)",
               "sl_deactivate_oidc_user(text)"):
        op.execute(f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO supplylens_app")


def downgrade() -> None:
    # Park, never drop: the next upgrade restores everything below (see module docstring).
    op.execute("DROP SCHEMA IF EXISTS retired_0007 CASCADE")
    op.execute("CREATE SCHEMA retired_0007")
    op.execute("""CREATE TABLE retired_0007.user_identity AS SELECT id, oidc_subject, deactivated_at FROM users
                  WHERE oidc_subject IS NOT NULL OR deactivated_at IS NOT NULL""")
    op.execute("CREATE TABLE retired_0007.membership_source AS SELECT tenant_id, user_id, source FROM memberships "
               "WHERE source <> 'local'")
    op.execute("CREATE TABLE retired_0007.sandbox_need_by AS SELECT po_number, need_by FROM sandbox_erp.purchase_orders "
               "WHERE need_by IS NOT NULL")
    for fn in ("sl_deactivate_oidc_user(text)", "sl_sync_oidc_memberships(uuid, jsonb)",
               "sl_upsert_oidc_user(text, text, text)", "sl_set_membership(uuid, uuid, text, text)",
               "sl_create_workspace(uuid, text, text, uuid)"):
        op.execute(f"DROP FUNCTION {fn}")
    op.execute("ALTER TABLE memberships DROP COLUMN source")
    op.execute("DROP TABLE IF EXISTS auth_sessions")  # sessions are not records: users sign in again after a rollback
    op.execute("ALTER TABLE users DROP COLUMN deactivated_at, DROP COLUMN oidc_subject")
    op.execute("DROP TRIGGER import_rows_immutable ON import_rows")
    op.execute("DROP TRIGGER import_batches_immutable ON import_batches")
    op.execute("DROP FUNCTION sl_import_immutable()")
    for t in ("receipts", "purchase_order_lines", "import_rows", "import_batches"):
        op.execute(f"ALTER TABLE {t} SET SCHEMA retired_0007")
    op.execute("DELETE FROM sandbox_erp.fault_injection WHERE mode NOT IN ('timeout_after_commit', 'fail_before_commit')")
    op.execute("ALTER TABLE sandbox_erp.fault_injection DROP CONSTRAINT fault_injection_mode_check")
    op.execute("ALTER TABLE sandbox_erp.fault_injection ADD CONSTRAINT fault_injection_mode_check "
               "CHECK (mode IN ('timeout_after_commit', 'fail_before_commit'))")
    op.execute("ALTER TABLE sandbox_erp.purchase_orders DROP COLUMN need_by")
