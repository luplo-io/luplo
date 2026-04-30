"""Alembic environment configuration for luplo."""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine

config = context.config

# Prefer the URL set on the alembic Config (e.g. via ``_migrate.build_config``)
# so programmatic callers can target a specific database. Fall back to the
# ``LUPLO_DB_URL`` env var only when the Config has none — that path is what
# ``alembic upgrade head`` uses when the user runs the bare CLI.
# Normalise to psycopg v3 dialect so callers can pass a plain ``postgresql://``
# URL without worrying about the SQLAlchemy driver.
db_url = config.get_main_option("sqlalchemy.url") or os.environ.get("LUPLO_DB_URL")
if db_url and db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)


def run_migrations_offline() -> None:
    context.configure(url=db_url, target_metadata=None, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(db_url)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
