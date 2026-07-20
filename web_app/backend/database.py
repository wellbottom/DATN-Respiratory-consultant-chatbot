from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .settings import AppSettings


class Base(DeclarativeBase):
    pass


_ENGINE: Engine | None = None
_SESSION_FACTORY: sessionmaker[Session] | None = None


def configure_database(settings: AppSettings) -> None:
    global _ENGINE, _SESSION_FACTORY

    if _ENGINE is not None and _SESSION_FACTORY is not None:
        return

    connect_args: dict[str, object] = {}
    engine_kwargs: dict[str, object] = {"future": True}
    if settings.database_url.startswith("sqlite"):
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        connect_args["check_same_thread"] = False
    else:
        engine_kwargs["pool_pre_ping"] = True

    _ENGINE = create_engine(settings.database_url, connect_args=connect_args, **engine_kwargs)
    _SESSION_FACTORY = sessionmaker(bind=_ENGINE, autoflush=False, autocommit=False, expire_on_commit=False)


def get_engine() -> Engine:
    if _ENGINE is None:
        raise RuntimeError("Cơ sở dữ liệu chưa được cấu hình.")
    return _ENGINE


def get_db() -> Generator[Session, None, None]:
    if _SESSION_FACTORY is None:
        raise RuntimeError("Cơ sở dữ liệu chưa được cấu hình.")

    session = _SESSION_FACTORY()
    try:
        yield session
    finally:
        session.close()
