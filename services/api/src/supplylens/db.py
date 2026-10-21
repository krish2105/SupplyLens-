"""Database engines and tenant-scoped sessions.

The application engine connects as a non-owner role subject to row-level security.
Every tenant-owned query must run inside `tenant_session`, which sets the tenant
GUC transaction-locally so pooled connections never leak context.
"""
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .config import settings


@lru_cache(maxsize=4)
def engine_for(url: str) -> Engine:
    # All timestamps are handled in UTC; business dates are derived explicitly, never from session TZ.
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10,
                         connect_args={"options": "-c timezone=UTC"})


def app_engine() -> Engine:
    return engine_for(settings.database_url)


def admin_engine() -> Engine:
    return engine_for(settings.admin_database_url)


@contextmanager
def tenant_session(tenant_id: UUID | str, engine: Engine | None = None) -> Iterator[Session]:
    """Open a transaction with app.tenant_id set; commits on success, rolls back on error."""
    factory = sessionmaker(bind=engine or app_engine(), expire_on_commit=False)
    with factory() as session, session.begin():
        session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(UUID(str(tenant_id)))}
        )
        yield session


@contextmanager
def control_session(engine: Engine | None = None) -> Iterator[Session]:
    """Session without tenant context: only control-plane tables (tenants, users) are visible."""
    factory = sessionmaker(bind=engine or app_engine(), expire_on_commit=False)
    with factory() as session, session.begin():
        yield session
