"""Phone numbers: international with a plus, Russian 7/8 numbers, and national
numbers with a bracketed or dotted/hyphenated area code.

A bare ten-digit national number without those marks is left to the
long-digit-run detector.
"""

from __future__ import annotations

import re

from jarvis.personal_proxy.common.spans import Span

_JOIN = r"(?:[ \n]?[.-][ \n]?|[ \n])?"
_CANDIDATE = re.compile(r"(?<!\w)\+?\(?\d[\d ()\-.\n]*\d")
_INTERNATIONAL_DIGITS = range(10, 16)
_RUSSIAN_DIGITS = 11
_RUSSIAN_PREFIXES = "78"
_MIN_AREA_CODE_DIGITS = 10

_BRACKETED_AREA = re.compile(
    rf"(?<!\w)\(\d{{3,5}}\)[ \n]?(?:-[ \n]?)?\d{{2,4}}(?:{_JOIN}\d{{2,4}}){{1,3}}(?!\d)"
)
_SEPARATED_AREA = re.compile(
    r"(?<![\w.-])\d{3}[.-]\d{3}[.-](?:\d{4}|\d{2}[.-]\d{2})(?!\d|[.-]\d)"
)


def _is_phone(candidate: str) -> bool:
    digits = re.sub(r"\D", "", candidate)
    if candidate.startswith("+"):
        return len(digits) in _INTERNATIONAL_DIGITS
    return len(digits) == _RUSSIAN_DIGITS and digits[0] in _RUSSIAN_PREFIXES


def _has_enough_digits(candidate: str) -> bool:
    return sum(char.isdigit() for char in candidate) >= _MIN_AREA_CODE_DIGITS


def find_phones(text: str) -> list[Span]:
    spans = [
        Span(match.start(), match.end())
        for match in _CANDIDATE.finditer(text)
        if _is_phone(match.group())
    ]
    spans += [
        Span(match.start(), match.end())
        for match in _BRACKETED_AREA.finditer(text)
        if _has_enough_digits(match.group())
    ]
    spans += [
        Span(match.start(), match.end()) for match in _SEPARATED_AREA.finditer(text)
    ]
    return spans
