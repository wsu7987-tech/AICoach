"""Deterministic, configuration-driven plain-text prompt construction."""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from app.schemas.intent import (
    LLMRecognitionOutput,
    LLMRecognitionOutputV2,
    PromptBuildResult,
    PromptMessage,
    RuntimeConfigSnapshot,
    SlotValue,
    canonical_json,
    validate_runtime_config_snapshot,
)


class PromptBuilder:
    """Build the exact plain-text messages sent through ``LLMProvider``."""

    def build(
        self,
        snapshot: RuntimeConfigSnapshot | dict[str, Any],
        text: str,
        context: dict[str, Any] | None = None,
        *,
        output_version: Literal[1, 2] = 1,
        pre_extracted_slots: list[SlotValue] | None = None,
    ) -> PromptBuildResult:
        config = validate_runtime_config_snapshot(snapshot)
        output_model = (
            LLMRecognitionOutputV2
            if output_version == 2
            else LLMRecognitionOutput
        )
        business_modules = [
            _render_routes(config),
            _render_intents(config),
            _render_slots(config),
        ]
        system_sections = [config.prompt_template.system.strip()]
        prompt_rules = [
            rule.strip()
            for rule in config.prompt_template.rules
            if not rule.strip().lower().startswith("slot start/end ")
        ]
        if prompt_rules:
            rules = "\n".join(f"- {rule}" for rule in prompt_rules)
            system_sections.append(f"## 识别规则\n\n{rules}")
        system_sections.extend(module for module in business_modules if module)
        extracted_module = _render_pre_extracted_slots(
            text, pre_extracted_slots or []
        )
        if extracted_module:
            system_sections.append(extracted_module)
        system_sections.append(_render_output_contract(output_version))
        system_content = "\n\n".join(system_sections)

        user_sections: list[str] = []
        if context:
            user_sections.append(f"## 上下文\n\n{_render_context(context)}")
        user_sections.append(f"## 用户输入\n\n{text}")
        user_content = "\n\n".join(user_sections)

        messages = [
            PromptMessage(role="system", content=system_content),
            PromptMessage(role="user", content=user_content),
        ]
        final_prompt = f"[SYSTEM]\n{system_content}\n\n[USER]\n{user_content}"
        prompt_hash = hashlib.sha256(final_prompt.encode("utf-8")).hexdigest()
        enum_matcher_text = _render_all_enum_matchers(config)
        effective_text = "\n\n".join([*business_modules, enum_matcher_text])
        return PromptBuildResult(
            messages=messages,
            final_prompt=final_prompt,
            prompt_hash=prompt_hash,
            metadata={
                "schema_version": config.schema_version,
                "config_snapshot_hash": config.canonical_hash(),
                "effective_config_hash": hashlib.sha256(
                    effective_text.encode("utf-8")
                ).hexdigest(),
                "enum_matcher_hash": hashlib.sha256(
                    enum_matcher_text.encode("utf-8")
                ).hexdigest(),
                "output_schema_name": output_model.__name__,
            },
        )

    def preview(
        self,
        snapshot: RuntimeConfigSnapshot | dict[str, Any],
        text: str,
        context: dict[str, Any] | None = None,
        *,
        pre_extracted_slots: list[SlotValue] | None = None,
    ) -> PromptBuildResult:
        """Return the same prompt as runtime without calling a model."""

        return self.build(
            snapshot,
            text=text,
            context=context,
            pre_extracted_slots=pre_extracted_slots,
        )

    def preview_routes(self, snapshot: RuntimeConfigSnapshot | dict[str, Any]) -> str:
        """Return only the Route module used by the runtime prompt."""

        return _render_routes(validate_runtime_config_snapshot(snapshot))

    def preview_intents(self, snapshot: RuntimeConfigSnapshot | dict[str, Any]) -> str:
        """Return the complete Intent module used by the runtime prompt."""

        return _render_intents(validate_runtime_config_snapshot(snapshot))

    def preview_intent(
        self,
        snapshot: RuntimeConfigSnapshot | dict[str, Any],
        intent_name: str,
    ) -> str:
        """Return one Intent block using the runtime renderer."""

        config = validate_runtime_config_snapshot(snapshot)
        active = {intent.name for intent in _active_intents(config)}
        if intent_name not in active:
            raise ValueError(f"Intent 不存在或未启用：{intent_name}")
        return _render_intents(config, intent_name=intent_name)

    def preview_slots(self, snapshot: RuntimeConfigSnapshot | dict[str, Any]) -> str:
        """Return the complete Slot module used by the runtime prompt."""

        return _render_slots(validate_runtime_config_snapshot(snapshot))

    def preview_slot(
        self,
        snapshot: RuntimeConfigSnapshot | dict[str, Any],
        slot_name: str,
    ) -> str:
        """Return one enabled Slot block using the runtime renderer."""

        config = validate_runtime_config_snapshot(snapshot)
        active = {slot.name for slot in config.active_slots}
        if slot_name not in active:
            raise ValueError(f"Slot 不存在或未启用：{slot_name}")
        slot = next(slot for slot in config.active_slots if slot.name == slot_name)
        if slot.value_type == "enum":
            assert slot.enum_group is not None
            return _render_enum_matcher(config, slot.enum_group, slot_name=slot.name)
        return _render_slots(config, slot_name=slot_name)

    def preview_enum_group(
        self,
        snapshot: RuntimeConfigSnapshot | dict[str, Any],
        enum_group: str,
    ) -> str:
        """Return the LLM examples or program matcher represented by one group."""

        config = validate_runtime_config_snapshot(snapshot)
        if enum_group not in config.enums:
            raise ValueError(f"Enum Group 不存在：{enum_group}")
        referenced = [
            slot
            for slot in config.active_slots
            if slot.enum_group == enum_group
        ]
        if not referenced:
            raise ValueError(
                f"Enum Group {enum_group} 未被已启用的 Slot 引用，不会参与提取"
            )
        if all(slot.value_type == "string" for slot in referenced):
            return _render_slots(config, enum_group=enum_group)
        return _render_enum_matcher(config, enum_group)


