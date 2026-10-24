"""Payment card numbers: 13-19 digits that pass the Luhn check."""

from __future__ import annotations

from jarvis.personal_proxy.common.spans import Span
from jarvis.personal_proxy.gate.detectors.digit_groups import DigitGroup, digit_runs

MIN_DIGITS = 13
MAX_DIGITS = 19


def _passes_luhn(digits: str) -> bool:
    total = 0
    for position, char in enumerate(reversed(digits)):
        value = int(char)
        if position % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _longest_card_end(groups: list[DigitGroup], first: int) -> int | None:
    digits = ""
    best: int | None = None
    for last in range(first, len(groups)):
        digits += groups[last].digits
        if len(digits) > MAX_DIGITS:
            break
        if len(digits) >= MIN_DIGITS and _passes_luhn(digits):
            best = last
    return best


def find_payment_cards(text: str) -> list[Span]:
    spans: list[Span] = []
    for groups in digit_runs(text, across_lines=True):
        first = 0
        while first < len(groups):
            last = _longest_card_end(groups, first)
            if last is None:
                first += 1
                continue
            spans.append(Span(groups[first].span.start, groups[last].span.end))
            first = last + 1
    return spans
