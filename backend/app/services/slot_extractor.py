"""Deterministic Slot extraction that does not consume LLM tokens."""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.intent import RuntimeConfigSnapshot, SlotValue


@dataclass(frozen=True)
class _EnumMatch:
    slot_order: int
    value_order: int
    form_order: int
    slot_name: str
    slot_zh: str
    canonical: str
    char_start: int
    char_end: int


def extract_enum_slots(text: str, snapshot: RuntimeConfigSnapshot) -> list[SlotValue]:
    """Match enabled enum forms and return canonical values with UTF-16 spans.

    Matching is exact and deterministic. At one character offset the longest
    configured form wins, which prevents a short alias such as ``胸`` from
    shadowing ``胸部``.
    """

    offsets = _utf16_offsets(text)
    matches: list[_EnumMatch] = []
    for slot_order, slot in enumerate(snapshot.slots):
        if not slot.enabled or slot.value_type != "enum" or not slot.enum_group:
            continue
        for value_order, value in enumerate(snapshot.enums[slot.enum_group]):
            if not value.enabled:
                continue
            forms = list(dict.fromkeys((value.canonical, value.display, *value.aliases)))
            for form_order, form in enumerate(forms):
                if not form:
                    continue
                search_from = 0
                while True:
                    char_start = text.find(form, search_from)
                    if char_start < 0:
                        break
                    char_end = char_start + len(form)
                    if not _has_safe_boundaries(text, form, char_start, char_end):
                        search_from = char_start + 1
                        continue
                    matches.append(
                        _EnumMatch(
                            slot_order=slot_order,
                            value_order=value_order,
                            form_order=form_order,
                            slot_name=slot.name,
                            slot_zh=slot.zh,
                            canonical=value.canonical,
                            char_start=char_start,
                            char_end=char_end,
                        )
                    )
                    search_from = char_start + 1

    selected: list[_EnumMatch] = []
    for slot_order in sorted({match.slot_order for match in matches}):
        slot_matches = [match for match in matches if match.slot_order == slot_order]
        slot_matches.sort(
            key=lambda match: (
                match.char_start,
                -(match.char_end - match.char_start),
                match.value_order,
                match.form_order,
            )
        )
        accepted: list[_EnumMatch] = []
        for match in slot_matches:
            if any(
                match.char_start < item.char_end and item.char_start < match.char_end
                for item in accepted
            ):
                continue
            accepted.append(match)
        selected.extend(accepted)

    unique: dict[tuple[str, str, int, int], SlotValue] = {}
    for match in selected:
        start = offsets[match.char_start]
        end = offsets[match.char_end]
        key = (match.slot_name, match.canonical, start, end)
        unique[key] = SlotValue(
            name=match.slot_name,
            zh=match.slot_zh,
            value=match.canonical,
            start=start,
            end=end,
            confidence=1.0,
        )
    return sorted(
        unique.values(),
        key=lambda slot: (slot.start, slot.end, slot.name, slot.value),
    )


def locate_action_ranges(
    text: str,
    actions: list[tuple[str, str]],
) -> dict[str, tuple[int, int]]:
    """Locate ordered, exact action fragments and return UTF-16 ranges."""

    offsets = _utf16_offsets(text)
    ranges: dict[str, tuple[int, int]] = {}
    search_from = 0
    for action_id, source_text in actions:
        char_start = text.find(source_text, search_from)
        if char_start < 0:
            char_start = text.find(source_text)
        if char_start < 0:
            continue
        char_end = char_start + len(source_text)
        ranges[action_id] = (offsets[char_start], offsets[char_end])
        search_from = char_end
    return ranges


def scope_enum_slots_to_actions(
    slots: list[SlotValue],
    action_ranges: dict[str, tuple[int, int]],
) -> dict[str, list[SlotValue]]:
    """Assign a deterministic enum match only to the action fragment containing it."""

    scoped: dict[str, list[SlotValue]] = {action_id: [] for action_id in action_ranges}
    for slot in slots:
        for action_id, (start, end) in action_ranges.items():
            if start <= slot.start and slot.end <= end:
                scoped[action_id].append(slot)
                break
    return scoped


def _utf16_offsets(text: str) -> list[int]:
    offsets = [0]
    current = 0
    for character in text:
        current += 2 if ord(character) > 0xFFFF else 1
        offsets.append(current)
    return offsets


def _has_safe_boundaries(text: str, form: str, start: int, end: int) -> bool:
    """Prevent ASCII forms such as ``leg`` from matching inside ``college``."""

    if _is_ascii_word_character(form[0]):
        if start > 0 and _is_ascii_word_character(text[start - 1]):
            return False
    if _is_ascii_word_character(form[-1]):
        if end < len(text) and _is_ascii_word_character(text[end]):
            return False
    return True


def _is_ascii_word_character(value: str) -> bool:
    return value.isascii() and (value.isalnum() or value == "_")
