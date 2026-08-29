from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlmodel import SQLModel

from core.settings import get_settings

_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            connect_args=(
                {"check_same_thread": False}
                if settings.database_url.startswith("sqlite")
                else {}
            ),
            pool_pre_ping=True,
        )
    return _engine


def get_session_maker() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
            expire_on_commit=False,
        )
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    session_local = get_session_maker()
    session = session_local()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_db_and_tables() -> None:
    # 🛑 `create_all` создаёт только те таблицы, чьи модели УЖЕ импортированы —
    # он читает `SQLModel.metadata`, а она наполняется импортом. Модель, не
    # импортированную в этой цепочке, он молча пропустит, и таблицы на проде
    # просто не будет. Импорт здесь, а не у вызывающих: иначе один забытый
    # импорт в одном из входов (api / worker / тесты) даёт разную схему.
    from core.domain import delivery, job  # noqa: F401

    engine = get_engine()
    SQLModel.metadata.create_all(engine)
