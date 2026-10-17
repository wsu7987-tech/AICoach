"""Diagnostic metrics only for explicitly labelled fields, never inferred gold."""

from collections import Counter

from app.services.evaluation.rules import _slot_values, match_actions


def labelled_metrics(items):
    matrix = Counter()
    dimensions = {
        key: {"checked": 0, "passed": 0}
        for key in (
            "intent",
            "slots",
            "composition",
            "clarification",
            "risk",
        )
    }
    labelled_cases = 0

    def record(key, passed):
        dimensions[key]["checked"] += 1
        dimensions[key]["passed"] += bool(passed)

    for item in items:
        expected = item.get("expected") or {}
        actual = item.get("actual")
        if expected.get("composition") is not None:
            record("composition", actual and actual["composition"] == expected["composition"])
        if expected.get("need_clarification") is not None:
            record(
                "clarification",
                actual and actual["need_clarification"] == expected["need_clarification"],
            )
        if "risk" in expected:
            risk = (actual or {}).get("risk")
            record(
                "risk",
                actual is not None
                and expected["risk"]
                == ({"type": risk["type"], "level": risk["level"]} if risk else None),
            )
        gold = expected.get("actions")
        if not gold:
            continue
        labelled_cases += 1
        actions = sorted((actual or {}).get("actions", []), key=lambda action: action["order"])
        ordered = expected.get("composition") == "sequential" or any(
            action.get("depends_on") for action in gold
        )
        mapping = match_actions(gold, actions, ordered)
        for index, target in enumerate(gold):
            found = actions[mapping[index]] if index in mapping else None
            matrix[target["route"], found["route"] if found else "（未识别/执行错误）"] += 1
            if "intent" in target:
                record(
                    "intent",
                    found
                    and target["route"] == found["route"]
                    and target["intent"] == (found.get("intent") or {}).get("name"),
                )
            if target.get("slots") is not None:
                record(
                    "slots",
                    found
                    and target["route"] == found["route"]
                    and _slot_values(target["slots"]) == _slot_values(found.get("slots", [])),
                )
        for index, action in enumerate(actions):
            if index not in mapping.values():
                matrix["（多余动作）", action["route"]] += 1
    labels = sorted({value for pair in matrix for value in pair if not value.startswith("（")})
    per_route = []
    for label in labels:
        tp = matrix[label, label]
        support = sum(value for (gold, _), value in matrix.items() if gold == label)
        predicted = sum(value for (_, actual), value in matrix.items() if actual == label)
        per_route.append(
            {
                "route": label,
                "support": support,
                "predicted": predicted,
                "precision": round(tp / predicted, 4) if predicted else None,
                "recall": round(tp / support, 4) if support else None,
                "f1": round(2 * tp / (support + predicted), 4) if support + predicted else None,
            }
        )
    measured = [entry["f1"] for entry in per_route if entry["support"]]
    return {
        "labelled_cases": labelled_cases,
        "per_route": per_route,
        "confusion": [
            {"expected": gold, "actual": actual, "count": count}
            for (gold, actual), count in sorted(matrix.items())
        ],
        "macro_f1": round(sum(measured) / len(measured), 4) if measured else None,
        "dimensions": dimensions,
    }
