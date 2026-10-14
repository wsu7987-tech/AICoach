from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


def normalized_base_url(value: str) -> str:
    candidate = value.strip().rstrip("/")
    parsed = urlsplit(candidate)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("请输入不包含账号、查询参数或片段的 HTTP(S) API 地址")
    # Scheme and host are case-insensitive. Preserve path case because gateways may
    # route it case-sensitively. Open WebUI likewise removes the trailing slash.
    hostname = parsed.hostname.lower()
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    parsed_port = parsed.port
    is_default_port = (parsed.scheme == "http" and parsed_port == 80) or (
        parsed.scheme == "https" and parsed_port == 443
    )
    port = f":{parsed_port}" if parsed_port is not None and not is_default_port else ""
    return urlunsplit((parsed.scheme.lower(), f"{hostname}{port}", parsed.path, "", ""))


class ManagedModelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=128, pattern=r"\S")
    base_url: str = Field(min_length=1, max_length=2048)
    api_key: SecretStr = Field(min_length=1, max_length=4096)
    model_name: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9._:/-]+$")
    temperature: float | None = Field(default=0.1, ge=0, le=2)
    top_p: float | None = Field(default=0.8, gt=0, le=1)
    timeout_seconds: float = Field(default=30, gt=0, le=600)
    max_retries: int = Field(default=1, ge=0, le=5)
    max_concurrency: int = Field(default=4, gt=0, le=256)

    @field_validator("base_url")
    @classmethod
    def normalize_endpoint(cls, value: str) -> str:
        return normalized_base_url(value)

    @field_validator("display_name", "model_name")
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()


class ManagedModelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"\S")
    api_key: SecretStr | None = Field(default=None, min_length=1, max_length=4096)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    clear_temperature: bool = False
    clear_top_p: bool = False
    timeout_seconds: float | None = Field(default=None, gt=0, le=600)
    max_retries: int | None = Field(default=None, ge=0, le=5)
    max_concurrency: int | None = Field(default=None, gt=0, le=256)

    @field_validator("display_name")
    @classmethod
    def trim_display_name(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def contains_a_change(self) -> ManagedModelUpdate:
        values = self.model_dump(exclude_none=True)
        if not values or values == {"clear_temperature": False, "clear_top_p": False}:
            raise ValueError("至少提供一个需要修改的字段")
        if self.temperature is not None and self.clear_temperature:
            raise ValueError("temperature 不能同时设置和清空")
        if self.top_p is not None and self.clear_top_p:
            raise ValueError("top_p 不能同时设置和清空")
        return self


class ConnectionVerifyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(min_length=1, max_length=2048)
    api_key: SecretStr = Field(min_length=1, max_length=4096)
    timeout_seconds: float = Field(default=15, gt=0, le=60)

    @field_validator("base_url")
    @classmethod
    def normalize_endpoint(cls, value: str) -> str:
        return normalized_base_url(value)


class ExistingConnectionVerifyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: SecretStr | None = Field(default=None, min_length=1, max_length=4096)


class ConnectionVerifyResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    connected: Literal[True]
    model_discovery_supported: bool
    models: list[str]
    message: str


class ManagedModelView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    id: int
    model_uid: str
    display_name: str
    model_name: str
    base_url: str
    temperature: float | None
    top_p: float | None
    timeout_seconds: float
    max_retries: int
    max_concurrency: int
    enabled: bool
    credential_configured: bool
    credential_hint: str | None
    last_verified_at: datetime | None
    is_default: bool
    created_at: datetime
    updated_at: datetime


class ManagedModelList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    default_model_uid: str | None
    items: list[ManagedModelView]
