"""Alembic environment: migrations always run as the owner role, never the app role."""
import os

from alembic import context
from sqlalchemy import create_engine

from supplylens.config import settings

url = os.environ.get("SUPPLYLENS_MIGRATION_URL") or settings.owner_database_url


def run() -> None:
    engine = create_engine(url)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


run()
