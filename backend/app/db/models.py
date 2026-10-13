from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Double,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
    text,
)
from sqlalchemy.dialects.mysql import DATETIME as DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ConfigDraft(Base):
    __tablename__ = "config_draft"
    __table_args__ = (CheckConstraint("id = 1", name="ck_config_draft_singleton"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    draft_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(fsp=6), nullable=False, default=_utc_now)


class ModelConfig(Base):
    __tablename__ = "model_config"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_model_config_name_version"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(256), nullable=False)
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    params_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    timeout_seconds: Mapped[float] = mapped_column(Double, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False)
    max_concurrency: Mapped[int] = mapped_column(Integer, nullable=False)
    structured_output_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    credential_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    model_config_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    immutable_from_at: Mapped[datetime | None] = mapped_column(DateTime(fsp=6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(fsp=6), nullable=False, default=_utc_now)


class ConfigRelease(Base):
    __tablename__ = "config_release"
    __table_args__ = (UniqueConstraint("version", name="uq_config_release_version"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    config_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    default_model_config_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("model_config.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    model_config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    release_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(fsp=6), nullable=False, default=_utc_now)


@event.listens_for(ConfigRelease, "before_update")
@event.listens_for(ConfigRelease, "before_delete")
def reject_release_mutation(mapper, connection, target):
    raise ValueError("historical release is immutable")


@event.listens_for(ModelConfig, "before_update")
def reject_model_parameter_mutation(mapper, connection, target):
    # All versions are append-only from creation, even before their first use.
    # Lifecycle flags remain mutable; the service guards active-release disable.
    state = inspect(target)
    for attribute in state.mapper.column_attrs:
        if attribute.key not in {"enabled", "immutable_from_at"}:
            if state.attrs[attribute.key].history.has_changes():
                raise ValueError("model config parameters are immutable; create a new version")


@event.listens_for(ModelConfig, "before_delete")
def reject_model_deletion(mapper, connection, target):
    raise ValueError("model config is immutable; disable instead")


class RuntimeState(Base):
    __tablename__ = "runtime_state"
    __table_args__ = (CheckConstraint("id = 1", name="ck_runtime_state_singleton"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default=text("1"))
    active_release_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("config_release.id", ondelete="SET NULL"), nullable=True, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(fsp=6), nullable=False, default=_utc_now)


class IntentRequestTrace(Base):
    __tablename__ = "intent_request_trace"
    __table_args__ = (
        Index("ix_intent_request_trace_status_created_at", "status", "created_at"),
        Index("ix_intent_request_trace_release_id_created_at", "release_id", "created_at"),
        Index(
            "ix_intent_request_trace_model_config_created_at",
            "effective_model_config_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    parent_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    input: Mapped[str] = mapped_column(Text, nullable=False)
    context_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    release_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("config_release.id", ondelete="SET NULL"), nullable=True, index=True
    )
    config_snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    release_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    effective_model_config_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("model_config.id", ondelete="SET NULL"), nullable=True, index=True
    )
    model_config_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_config_snapshot_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON, nullable=True
    )
    final_route: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    final_result_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    reason_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    validation_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    timeline_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(fsp=6), nullable=False, default=_utc_now, index=True
    )


class LLMCallTrace(Base):
    __tablename__ = "llm_call_trace"
    __table_args__ = (UniqueConstraint("trace_id", "attempt_no", name="uq_llm_call_trace_attempt"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("intent_request_trace.trace_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(256), nullable=False)
    model_params_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    final_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_request_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    raw_response_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    final_prompt_truncated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )
    raw_request_truncated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )
    raw_response_truncated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_model_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    system_fingerprint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parsed_result_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(fsp=6), nullable=False, default=_utc_now, index=True
    )


class EvaluationDataset(Base):
    __tablename__ = "evaluation_dataset"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_evaluation_dataset_name_version"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    normalized_cases_json: Mapped[list[object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(fsp=6), nullable=False, default=_utc_now)


class EvaluationRun(Base):
    __tablename__ = "evaluation_run"
    __table_args__ = (
        Index("ix_evaluation_run_claim", "status", "claimed_by", "heartbeat_at"),
        Index("ix_evaluation_run_status_created_at", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("evaluation_dataset.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    dataset_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    release_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("config_release.id", ondelete="SET NULL"), nullable=True, index=True
    )
    config_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    release_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_model_config_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("model_config.id", ondelete="SET NULL"), nullable=True, index=True
    )
    model_config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model_config_snapshot_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    repeat_count: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_concurrency: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    progress_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(fsp=6), nullable=True, index=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(fsp=6), nullable=False, default=_utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(fsp=6), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(fsp=6), nullable=True)


class EvaluationCaseResult(Base):
    __tablename__ = "evaluation_case_result"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "case_id", "repeat_index", name="uq_evaluation_case_result_run_case_repeat"
        ),
        Index("ix_evaluation_case_result_trace_id", "trace_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("evaluation_run.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[str] = mapped_column(String(128), nullable=False)
    repeat_index: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    actual_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    # Deliberately no FK: trace retention must not delete results or be blocked by them.
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
