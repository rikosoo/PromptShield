from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session

from app.config import settings

NAMING = {
    "pk": "pk_%(table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ix": "ix_%(table_name)s_%(column_0_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url, pool_pre_ping=True)
    return _engine


def reset_engine() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


@contextmanager
def tenant_session(tenant_id: uuid.UUID) -> Iterator[Session]:
    """Sessão cujo `app.tenant_id` vale só nesta transação (SET LOCAL via set_config).

    O row-level security do Postgres usa essa variável. Sem ela, nenhuma linha é visível.
    """
    with Session(get_engine()) as session, session.begin():
        session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        yield session


@contextmanager
def anonymous_session() -> Iterator[Session]:
    """Sem tenant: só para chamar as funções de autenticação SECURITY DEFINER."""
    with Session(get_engine()) as session, session.begin():
        yield session
