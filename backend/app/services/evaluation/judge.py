"""Optional model review, using the existing bounded-retry Provider transport."""

import json

from app.providers.openai_compatible import OpenAICompatibleProvider
from app.schemas.evaluation import JudgeVerdict
from app.schemas.intent import PromptBuildResult, PromptMessage, sha256_canonical


class JudgeProvider(OpenAICompatibleProvider):
    def _response_format(self, prompt):
        if self.runtime_snapshot.structured_output_mode == "json_object":
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "EvaluationJudgement",
                "strict": True,
                "schema": JudgeVerdict.model_json_schema(),
            },
        }


class JudgeResponseError(ValueError):
    def __init__(self, attempts):
        super().__init__("评审结果格式无效")
        self.attempts = attempts


async def judge_result(
    provider: JudgeProvider, *, system_prompt: str, case: dict, actual: dict, vocabulary: dict
):
    payload = {
        "question": case["question"],
        "context": case.get("context", {}),
        "standard_answer": case["standard_answer"],
        "actual": actual,
        "vocabulary": vocabulary,
    }
    messages = [
        PromptMessage(role="system", content=system_prompt),
        PromptMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
    ]
    rendered = json.dumps([message.model_dump() for message in messages], ensure_ascii=False)
    response = await provider.invoke(
        PromptBuildResult(
            messages=messages,
            final_prompt=rendered,
            prompt_hash=sha256_canonical(rendered),
            metadata={},
        )
    )
    try:
        verdict = JudgeVerdict.model_validate_json(response.content)
    except ValueError:
        raise JudgeResponseError(response.attempts) from None
    return {
        **verdict.model_dump(),
        "attempts": [attempt.model_dump(mode="json") for attempt in response.attempts],
    }
