import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.core.db import Base
import app.models  # noqa: F401  (ensures all models are imported before autogenerate)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Migrations run as the owner. The app itself logs in as `solver_runtime`
# (migration 0037), which may not change the schema; compose hands the
# owner's URL to this process as MIGRATION_DATABASE_URL. Without it -- the
# test suite, a bare checkout -- DATABASE_URL is the owner's anyway.
_url = os.environ.get("MIGRATION_DATABASE_URL") or get_settings().database_url
# configparser would read a `%` in a password as interpolation.
config.set_main_option("sqlalchemy.url", _url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
