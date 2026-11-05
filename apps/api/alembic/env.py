from sqlalchemy import create_engine

from alembic import context
from app import models  # noqa: F401  (registra as tabelas no metadata)
from app.config import settings
from app.db import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_online() -> None:
    engine = create_engine(settings.admin_database_url or settings.database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
