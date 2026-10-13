"""Database-backed immutable configuration loading for Runtime executions."""

from __future__ import annotations

import asyncio
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import RuntimeState
from app.providers.factory import configuration_error
from app.services import config_service
from app.services.intent_service import RuntimeConfiguration


class DatabaseRuntimeConfigLoader:
    """A small TTL cache which checks the database active id on every load.

    The active-id read makes a newly activated Release visible immediately while
    the TTL limits the heavier Release + Model snapshot validation query.
    """

    def __init__(self, session_factory: async_sessionmaker, *, ttl_seconds: float = 2.0) -> None:
        self._sessions = session_factory
        self._ttl_seconds = ttl_seconds
        self._cached: RuntimeConfiguration | None = None
        self._cached_at = 0.0
        self._lock = asyncio.Lock()

    async def load(self) -> RuntimeConfiguration:
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
            return RuntimeConfiguration.model_validate(cached.model_dump(mode="json"))

        async with self._lock:
            cached = self._cached
            if (
                cached is not None
                and cached.release_id == active_id
                and time.monotonic() - self._cached_at < self._ttl_seconds
            ):
                return RuntimeConfiguration.model_validate(cached.model_dump(mode="json"))
            try:
                async with self._sessions() as session:
                    data = await config_service.release_configuration(session, active_id)
                configuration = RuntimeConfiguration.from_release(data)
                if not configuration.model_config_snapshot.enabled:
                    raise ValueError("active model is disabled")
            except Exception:
                # A runtime caller sees only fail-closed CONFIG_NOT_READY; hash and
                # row details remain available to the internal Admin path instead.
                raise configuration_error() from None
            self._cached = configuration
            self._cached_at = time.monotonic()
            return RuntimeConfiguration.model_validate(configuration.model_dump(mode="json"))
