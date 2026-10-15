"""Deterministic, configuration-driven plain-text prompt construction."""

from __future__ import annotations

import hashlib
from typing import Any

from app.schemas.intent import (
    LLMStructuredIntentOutput,
    PromptBuildResult,
    PromptMessage,
    RuntimeConfigSnapshot,
    validate_runtime_config_snapshot,
)


class PromptBuilder:
    """Build the exact plain-text messages sent through ``LLMProvider``."""

    def build(
        self,
        snapshot: RuntimeConfigSnapshot | dict[str, Any],
        text: str,
        context: dict[str, Any] | None = None,
    ) -> PromptBuildResult:
        config = validate_runtime_config_snapshot(snapshot)
        business_modules = [
            _render_routes(config),
            _render_intents(config),
            _render_slots(config),
        ]
        system_sections = [config.prompt_template.system.strip()]
        if config.prompt_template.rules:
            rules = "\n".join(f"- {rule.strip()}" for rule in config.prompt_template.rules)
            system_sections.append(f"## 识别规则\n\n{rules}")
        system_sections.extend(module for module in business_modules if module)
        system_sections.append(
            "## 输出要求\n\n"
            "返回一个符合接口字段要求的 JSON 对象，只返回识别结果，不要补充解释。"
        )
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
        effective_text = "\n\n".join(business_modules)
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
                "output_schema_name": LLMStructuredIntentOutput.__name__,
            },
        )

    def preview(
        self,
        snapshot: RuntimeConfigSnapshot | dict[str, Any],
        text: str,
        context: dict[str, Any] | None = None,
    ) -> PromptBuildResult:
        """Return the same prompt as runtime without calling a model."""

        return self.build(snapshot, text=text, context=context)

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


def _render_slots(snapshot: RuntimeConfigSnapshot) -> str:
    slots = [slot for slot in snapshot.slots if slot.enabled]
    if not slots:
        return ""
    lines = ["## 可提取 Slot", ""]
    for slot in slots:
        lines.append(f"- {slot.name}（{slot.value_type}）：{slot.description}")
        if slot.value_type != "enum" or not slot.enum_group:
            continue
        values = [value for value in snapshot.enums[slot.enum_group] if value.enabled]
        rendered_values = []
        for value in values:
            expressions = list(dict.fromkeys([value.display, *value.aliases]))
            suffix = f"（表达：{'、'.join(expressions)}）" if expressions else ""
            rendered_values.append(f"{value.canonical}{suffix}")
        if rendered_values:
            lines.append(f"  可选值：{'；'.join(rendered_values)}")
    return "\n".join(lines)


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
