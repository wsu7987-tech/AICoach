"""Database-backed immutable configuration loading for Runtime executions."""

from __future__ import annotations

import asyncio
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import RuntimeState
from app.providers.factory import configuration_error
from app.services import config_service
from app.services.intent_service import BusinessRuntimeConfiguration


class DatabaseBusinessConfigLoader:
    """Load only Active Release business rules for ManagedModel Runtime calls."""

    def __init__(self, session_factory: async_sessionmaker, *, ttl_seconds: float = 2.0) -> None:
        self._sessions = session_factory
        self._ttl_seconds = ttl_seconds
        self._cached: BusinessRuntimeConfiguration | None = None
        self._cached_at = 0.0
        self._lock = asyncio.Lock()

    async def load(self) -> BusinessRuntimeConfiguration:
        async with self._sessions() as session:
            active_id = await session.scalar(
                select(RuntimeState.active_release_id).where(RuntimeState.id == 1)
            )
        if not active_id:
            raise configuration_error()

        cached = self._cached
        if (
            cached is not None
            and cached.release_id == active_id
            and time.monotonic() - self._cached_at < self._ttl_seconds
        ):
            return BusinessRuntimeConfiguration.model_validate(cached.model_dump(mode="json"))

        async with self._lock:
            cached = self._cached
            if (
                cached is not None
                and cached.release_id == active_id
                and time.monotonic() - self._cached_at < self._ttl_seconds
            ):
                return BusinessRuntimeConfiguration.model_validate(cached.model_dump(mode="json"))
            try:
                async with self._sessions() as session:
                    data = await config_service.release_configuration(session, active_id)
                configuration = BusinessRuntimeConfiguration.from_release(data)
            except Exception:
                raise configuration_error() from None
            self._cached = configuration
            self._cached_at = time.monotonic()
            return BusinessRuntimeConfiguration.model_validate(
                configuration.model_dump(mode="json")
            )
