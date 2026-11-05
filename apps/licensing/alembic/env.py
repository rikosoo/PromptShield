import os

from sqlalchemy import create_engine

from alembic import context
from lic_service.config import settings
from lic_service.models import Base

url = os.environ.get("LICENSING_ADMIN_DATABASE_URL") or settings.database_url
VERSION_TABLE = "alembic_version_licensing"   # não colide com a tabela de versões da API quando os dois compartilham um banco de teste

with create_engine(url).connect() as conn:
    context.configure(connection=conn, target_metadata=Base.metadata, version_table=VERSION_TABLE)
    with context.begin_transaction():
        context.run_migrations()
