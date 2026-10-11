import os
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core import config  # noqa: F401  (loads .env)
from app.db.models import Base

_INITIALISED: set[str] = set()


def database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite:///./jobhunt.db")


@lru_cache(maxsize=1)
def get_engine():
    url = database_url()
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
    return create_engine(url, **kwargs)


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def reset_engine_cache() -> None:      # used by tests / CLI after changing DATABASE_URL
    get_engine.cache_clear(); get_sessionmaker.cache_clear()


def init_db() -> None:
    url = database_url()
    if url not in _INITIALISED:
        Base.metadata.create_all(get_engine())   # idempotent
        _INITIALISED.add(url)


@contextmanager
def session_scope():
    init_db()
    s: Session = get_sessionmaker()()
    try:
        yield s
    finally:
        s.close()