def _active_routes(snapshot: RuntimeConfigSnapshot):
    return [route for route in snapshot.routes if route.enabled]


def _active_intents(snapshot: RuntimeConfigSnapshot):
    route_names = {route.name for route in _active_routes(snapshot)}
    return [
        intent
        for intent in snapshot.intents
        if intent.enabled and intent.route in route_names
    ]


def _active_examples(snapshot: RuntimeConfigSnapshot):
    route_names = {route.name for route in _active_routes(snapshot)}
    intent_names = {intent.name for intent in _active_intents(snapshot)}
    return [
        example
        for example in snapshot.examples
        if example.enabled
        and example.route in route_names
        and (example.intent is None or example.intent in intent_names)
    ]


def _render_routes(snapshot: RuntimeConfigSnapshot) -> str:
    lines = ["## 可选 Route", "", "从以下 Route 中选择一个：", ""]
    for route in _active_routes(snapshot):
        lines.append(f"- {route.name}：{route.description}")
    return "\n".join(lines)


def _render_intents(
    snapshot: RuntimeConfigSnapshot,
    intent_name: str | None = None,
) -> str:
    intents = _active_intents(snapshot)
    if intent_name is not None:
        intents = [intent for intent in intents if intent.name == intent_name]
    examples = _active_examples(snapshot)
    lines = ["## 二级 Intent"]
    for route in _active_routes(snapshot):
        route_intents = [intent for intent in intents if intent.route == route.name]
        if not route_intents:
            continue
        lines.extend(["", f"### Route: {route.name}", ""])
        for intent in route_intents:
            lines.append(f"- {intent.name}：{intent.description}")
            intent_examples = [item.text for item in examples if item.intent == intent.name]
            if intent_examples:
                lines.append("  典型说法：")
                lines.extend(f"  - {text}" for text in intent_examples)
    return "\n".join(lines)


