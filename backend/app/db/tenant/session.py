from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Final

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

MAX_CACHED_ENGINES: Final[int] = 100

_cache_lock = threading.Lock()
_engine_cache: "OrderedDict[str, Engine]" = OrderedDict()


def _url_for_tenant(db_name: str) -> str:
    return get_settings().database_url_tenant_template.format(tenant_db=db_name)


def get_tenant_engine(db_name: str) -> Engine:
    """Return a cached engine for a tenant DB name (bounded LRU)."""
    with _cache_lock:
        if db_name in _engine_cache:
            _engine_cache.move_to_end(db_name)
            return _engine_cache[db_name]
        engine = create_engine(
            _url_for_tenant(db_name),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            future=True,
        )
        _engine_cache[db_name] = engine
        while len(_engine_cache) > MAX_CACHED_ENGINES:
            _, evicted = _engine_cache.popitem(last=False)
            evicted.dispose()
        return engine


def dispose_tenant_engine(db_name: str) -> None:
    """Dispose and evict the cached engine for one tenant database.

    Necessary before DROP DATABASE: a pooled connection makes the drop fail
    with "database is being accessed by other users". clear_engine_cache()
    would work but disposes every tenant's pool, which is wrong inside an
    operation that targets a single database.

    Safe to call when nothing is cached -- that is the normal case in
    production and the common case in tests.
    """
    with _cache_lock:
        engine = _engine_cache.pop(db_name, None)
    if engine is not None:
        engine.dispose()


def clear_engine_cache() -> None:
    with _cache_lock:
        for engine in _engine_cache.values():
            engine.dispose()
        _engine_cache.clear()


@contextmanager
def tenant_session(db_name: str) -> Iterator[Session]:
    engine = get_tenant_engine(db_name)
    factory = sessionmaker(
        bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
    )
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()