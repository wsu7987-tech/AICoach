"""Strict request contracts for the small internal diagnostic surface."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AdminRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DebugAnalyzeInput(AdminRequest):
    text: str = Field(min_length=1, max_length=2000)
    context: dict[str, Any] = Field(default_factory=dict)
    release_id: int | None = Field(default=None, gt=0)
    model_config_id: int | None = Field(default=None, gt=0)
    repeat: Literal[1, 3, 5] = 1


class ReplayInput(AdminRequest):
    mode: Literal["historical", "active"] = "historical"
    model_config_id: int | None = Field(default=None, gt=0)
    repeat: Literal[1, 3, 5] = 1


class DiffInput(AdminRequest):
    left_trace_id: str = Field(min_length=1, max_length=64)
    right_trace_id: str = Field(min_length=1, max_length=64)
