"""Create the production MySQL 8 schema for all phase-one records.

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-10-12
"""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


UTC_DATETIME = mysql.DATETIME(fsp=6)
JSON = mysql.JSON()
TABLE_OPTIONS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}


def _id() -> sa.Column:
    return sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True)


def _created_at() -> sa.Column:
    return sa.Column("created_at", UTC_DATETIME, nullable=False)


def upgrade() -> None:
    op.create_table(
        "config_draft",
        # This is a singleton row whose id is explicitly assigned as 1 by
        # bootstrap. MySQL does not allow a CHECK constraint to reference an
        # AUTO_INCREMENT column.
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("draft_json", JSON, nullable=False),
        sa.Column("updated_by", sa.String(length=128), nullable=False),
        sa.Column("updated_at", UTC_DATETIME, nullable=False),
        sa.CheckConstraint("id = 1", name="ck_config_draft_singleton"),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "model_config",
        _id(),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=256), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=False),
        sa.Column("params_json", JSON, nullable=False),
        sa.Column("timeout_seconds", sa.Float(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), nullable=False),
        sa.Column("structured_output_mode", sa.String(length=32), nullable=False),
        sa.Column("credential_ref", sa.String(length=255), nullable=False),
        sa.Column("model_config_hash", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("immutable_from_at", UTC_DATETIME, nullable=True),
        _created_at(),
        sa.UniqueConstraint("name", "version", name="uq_model_config_name_version"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_model_config_model_config_hash", "model_config", ["model_config_hash"])
    op.create_table(
        "config_release",
        _id(),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("snapshot_json", JSON, nullable=False),
        sa.Column("config_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("default_model_config_id", sa.BigInteger(), nullable=False),
        sa.Column("model_config_hash", sa.String(length=64), nullable=False),
        sa.Column("release_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["default_model_config_id"], ["model_config.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("version", name="uq_config_release_version"),
        sa.UniqueConstraint("release_fingerprint", name="uq_config_release_release_fingerprint"),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_config_release_config_snapshot_hash", "config_release", ["config_snapshot_hash"]
    )
    op.create_index(
        "ix_config_release_default_model_config_id", "config_release", ["default_model_config_id"]
    )
    op.create_table(
        "runtime_state",
        sa.Column("id", sa.SmallInteger(), primary_key=True, server_default=sa.text("1")),
        sa.Column("active_release_id", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", UTC_DATETIME, nullable=False),
        sa.CheckConstraint("id = 1", name="ck_runtime_state_singleton"),
        sa.ForeignKeyConstraint(["active_release_id"], ["config_release.id"], ondelete="SET NULL"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_runtime_state_active_release_id", "runtime_state", ["active_release_id"])
    op.create_table(
        "intent_request_trace",
        _id(),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("parent_trace_id", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("context_json", JSON, nullable=True),
        sa.Column("release_id", sa.BigInteger(), nullable=True),
        sa.Column("config_snapshot_hash", sa.String(length=64), nullable=True),
        sa.Column("release_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("effective_model_config_id", sa.BigInteger(), nullable=True),
        sa.Column("model_config_hash", sa.String(length=64), nullable=True),
        sa.Column("model_config_snapshot_json", JSON, nullable=True),
        sa.Column("final_route", sa.String(length=64), nullable=True),
        sa.Column("final_result_json", JSON, nullable=True),
        sa.Column("reason_summary", sa.Text(), nullable=True),
        sa.Column("evidence_json", JSON, nullable=True),
        sa.Column("validation_json", JSON, nullable=True),
        sa.Column("timeline_json", JSON, nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(["release_id"], ["config_release.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["effective_model_config_id"], ["model_config.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("trace_id", name="uq_intent_request_trace_trace_id"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_intent_request_trace_request_id", "intent_request_trace", ["request_id"])
    op.create_index(
        "ix_intent_request_trace_parent_trace_id", "intent_request_trace", ["parent_trace_id"]
    )
    op.create_index("ix_intent_request_trace_release_id", "intent_request_trace", ["release_id"])
    op.create_index(
        "ix_intent_request_trace_effective_model_config_id",
        "intent_request_trace",
        ["effective_model_config_id"],
    )
    op.create_index("ix_intent_request_trace_final_route", "intent_request_trace", ["final_route"])
    op.create_index("ix_intent_request_trace_status", "intent_request_trace", ["status"])
    op.create_index("ix_intent_request_trace_created_at", "intent_request_trace", ["created_at"])
    op.create_index(
        "ix_intent_request_trace_status_created_at",
        "intent_request_trace",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_intent_request_trace_release_id_created_at",
        "intent_request_trace",
        ["release_id", "created_at"],
    )
    op.create_index(
        "ix_intent_request_trace_model_config_created_at",
        "intent_request_trace",
        ["effective_model_config_id", "created_at"],
    )
    op.create_table(
        "llm_call_trace",
        _id(),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=256), nullable=False),
        sa.Column("model_params_json", JSON, nullable=True),
        sa.Column("final_prompt", sa.Text(), nullable=True),
        sa.Column("prompt_hash", sa.String(length=64), nullable=True),
        sa.Column("raw_request_json", JSON, nullable=True),
        sa.Column("raw_response_json", JSON, nullable=True),
        sa.Column(
            "final_prompt_truncated", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "raw_request_truncated", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "raw_response_truncated", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("provider_request_id", sa.String(length=255), nullable=True),
        sa.Column("provider_model_version", sa.String(length=255), nullable=True),
        sa.Column("system_fingerprint", sa.String(length=255), nullable=True),
        sa.Column("finish_reason", sa.String(length=128), nullable=True),
        sa.Column("parsed_result_json", JSON, nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["trace_id"], ["intent_request_trace.trace_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("trace_id", "attempt_no", name="uq_llm_call_trace_attempt"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_llm_call_trace_trace_id", "llm_call_trace", ["trace_id"])
    op.create_index("ix_llm_call_trace_status", "llm_call_trace", ["status"])
    op.create_index("ix_llm_call_trace_created_at", "llm_call_trace", ["created_at"])
    op.create_table(
        "evaluation_dataset",
        _id(),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("source_filename", sa.String(length=512), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column("normalized_cases_json", JSON, nullable=False),
        _created_at(),
        sa.UniqueConstraint("name", "version", name="uq_evaluation_dataset_name_version"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_evaluation_dataset_hash", "evaluation_dataset", ["hash"])
    op.create_table(
        "evaluation_run",
        _id(),
        sa.Column("dataset_id", sa.BigInteger(), nullable=False),
        sa.Column("dataset_hash", sa.String(length=64), nullable=False),
        sa.Column("release_id", sa.BigInteger(), nullable=True),
        sa.Column("config_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("release_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("effective_model_config_id", sa.BigInteger(), nullable=True),
        sa.Column("model_config_hash", sa.String(length=64), nullable=False),
        sa.Column("model_config_snapshot_json", JSON, nullable=False),
        sa.Column("repeat_count", sa.Integer(), nullable=False),
        sa.Column("worker_concurrency", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress_json", JSON, nullable=True),
        sa.Column("claimed_by", sa.String(length=128), nullable=True),
        sa.Column("heartbeat_at", UTC_DATETIME, nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        _created_at(),
        sa.Column("started_at", UTC_DATETIME, nullable=True),
        sa.Column("finished_at", UTC_DATETIME, nullable=True),
        sa.ForeignKeyConstraint(["dataset_id"], ["evaluation_dataset.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["release_id"], ["config_release.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["effective_model_config_id"], ["model_config.id"], ondelete="SET NULL"
        ),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_evaluation_run_dataset_id", "evaluation_run", ["dataset_id"])
    op.create_index("ix_evaluation_run_release_id", "evaluation_run", ["release_id"])
    op.create_index(
        "ix_evaluation_run_effective_model_config_id",
        "evaluation_run",
        ["effective_model_config_id"],
    )
    op.create_index("ix_evaluation_run_status", "evaluation_run", ["status"])
    op.create_index("ix_evaluation_run_claimed_by", "evaluation_run", ["claimed_by"])
    op.create_index("ix_evaluation_run_heartbeat_at", "evaluation_run", ["heartbeat_at"])
    op.create_index(
        "ix_evaluation_run_status_created_at", "evaluation_run", ["status", "created_at"]
    )
    op.create_index(
        "ix_evaluation_run_claim", "evaluation_run", ["status", "claimed_by", "heartbeat_at"]
    )
    op.create_table(
        "evaluation_case_result",
        _id(),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("case_id", sa.String(length=128), nullable=False),
        sa.Column("repeat_index", sa.Integer(), nullable=False),
        sa.Column("expected_json", JSON, nullable=False),
        sa.Column("actual_json", JSON, nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("error_type", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["evaluation_run.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "run_id", "case_id", "repeat_index", name="uq_evaluation_case_result_run_case_repeat"
        ),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_evaluation_case_result_run_id", "evaluation_case_result", ["run_id"])
    op.create_index(
        "ix_evaluation_case_result_request_id", "evaluation_case_result", ["request_id"]
    )
    op.create_index("ix_evaluation_case_result_trace_id", "evaluation_case_result", ["trace_id"])


def downgrade() -> None:
    op.drop_table("evaluation_case_result")
    op.drop_table("evaluation_run")
    op.drop_table("evaluation_dataset")
    op.drop_table("llm_call_trace")
    op.drop_table("intent_request_trace")
    op.drop_table("runtime_state")
    op.drop_table("config_release")
    op.drop_table("model_config")
    op.drop_table("config_draft")