def _render_slots(
    snapshot: RuntimeConfigSnapshot,
    *,
    slot_name: str | None = None,
    enum_group: str | None = None,
) -> str:
    slots = [
        slot
        for slot in snapshot.slots
        if slot.enabled and slot.value_type == "string"
    ]
    if slot_name is not None:
        slots = [slot for slot in slots if slot.name == slot_name]
    if enum_group is not None:
        slots = [slot for slot in slots if slot.enum_group == enum_group]
    if not slots:
        return ""
    lines = [
        "## 由模型提取的文本 Slot",
        "",
        "只提取用户原话中明确出现的文本。枚举 Slot 已由程序处理，不要返回枚举 Slot。",
        "",
    ]
    for slot in slots:
        lines.append(f"- {slot.name}（{slot.zh}）：{slot.description}")
        if not slot.enum_group:
            continue
        values = [value for value in snapshot.enums[slot.enum_group] if value.enabled]
        examples: list[str] = []
        for value in values:
            examples.extend([value.display, *value.aliases])
        examples = list(dict.fromkeys(examples))[:3]
        if examples:
            lines.append(f"  参考示例（不限制输出）：{'、'.join(examples)}")
    return "\n".join(lines)


def _render_enum_matcher(
    snapshot: RuntimeConfigSnapshot,
    enum_group: str,
    *,
    slot_name: str | None = None,
) -> str:
    slots = [
        slot
        for slot in snapshot.active_slots
        if slot.value_type == "enum"
        and slot.enum_group == enum_group
        and (slot_name is None or slot.name == slot_name)
    ]
    values = [value for value in snapshot.enums[enum_group] if value.enabled]
    lines = [
        "## 程序枚举匹配规则",
        "",
        "该词典不进入 LLM Prompt。程序命中任一表达后输出 canonical。",
        "",
    ]
    if slots:
        lines.append(
            "Slot：" + "、".join(f"{slot.name}（{slot.zh}）" for slot in slots)
        )
    lines.append(f"Group：{enum_group}")
    for value in values:
        expressions = list(
            dict.fromkeys([value.canonical, value.display, *value.aliases])
        )
        lines.append(f"- {value.canonical} ← {'、'.join(expressions)}")
    if not values:
        lines.extend(["", "（没有已启用的匹配值）"])
    return "\n".join(lines)


def _render_all_enum_matchers(snapshot: RuntimeConfigSnapshot) -> str:
    groups = list(
        dict.fromkeys(
            slot.enum_group
            for slot in snapshot.active_slots
            if slot.value_type == "enum" and slot.enum_group is not None
        )
    )
    return "\n\n".join(_render_enum_matcher(snapshot, group) for group in groups)


def _render_pre_extracted_slots(text: str, slots: list[SlotValue]) -> str:
    if not slots:
        return ""
    lines = [
        "## 程序已提取的枚举参数",
        "",
        "以下参数仅用于辅助判断 Route 和 Intent，已经由程序处理，不要在 slots 中重复返回。",
        "",
    ]
    for slot in slots:
        source = _utf16_substring(text, slot.start, slot.end) or slot.value
        lines.append(
            f"- {slot.name}（{slot.zh}）：{slot.value}（原文：{source}）"
        )
    return "\n".join(lines)


def _utf16_substring(text: str, start: int, end: int) -> str | None:
    offsets = [0]
    current = 0
    for character in text:
        current += 2 if ord(character) > 0xFFFF else 1
        offsets.append(current)
    try:
        start_index = offsets.index(start)
        end_index = offsets.index(end)
    except ValueError:
        return None
    if end_index < start_index:
        return None
    return text[start_index:end_index]


