from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from starlette.requests import Request

from app.core.settings import Settings


class Database:
    """Owns the async engine and explicit session/transaction boundaries."""

    def __init__(self, settings: Settings) -> None:
        if not settings.database_url:
            raise ValueError("DATABASE_URL must be configured before creating database access")
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_recycle=1800,
        )
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        """Yield a session that commits on success and rolls back on any error."""

        async with self.session_factory() as session:
            try:
                async with session.begin():
                    yield session
            except BaseException:
                await session.rollback()
                raise

    async def dispose(self) -> None:
        await self.engine.dispose()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency for future DB-backed endpoints.

    Endpoint code gets a transaction that is committed only after its coroutine
    completes successfully; failures are rolled back before propagating.
    """

    database: Database | None = request.app.state.database
    if database is None:
        raise RuntimeError("DATABASE_URL is not configured")
    async with database.transaction() as session:
        yield session
