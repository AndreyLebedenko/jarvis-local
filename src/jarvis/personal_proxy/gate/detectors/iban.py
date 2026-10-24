"""IBANs: country prefix, a known or plausible length, and a valid mod-97."""

from __future__ import annotations

import re

from jarvis.personal_proxy.common.spans import Span

_START = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{2}\d{2}(?=[ \n]?[A-Za-z0-9])")
_GROUP = re.compile(r"[ \n]?[A-Za-z0-9]{1,4}")
_UNKNOWN_COUNTRY_LENGTHS = range(15, 35)
_MAX_GROUPS = 9
_LENGTH_BY_COUNTRY = {
    "AE": 23,
    "AT": 20,
    "BE": 16,
    "BY": 28,
    "CH": 21,
    "CZ": 24,
    "DE": 22,
    "DK": 18,
    "EE": 20,
    "ES": 24,
    "FI": 18,
    "FR": 27,
    "GB": 22,
    "GE": 22,
    "GR": 27,
    "IE": 22,
    "IT": 27,
    "KZ": 20,
    "LT": 20,
    "LU": 20,
    "LV": 21,
    "NL": 18,
    "NO": 15,
    "PL": 28,
    "PT": 25,
    "RU": 33,
    "SA": 24,
    "SE": 24,
    "TR": 26,
    "UA": 29,
}


def _mod97_valid(compact: str) -> bool:
    rearranged = compact[4:] + compact[:4]
    number = "".join(str(int(char, 36)) for char in rearranged)
    return int(number) % 97 == 1


def _is_iban(compact: str) -> bool:
    compact = compact.upper()
    expected = _LENGTH_BY_COUNTRY.get(compact[:2])
    length_ok = (
        len(compact) == expected
        if expected is not None
        else len(compact) in _UNKNOWN_COUNTRY_LENGTHS
    )
    return length_ok and _mod97_valid(compact)


def _group_ends(text: str, start: int) -> list[int]:
    ends: list[int] = []
    position = start + 4
    while len(ends) < _MAX_GROUPS and (match := _GROUP.match(text, position)):
        position = match.end()
        ends.append(position)
    return ends


def find_ibans(text: str) -> list[Span]:
    spans: list[Span] = []
    covered_until = 0
    for start_match in _START.finditer(text):
        start = start_match.start()
        if start < covered_until:
            continue
        for end in reversed(_group_ends(text, start)):
            if _is_iban(re.sub(r"\s", "", text[start:end])):
                spans.append(Span(start, end))
                covered_until = end
                break
    return spans
