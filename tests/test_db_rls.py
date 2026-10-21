import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError, DBAPIError

from supplylens.db import app_engine, control_session, tenant_session


def _add_supplier(tenant, sid):
    with tenant_session(tenant) as s:
        s.execute(
            text("INSERT INTO suppliers VALUES (:t, :s, 'x', 'generated', 'simulated')"),
            {"t": tenant, "s": sid},
        )


def test_app_role_is_not_owner_and_cannot_bypass_rls():
    with app_engine().connect() as c:
        row = c.execute(
            text("SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = current_user")
        ).one()
        assert row == (False, False)
        owner = c.execute(text("SELECT tableowner FROM pg_tables WHERE tablename='suppliers'")).scalar()
        assert owner != c.execute(text("SELECT current_user")).scalar()


def test_tenant_rows_invisible_across_tenants(clean_db, tenant_a, tenant_b):
    _add_supplier(tenant_a, "SUP-A")
    _add_supplier(tenant_b, "SUP-B")
    with tenant_session(tenant_a) as s:
        assert s.execute(text("SELECT supplier_id FROM suppliers")).scalars().all() == ["SUP-A"]
    with tenant_session(tenant_b) as s:
        assert s.execute(text("SELECT supplier_id FROM suppliers")).scalars().all() == ["SUP-B"]


def test_missing_tenant_context_sees_nothing(clean_db, tenant_a):
    _add_supplier(tenant_a, "SUP-A")
    with control_session() as s:
        assert s.execute(text("SELECT count(*) FROM suppliers")).scalar() == 0


def test_cannot_write_into_other_tenant(clean_db, tenant_a, tenant_b):
    with pytest.raises((ProgrammingError, DBAPIError)):
        with tenant_session(tenant_a) as s:
            s.execute(
                text("INSERT INTO suppliers VALUES (:t, 'EVIL', 'x', 'generated', 'simulated')"),
                {"t": tenant_b},
            )


def test_cannot_update_rows_to_other_tenant(clean_db, tenant_a, tenant_b):
    _add_supplier(tenant_a, "SUP-A")
    with pytest.raises((ProgrammingError, DBAPIError)):
        with tenant_session(tenant_a) as s:
            s.execute(text("UPDATE suppliers SET tenant_id = :b"), {"b": tenant_b})


def test_tenant_context_does_not_leak_between_pooled_transactions(clean_db, tenant_a):
    _add_supplier(tenant_a, "SUP-A")
    for _ in range(5):
        with tenant_session(tenant_a) as s:
            s.execute(text("SELECT 1"))
        with control_session() as s:
            assert s.execute(text("SELECT current_setting('app.tenant_id', true)")).scalar() in (None, "")
            assert s.execute(text("SELECT count(*) FROM suppliers")).scalar() == 0


def test_app_role_cannot_write_control_plane_or_rewrite_audit(clean_db, tenant_a):
    with pytest.raises((ProgrammingError, DBAPIError)):
        with control_session() as s:
            s.execute(text("INSERT INTO tenants VALUES (:i,'x','x','demo','',now())"), {"i": uuid.uuid4()})
    with tenant_session(tenant_a) as s:
        s.execute(
            text("INSERT INTO audit_events (tenant_id, action, entity, entity_id) VALUES (:t,'a','e','1')"),
            {"t": tenant_a},
        )
    with pytest.raises((ProgrammingError, DBAPIError)):
        with tenant_session(tenant_a) as s:
            s.execute(text("DELETE FROM audit_events"))
