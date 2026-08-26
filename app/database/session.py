from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@lru_cache(maxsize=4)
def _get_engine(database_url: str, role: str = "app") -> AsyncEngine:
    # ARQ-01.4: pools separados por papel. O worker roda eventos operacionais
    # de polling a cada ciclo e competia pelo mesmo pool da UI; com pool menor
    # e dedicado, a UI não fica sem conexões quando o worker está ocupado.
    pool_config = (
        {"pool_size": 10, "max_overflow": 10}
        if role == "app"
        else {"pool_size": 4, "max_overflow": 4}
    )
    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        pool_recycle=1800,
        **pool_config,
    )


def get_engine() -> AsyncEngine:
    from app.config.settings import get_settings

    return _get_engine(get_settings().database_url)


def get_async_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)


def get_worker_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Sessionmaker do worker com pool dedicado (ARQ-01.4)."""
    from app.config.settings import get_settings

    return async_sessionmaker(
        _get_engine(get_settings().database_url, role="worker"),
        class_=AsyncSession,
        expire_on_commit=False,
    )


# Mantido para compatibilidade com codigo que importa AsyncSessionLocal diretamente.
from app.config.settings import get_settings as _get_settings  # noqa: E402

engine: AsyncEngine = _get_engine(_get_settings().database_url)
AsyncSessionLocal: async_sessionmaker[AsyncSession] = get_async_sessionmaker()


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a session with centralized commit/rollback semantics.

    On successful completion of the dependency, commits the transaction.
    On exception, rolls back. This ensures callers don't need to remember
    to commit explicitly (though they can flush within the transaction).
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Fecha o engine e limpa o cache — usar no shutdown da aplicacao."""
    _get_engine.cache_clear()
    await engine.dispose()