def _render_output_contract(output_version: Literal[1, 2]) -> str:
    """Render the exact model-output contract for json_object-only endpoints.

    OpenAI-compatible ``json_object`` mode guarantees JSON syntax only.  The
    model still needs the actual field contract in the prompt; a schema name in
    metadata is not visible to the provider.
    """

    if output_version == 2:
        return _render_compound_output_contract()

    schema = canonical_json(LLMRecognitionOutput.model_json_schema())
    example = canonical_json(
        {
            "route": "social_chat",
            "intents": [
                {
                    "name": "greeting",
                    "zh": "问候",
                    "confidence": 0.99,
                }
            ],
            "slots": [],
            "risk": None,
            "need_clarification": False,
            "clarification": None,
            "reason_summary": "用户正在问候",
            "evidence": [{"type": "user_text", "text": "你好"}],
        }
    )
    return (
        "## 输出要求\n\n"
        "只返回一个符合下方 JSON Schema 的 JSON 对象，不要补充解释或 Markdown。\n"
        "intents 中每一项必须使用 name、zh、confidence 字段；不得使用 intent 字段。\n"
        "slots 只返回文本型 Slot，value 必须复制用户原话中的完整文本；不要返回枚举型 Slot。\n"
        "evidence 必须是对象数组；没有证据时返回空数组。\n\n"
        f"### JSON Schema\n\n{schema}\n\n"
        f"### 标准示例\n\n{example}"
    )


def _render_compound_output_contract() -> str:
    schema = canonical_json(LLMRecognitionOutputV2.model_json_schema())
    example = canonical_json(
        {
            "schema_version": 2,
            "is_compound": True,
            "composition": "parallel",
            "actions": [
                {
                    "action_id": "action_1",
                    "source_text": "调高音量",
                    "route": "dialogue_device_control",
                    "intent": {
                        "name": "volume_up",
                        "zh": "调高音量",
                        "confidence": 0.99,
                    },
                    "slots": [],
                    "order": 1,
                    "depends_on": [],
                },
                {
                    "action_id": "action_2",
                    "source_text": "回答我今天的训练计划",
                    "route": "information_query",
                    "intent": {
                        "name": "query_schedule",
                        "zh": "查询训练日程",
                        "confidence": 0.96,
                    },
                    "slots": [],
                    "order": 2,
                    "depends_on": [],
                },
            ],
            "risk": None,
            "need_clarification": False,
            "clarification": None,
            "reason_summary": "用户同时要求调整音量并查询训练计划",
            "evidence": [{"type": "user_text", "text": "调高音量并回答我今天的训练计划"}],
        }
    )
    return (
        "## 输出要求（复合意图 V2）\n\n"
        "只返回一个符合下方 JSON Schema 的 JSON 对象，不要补充解释或 Markdown。\n"
        "把用户表达的每个独立、可执行意图拆成一个 action，不得把跨 Route 意图合并，也不得因动作数量多而省略。\n"
        "actions 不设数量上限；action_id 按 action_1、action_2 递增，order 从 1 连续递增。\n"
        "单动作使用 single；“并且/同时”使用 parallel 且 depends_on 为空；“先…再…”使用 sequential，后续动作依赖前序动作；“或者”使用 alternative、depends_on 为空，并要求澄清。\n"
        "每个 action 的 source_text 必须逐字复制该动作对应的连续用户原话，不含连接词；不得改写。\n"
        "每个 action 只能包含自己的 route、intent 和文本型 slots；不要返回枚举型 Slot；intent 必须使用 name、zh、confidence 字段。\n"
        "evidence 必须是对象数组；没有证据时返回空数组。\n\n"
        f"### JSON Schema\n\n{schema}\n\n"
        f"### 标准示例\n\n{example}"
    )


def _render_context(value: dict[str, Any]) -> str:
    return "\n".join(_context_lines(value))


def _context_lines(value: Any, indent: int = 0) -> list[str]:
    prefix = "  " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key in sorted(value):
            item = value[key]
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.extend(_context_lines(item, indent + 1))
            else:
                lines.append(f"{prefix}{key}: {_plain_scalar(item)}")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.extend(_context_lines(item, indent + 1))
            else:
                lines.append(f"{prefix}- {_plain_scalar(item)}")
        return lines
    return [f"{prefix}{_plain_scalar(value)}"]


def _plain_scalar(value: Any) -> str:
    if value is None:
        return "无"
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)
