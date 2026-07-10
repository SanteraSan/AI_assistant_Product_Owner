from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.base import Base
from app.db import models  # noqa: F401


def create_engine(postgres_dsn: str) -> AsyncEngine:
    return create_async_engine(
        postgres_dsn,
        pool_pre_ping=True,
    )


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        engine,
        expire_on_commit=False,
    )


async def init_db(engine: AsyncEngine, *, auto_create: bool = True) -> None:
    if not auto_create:
        return
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def database_available(engine: AsyncEngine) -> bool:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


async def iter_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
