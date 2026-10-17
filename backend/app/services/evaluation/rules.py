"""Deterministic V2 assertions. Omitted fields are never implicit gold labels."""

from collections import Counter
from functools import cache
from typing import Any

from app.schemas.intent import canonical_json


def _slot_values(slots: list[dict]) -> Counter:
    return Counter((slot["name"], slot["value"]) for slot in slots)


def _action_cost(expected: dict, actual: dict) -> int:
    cost = 100 if expected["route"] != actual["route"] else 0
    if "intent" in expected and expected["intent"] != (actual.get("intent") or {}).get("name"):
        cost += 30
    if expected.get("slots") is not None:
        cost += sum(
            (_slot_values(expected["slots"]) - _slot_values(actual.get("slots", []))).values()
        )
        cost += sum(
            (_slot_values(actual.get("slots", [])) - _slot_values(expected["slots"])).values()
        )
    return cost


def match_actions(expected: list[dict], actual: list[dict], ordered: bool) -> dict[int, int]:
    if ordered:
        return {index: index for index in range(min(len(expected), len(actual)))}
    # Gold is bounded to twelve actions. Excess actual actions are reported separately.
    candidates = actual[:12]

    @cache
    def assign(index: int, used: int) -> tuple[int, tuple[int, ...]]:
        if index == len(expected):
            return 0, ()
        options: list[tuple[int, tuple[int, ...]]] = []
        for candidate, action in enumerate(candidates):
            if used & (1 << candidate):
                continue
            tail_cost, tail = assign(index + 1, used | (1 << candidate))
            options.append((_action_cost(expected[index], action) + tail_cost, (candidate, *tail)))
        if len(expected) - index > len(candidates) - used.bit_count():
            tail_cost, tail = assign(index + 1, used)
            options.append((1000 + tail_cost, (-1, *tail)))
        return min(options)

    return {index: candidate for index, candidate in enumerate(assign(0, 0)[1]) if candidate >= 0}


def evaluate_rules(expected: dict | None, actual: dict) -> dict[str, Any]:
    issues: list[dict] = []
    checked: list[str] = []
    expected = expected or {}

    def compare(field: str, want: Any, got: Any, tag: str, message: str):
        checked.append(field)
        if want != got:
            issues.append(
                {"field": field, "expected": want, "actual": got, "tag": tag, "message": message}
            )

    for field, tag, message in (
        ("composition", "composition", "动作组合方式不符合标准"),
        ("need_clarification", "clarification", "追问触发不符合标准"),
    ):
        if expected.get(field) is not None:
            compare(field, expected[field], actual.get(field), tag, message)
    if "risk" in expected:
        risk = actual.get("risk")
        compare(
            "risk",
            expected["risk"],
            {"type": risk["type"], "level": risk["level"]} if risk else None,
            "risk",
            "风险类型或等级不符合标准",
        )

    if expected.get("actions") is not None:
        gold = expected["actions"]
        actions = sorted(actual["actions"], key=lambda action: action["order"])
        checked.append("actions.count")
        if len(gold) != len(actions):
            issues.append(
                {
                    "field": "actions.count",
                    "expected": len(gold),
                    "actual": len(actions),
                    "tag": "action_missing" if len(actions) < len(gold) else "action_extra",
                    "message": f"期望 {len(gold)} 个动作，实际 {len(actions)} 个动作",
                }
            )
        ordered = expected.get("composition") == "sequential" or any(
            action.get("depends_on") for action in gold
        )
        mapping = match_actions(gold, actions, ordered)
        for index, target in enumerate(gold):
            prefix = f"actions[{index + 1}]"
            if index not in mapping:
                issues.append(
                    {
                        "field": prefix,
                        "tag": "action_missing",
                        "message": f"缺少期望动作 {index + 1}",
                    }
                )
                continue
            found = actions[mapping[index]]
            compare(
                f"{prefix}.route",
                target["route"],
                found["route"],
                "route",
                f"动作 {index + 1} 的一级路由错误",
            )
            if "intent" in target:
                compare(
                    f"{prefix}.intent",
                    target["intent"],
                    (found.get("intent") or {}).get("name"),
                    "intent",
                    f"动作 {index + 1} 的二级意图错误",
                )
            if target.get("slots") is not None:
                compare(
                    f"{prefix}.slots",
                    sorted(_slot_values(target["slots"]).elements()),
                    sorted(_slot_values(found.get("slots", [])).elements()),
                    "slot",
                    f"动作 {index + 1} 的参数缺失、多余、值错误或归属错误",
                )
            if target.get("depends_on") is not None:
                dependencies = [
                    actions[mapping[d - 1]]["action_id"] if d - 1 in mapping else f"missing:{d}"
                    for d in target["depends_on"]
                ]
                compare(
                    f"{prefix}.depends_on",
                    sorted(dependencies),
                    sorted(found["depends_on"]),
                    "dependency",
                    f"动作 {index + 1} 的依赖关系错误",
                )
    return {"checked": checked, "issues": issues, "passed": not issues}


def semantic_signature(actual: dict | None) -> str | None:
    """Ignore generated ids, confidences and clarification wording in stability."""
    if actual is None:
        return None
    ordered = sorted(actual["actions"], key=lambda action: action["order"])
    ids = {action["action_id"]: index for index, action in enumerate(ordered)}
    actions = [
        {
            "route": action["route"],
            "intent": (action.get("intent") or {}).get("name"),
            "slots": sorted(_slot_values(action.get("slots", [])).elements()),
            "depends_on": sorted(ids.get(key, -1) for key in action["depends_on"]),
        }
        for action in ordered
    ]
    if actual["composition"] in {"parallel", "alternative"}:
        actions.sort(key=canonical_json)
    risk = actual.get("risk")
    return canonical_json(
        {
            "actions": actions,
            "composition": actual["composition"],
            "risk": {"type": risk["type"], "level": risk["level"]} if risk else None,
            "need_clarification": actual["need_clarification"],
        }
    )
