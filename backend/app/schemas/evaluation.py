"""Evaluation inputs: natural-language gold answers plus optional exact assertions."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ExpectedSlot(EvaluationModel):
    name: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1, max_length=2000)


class ExpectedAction(EvaluationModel):
    route: str = Field(min_length=1, max_length=64)
    intent: str | None = Field(default=None, max_length=128)
    slots: list[ExpectedSlot] | None = Field(default=None, max_length=50)
    depends_on: list[int] | None = Field(default=None, max_length=12)


class ExpectedRisk(EvaluationModel):
    type: str = Field(min_length=1, max_length=128)
    level: Literal["low", "medium", "high"]


class ExpectedAnswer(EvaluationModel):
    actions: list[ExpectedAction] | None = Field(default=None, min_length=1, max_length=12)
    composition: Literal["single", "parallel", "sequential", "alternative"] | None = None
    risk: ExpectedRisk | None = None
    need_clarification: bool | None = None

    @model_validator(mode="after")
    def validate_dependencies(self):
        if self.actions:
            if sum(len(action.slots or []) for action in self.actions) > 50:
                raise ValueError("每个用例最多填写 50 个期望参数")
            for index, action in enumerate(self.actions, 1):
                if action.depends_on is not None:
                    if len(set(action.depends_on)) != len(action.depends_on) or any(
                        dependency < 1 or dependency >= index for dependency in action.depends_on
                    ):
                        raise ValueError(f"动作 {index} 的依赖必须是不重复的前置动作编号")
                    if (
                        self.composition in {"single", "parallel", "alternative"}
                        and action.depends_on
                    ):
                        raise ValueError("单动作、并行、备选组合不能填写动作依赖")
            if self.composition == "single" and len(self.actions) != 1:
                raise ValueError("单动作组合只能有一个期望动作")
            if (
                self.composition in {"parallel", "sequential", "alternative"}
                and len(self.actions) < 2
            ):
                raise ValueError("复合组合至少需要两个期望动作")
            if self.composition == "sequential" and any(
                action.depends_on == [] for action in self.actions[1:]
            ):
                raise ValueError("顺序动作填写依赖时，后续动作不能明确要求无依赖")
        if self.composition == "alternative" and self.need_clarification is False:
            raise ValueError("备选动作需要追问，不能同时要求不得追问")
        return self


class EvaluationCase(EvaluationModel):
    case_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=2000)
    standard_answer: str = Field(min_length=1, max_length=10000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    context: dict[str, Any] = Field(default_factory=dict)
    expected: ExpectedAnswer | None = None
    critical: bool = False

    @model_validator(mode="after")
    def bounded_fields(self):
        import json

        if any(not tag or len(tag) > 64 for tag in self.tags):
            raise ValueError("场景标签不能为空且不能超过 64 字")
        self.tags = list(dict.fromkeys(self.tags))
        if len(json.dumps(self.context, ensure_ascii=False, allow_nan=False).encode()) > 16384:
            raise ValueError("上下文不能超过 16 KB")
        return self


class DatasetCreate(EvaluationModel):
    name: str = Field(min_length=1, max_length=128)
    cases: list[EvaluationCase] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_cases(self):
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("用例编号不能重复")
        return self


class RunCreate(EvaluationModel):
    name: str = Field(min_length=1, max_length=128)
    dataset_id: int = Field(gt=0)
    release_id: int | None = Field(default=None, gt=0)
    model_uid: str | None = None
    judge_model_uid: str | None = None
    repeat_count: Literal[1, 3, 5] = 1
    worker_concurrency: int = Field(default=2, ge=1, le=8)
    pass_threshold: float = Field(default=100, ge=0, le=100)
    parent_run_id: int | None = Field(default=None, gt=0)
    case_ids: list[str] | None = Field(default=None, min_length=1, max_length=500)


class ReviewInput(EvaluationModel):
    decision: Literal["pass", "fail"]
    reason: str = Field(min_length=1, max_length=2000)
    reviewer: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=0)


class JudgeVerdict(EvaluationModel):
    verdict: Literal["pass", "fail", "review"]
    reason: str = Field(min_length=1, max_length=2000)
    tags: list[
        Literal[
            "action_missing",
            "action_extra",
            "route",
            "intent",
            "slot",
            "dependency",
            "composition",
            "risk",
            "clarification",
            "ambiguous_standard",
            "other",
        ]
    ] = Field(max_length=12)
