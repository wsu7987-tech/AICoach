"""Resolve the ManagedModel selected for one Runtime request.

The decrypted credential is carried only in the short-lived in-memory
``ResolvedManagedModel`` object.  Its repr is redacted and only the secret-free
snapshot may cross into Trace persistence.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.errors import ErrorCode
from app.db.models import ManagedModel, ProviderCredential, RuntimeModelState
from app.providers.openai_compatible import ProviderError
from app.schemas.managed_model import ManagedModelRuntimeSnapshot
from app.security.credentials import CredentialCipher
from app.services.managed_model_service import decrypt_model_credential


@dataclass(frozen=True, slots=True)
class ResolvedManagedModel:
    snapshot: ManagedModelRuntimeSnapshot
    api_key: str = field(repr=False)
    credential_revision: str = field(repr=False)


def _runtime_model_error(
    code: ErrorCode,
    message: str,
    status_code: int,
    *,
    failure_stage: str = "configuration",
) -> ProviderError:
    return ProviderError(
        code,
        message,
        status_code,
        attempts=[],
        failure_stage=failure_stage,
    )


class DatabaseManagedModelLoader:
    """Load an explicit model_uid or the singleton Runtime default model."""

    def __init__(
        self,
        session_factory: async_sessionmaker,
        cipher: CredentialCipher,
    ) -> None:
        self._sessions = session_factory
        self._cipher = cipher

    async def load(self, model_uid: str | None) -> ResolvedManagedModel:
        async with self._sessions() as session:
            if model_uid is not None:
                row = await session.scalar(
                    select(ManagedModel).where(ManagedModel.model_uid == model_uid)
                )
                if row is None:
                    raise _runtime_model_error(
                        ErrorCode.INVALID_INPUT,
                        "requested model_uid does not exist",
                        422,
                    )
                if not row.enabled:
                    raise _runtime_model_error(
                        ErrorCode.INVALID_INPUT,
                        "requested model_uid is disabled",
                        422,
                    )
            else:
                state = await session.get(RuntimeModelState, 1)
                row = (
                    await session.get(ManagedModel, state.default_model_id)
                    if state is not None and state.default_model_id is not None
                    else None
                )
                if row is None or not row.enabled:
                    raise _runtime_model_error(
                        ErrorCode.CONFIG_NOT_READY,
                        "default runtime model is not configured",
                        503,
                    )

            credential = await session.get(ProviderCredential, row.credential_id)
            try:
                if credential is None:
                    raise ValueError("missing credential")
                api_key = decrypt_model_credential(self._cipher, credential)
                revision_source = (
                    f"{credential.credential_uid}:"
                    f"{credential.updated_at.isoformat(timespec='microseconds')}"
                )
            except Exception:
                # Credential exception text can contain deployment details. The
                # public and Trace-facing error stays intentionally generic.
                raise _runtime_model_error(
                    ErrorCode.CONFIG_NOT_READY,
                    "runtime model credential is unavailable",
                    503,
                    failure_stage="credential",
                ) from None
            if not api_key:
                raise _runtime_model_error(
                    ErrorCode.CONFIG_NOT_READY,
                    "runtime model credential is unavailable",
                    503,
                    failure_stage="credential",
                )

            try:
                snapshot = ManagedModelRuntimeSnapshot(
                    id=row.id,
                    model_uid=row.model_uid,
                    display_name=row.display_name,
                    provider=row.provider,
                    model_name=row.model_name,
                    base_url=row.base_url,
                    params_json=dict(row.params_json),
                    timeout_seconds=row.timeout_seconds,
                    max_retries=row.max_retries,
                    max_concurrency=row.max_concurrency,
                    enabled=row.enabled,
                )
            except ValueError:
                raise _runtime_model_error(
                    ErrorCode.CONFIG_NOT_READY,
                    "runtime model configuration is invalid",
                    503,
                ) from None
            revision = hashlib.sha256(revision_source.encode()).hexdigest()
            return ResolvedManagedModel(
                snapshot=snapshot,
                api_key=api_key,
                credential_revision=revision,
            )
