from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import openai
from openai import AsyncOpenAI
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ManagedModel, ProviderCredential, RuntimeModelState
from app.schemas.intent import LLMRecognitionOutputV2
from app.schemas.managed_model import (
    ConnectionVerifyResult,
    ManagedModelCreate,
    ManagedModelUpdate,
    ManagedModelView,
)
from app.security.credentials import (
    CredentialCipher,
    CredentialConfigurationError,
    CredentialDecryptionError,
    secret_hint,
)
from app.services.config_service import ConfigError


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def make_model_uid(base_url: str, model_name: str) -> str:
    digest = hashlib.sha256(f"{base_url}\n{model_name}".encode()).hexdigest()
    return f"mdl_{digest}"


def _params(temperature: float | None, top_p: float | None) -> dict[str, float]:
    result: dict[str, float] = {}
    if temperature is not None:
        result["temperature"] = temperature
    if top_p is not None:
        result["top_p"] = top_p
    return result


def _view(
    row: ManagedModel,
    credential: ProviderCredential | None,
    default_model_id: int | None,
) -> ManagedModelView:
    return ManagedModelView(
        id=row.id,
        model_uid=row.model_uid,
        display_name=row.display_name,
        model_name=row.model_name,
        base_url=row.base_url,
        temperature=row.params_json.get("temperature"),
        top_p=row.params_json.get("top_p"),
        timeout_seconds=row.timeout_seconds,
        max_retries=row.max_retries,
        max_concurrency=row.max_concurrency,
        enabled=row.enabled,
        credential_configured=credential is not None or bool(row.credential_ref),
        credential_hint=credential.secret_hint if credential is not None else None,
        last_verified_at=credential.last_verified_at if credential is not None else None,
        is_default=row.id == default_model_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _get_row(session: AsyncSession, model_uid: str, *, lock: bool = False) -> ManagedModel:
    query = select(ManagedModel).where(ManagedModel.model_uid == model_uid)
    if lock:
        query = query.with_for_update()
    row = await session.scalar(query)
    if row is None:
        raise ConfigError("MODEL_NOT_FOUND", "模型不存在", 404)
    return row


async def _credential(session: AsyncSession, row: ManagedModel) -> ProviderCredential | None:
    return await session.get(ProviderCredential, row.credential_id) if row.credential_id else None


async def list_models(session: AsyncSession) -> dict[str, object]:
    rows = list(
        await session.scalars(select(ManagedModel).order_by(ManagedModel.created_at.desc()))
    )
    state = await session.get(RuntimeModelState, 1)
    default_id = state.default_model_id if state else None
    credentials: dict[int, ProviderCredential] = {}
    credential_ids = [row.credential_id for row in rows if row.credential_id is not None]
    if credential_ids:
        credential_rows = await session.scalars(
            select(ProviderCredential).where(ProviderCredential.id.in_(credential_ids))
        )
        credentials = {item.id: item for item in credential_rows}
    default_uid = next((row.model_uid for row in rows if row.id == default_id), None)
    return {
        "default_model_uid": default_uid,
        "items": [_view(row, credentials.get(row.credential_id), default_id) for row in rows],
    }


async def get_model(session: AsyncSession, model_uid: str) -> ManagedModelView:
    row = await _get_row(session, model_uid)
    state = await session.get(RuntimeModelState, 1)
    return _view(row, await _credential(session, row), state.default_model_id if state else None)


def _encrypt(cipher: CredentialCipher, api_key: str) -> str:
    try:
        return cipher.encrypt(api_key)
    except CredentialConfigurationError as exc:
        raise ConfigError(
            "CREDENTIAL_STORE_NOT_READY",
            "凭据加密尚未配置，请设置 CREDENTIAL_ENCRYPTION_KEY",
            503,
        ) from exc


async def create_model(
    session: AsyncSession, body: ManagedModelCreate, cipher: CredentialCipher
) -> ManagedModelView:
    model_uid = make_model_uid(body.base_url, body.model_name)
    if await session.scalar(select(ManagedModel.id).where(ManagedModel.model_uid == model_uid)):
        raise ConfigError("MODEL_ALREADY_EXISTS", "相同调用地址和模型名称的模型已存在", 409)

    api_key = body.api_key.get_secret_value()
    credential = ProviderCredential(
        credential_uid=f"cred_{uuid4().hex}",
        encrypted_secret=_encrypt(cipher, api_key),
        secret_hint=secret_hint(api_key),
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    session.add(credential)
    await session.flush()
    row = ManagedModel(
        model_uid=model_uid,
        display_name=body.display_name,
        # This is the internal transport adapter, not a user-selected vendor.
        provider="openai_compatible",
        model_name=body.model_name,
        base_url=body.base_url,
        credential_id=credential.id,
        credential_ref=None,
        params_json=_params(body.temperature, body.top_p),
        timeout_seconds=body.timeout_seconds,
        max_retries=body.max_retries,
        max_concurrency=body.max_concurrency,
        enabled=True,
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConfigError(
            "MODEL_ALREADY_EXISTS", "相同调用地址和模型名称的模型已存在", 409
        ) from exc
    state = await session.get(RuntimeModelState, 1, with_for_update=True)
    if state is None:
        state = RuntimeModelState(id=1, default_model_id=row.id, updated_at=_utc_now())
        session.add(state)
    elif state.default_model_id is None:
        state.default_model_id = row.id
        state.updated_at = _utc_now()
    return _view(row, credential, state.default_model_id)


async def update_model(
    session: AsyncSession,
    model_uid: str,
    body: ManagedModelUpdate,
    cipher: CredentialCipher,
) -> ManagedModelView:
    row = await _get_row(session, model_uid, lock=True)
    credential = await _credential(session, row)
    if body.display_name is not None:
        row.display_name = body.display_name
    params = dict(row.params_json)
    if body.clear_temperature:
        params.pop("temperature", None)
    elif body.temperature is not None:
        params["temperature"] = body.temperature
    if body.clear_top_p:
        params.pop("top_p", None)
    elif body.top_p is not None:
        params["top_p"] = body.top_p
    row.params_json = params
    if body.timeout_seconds is not None:
        row.timeout_seconds = body.timeout_seconds
    if body.max_retries is not None:
        row.max_retries = body.max_retries
    if body.max_concurrency is not None:
        row.max_concurrency = body.max_concurrency
    if body.api_key is not None:
        if credential is None:
            raise ConfigError("CREDENTIAL_NOT_FOUND", "模型凭据不存在", 409)
        api_key = body.api_key.get_secret_value()
        credential.encrypted_secret = _encrypt(cipher, api_key)
        credential.secret_hint = secret_hint(api_key)
        credential.last_verified_at = None
        credential.updated_at = _utc_now()
    row.updated_at = _utc_now()
    await session.flush()
    state = await session.get(RuntimeModelState, 1)
    return _view(row, credential, state.default_model_id if state else None)


async def set_default(session: AsyncSession, model_uid: str) -> ManagedModelView:
    row = await _get_row(session, model_uid, lock=True)
    if not row.enabled:
        raise ConfigError("MODEL_DISABLED", "禁用的模型不能设为默认模型", 409)
    state = await session.get(RuntimeModelState, 1, with_for_update=True)
    if state is None:
        state = RuntimeModelState(id=1, default_model_id=row.id, updated_at=_utc_now())
        session.add(state)
    else:
        state.default_model_id = row.id
        state.updated_at = _utc_now()
    await session.flush()
    return _view(row, await _credential(session, row), row.id)


async def set_enabled(session: AsyncSession, model_uid: str, *, enabled: bool) -> ManagedModelView:
    row = await _get_row(session, model_uid, lock=True)
    state = await session.get(RuntimeModelState, 1, with_for_update=True)
    if not enabled and state is not None and state.default_model_id == row.id:
        raise ConfigError("DEFAULT_MODEL_DISABLE_FORBIDDEN", "请先设置其他默认模型再禁用", 409)
    row.enabled = enabled
    row.updated_at = _utc_now()
    await session.flush()
    return _view(row, await _credential(session, row), state.default_model_id if state else None)


def decrypt_model_credential(cipher: CredentialCipher, credential: ProviderCredential) -> str:
    try:
        return cipher.decrypt(credential.encrypted_secret)
    except CredentialConfigurationError as exc:
        raise ConfigError("CREDENTIAL_STORE_NOT_READY", "凭据加密尚未配置", 503) from exc
    except CredentialDecryptionError as exc:
        raise ConfigError("CREDENTIAL_DECRYPT_FAILED", "模型凭据无法解密", 503) from exc


async def verify_connection(
    base_url: str,
    api_key: str,
    timeout_seconds: float,
    *,
    model_name: str | None = None,
    temperature: float | None = 0.1,
    top_p: float | None = 0.8,
) -> ConnectionVerifyResult:
    http_client = httpx.AsyncClient(trust_env=False)
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout_seconds,
        max_retries=0,
        http_client=http_client,
    )
    models: list[str] = []
    discovery_supported = True
    try:
        try:
            page = await client.models.list()
            models = sorted({item.id for item in page.data if item.id})
        except openai.APIStatusError as exc:
            if exc.status_code not in {404, 405}:
                raise
            discovery_supported = False

        if model_name is None:
            message = (
                "连接成功，请选择模型后再次验证模型调用"
                if discovery_supported
                else "已连接，但服务不支持获取模型列表；填写模型名称后需再次验证"
            )
            return ConnectionVerifyResult(
                connected=True,
                model_verified=False,
                verified_model_name=None,
                model_discovery_supported=discovery_supported,
                models=models,
                message=message,
            )

        expected = {
            "schema_version": 2,
            "is_compound": False,
            "composition": "single",
            "actions": [
                {
                    "action_id": "action_1",
                    "source_text": "connection verification",
                    "route": "unknown",
                    "intent": None,
                    "slots": [],
                    "order": 1,
                    "depends_on": [],
                }
            ],
            "risk": None,
            "need_clarification": False,
            "clarification": None,
            "reason_summary": "connection verification",
            "evidence": [],
        }
        params: dict[str, float] = {}
        if temperature is not None:
            params["temperature"] = temperature
        if top_p is not None:
            params["top_p"] = top_p
        completion = await client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Return exactly one JSON object and no explanation. "
                        "Copy the object supplied by the user without changing field names."
                    ),
                },
                {"role": "user", "content": json.dumps(expected, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
            **params,
        )
        content = completion.choices[0].message.content or ""
        try:
            LLMRecognitionOutputV2.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValidationError, TypeError):
            raise ConfigError(
                "MODEL_OUTPUT_FORMAT_UNSUPPORTED",
                "模型可以调用，但不能稳定返回意图识别所需的 JSON 字段格式",
                422,
            ) from None

        return ConnectionVerifyResult(
            connected=True,
            model_verified=True,
            verified_model_name=model_name,
            model_discovery_supported=discovery_supported,
            models=models,
            message="连接及模型调用验证成功",
        )
    except ConfigError:
        raise
    except openai.AuthenticationError as exc:
        raise ConfigError("PROVIDER_AUTH_FAILED", "认证失败，请检查 API Key", 401) from exc
    except openai.APITimeoutError as exc:
        raise ConfigError("PROVIDER_TIMEOUT", "模型服务响应超时", 504) from exc
    except openai.APIConnectionError as exc:
        raise ConfigError("PROVIDER_CONNECTION_FAILED", "无法连接模型服务", 502) from exc
    except openai.RateLimitError as exc:
        raise ConfigError("PROVIDER_RATE_LIMIT", "模型服务请求过于频繁，请稍后重试", 429) from exc
    except openai.APIStatusError as exc:
        body = exc.body if isinstance(exc.body, dict) else {}
        if exc.status_code == 404 or body.get("code") == "model_not_found":
            raise ConfigError(
                "MODEL_NOT_FOUND",
                f"模型名称 {model_name or ''} 不存在或当前 API Key 无权调用",
                422,
            ) from exc
        if exc.status_code >= 500:
            raise ConfigError("PROVIDER_SERVER_ERROR", "模型服务暂时不可用", 502) from exc
        raise ConfigError(
            "PROVIDER_VERIFY_FAILED",
            f"模型服务拒绝了模型调用验证（HTTP {exc.status_code}）",
            400,
        ) from exc
    finally:
        await client.close()


async def verify_existing(
    session: AsyncSession,
    model_uid: str,
    cipher: CredentialCipher,
    replacement_api_key: str | None,
) -> ConnectionVerifyResult:
    row = await _get_row(session, model_uid)
    credential = await _credential(session, row)
    if replacement_api_key is not None:
        api_key = replacement_api_key
    elif credential is not None:
        api_key = decrypt_model_credential(cipher, credential)
    elif row.credential_ref:
        raise ConfigError(
            "LEGACY_CREDENTIAL_REQUIRES_RUNTIME",
            "旧环境凭据请在运行环境中验证",
            409,
        )
    else:
        raise ConfigError("CREDENTIAL_NOT_FOUND", "模型尚未配置 API Key", 409)
    result = await verify_connection(
        row.base_url,
        api_key,
        min(row.timeout_seconds, 60),
        model_name=row.model_name,
        temperature=row.params_json.get("temperature"),
        top_p=row.params_json.get("top_p"),
    )
    if result.model_verified and credential is not None and replacement_api_key is None:
        credential.last_verified_at = _utc_now()
        credential.updated_at = _utc_now()
    return result
