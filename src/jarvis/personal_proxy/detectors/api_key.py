"""API-key-like strings: well-known prefixes, JWT shape, hex digests of key
size, and long tokens of high entropy: either letters mixed with digits, or
letters only with both cases in roughly equal share.

A hex string of 32, 40 or 64 characters is blocked even when it is only a hash
or a git SHA: it cannot be told from a key, and the gate fails closed.
Identifiers such as snake_case or camelCase names are kept out by requiring
many letter/digit alternations, which random tokens have and names do not.
A letters-only token needs many case switches and at least MIN_UPPER_SHARE
capitals, which a CamelCase identifier (about one capital per word) lacks.
A token with three or more '/' is a file path or URL and is skipped; Base64
keys keep their '/'.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from itertools import pairwise

from jarvis.personal_proxy.spans import Span

MIN_GENERIC_LENGTH = 32
MIN_GENERIC_ENTROPY_BITS = 3.5
MIN_LETTER_DIGIT_SWITCHES = 4
MIN_CASE_SWITCHES = 8
MIN_UPPER_SHARE = 0.3
MAX_UPPER_SHARE = 0.7
MAX_PATH_SLASHES = 2

_KNOWN_SHAPES = re.compile(
    r"(?<![^\W_])sk-[A-Za-z0-9_-]{16,}"
    r"|(?<![^\W_])AKIA[0-9A-Z]{16}(?![^\W_])"
    r"|(?<![^\W_])gh[pousr]_[A-Za-z0-9]{30,}"
    r"|(?<![^\W_])glpat-[A-Za-z0-9_-]{20,}"
    r"|(?<![^\W_])xox[abprs]-[A-Za-z0-9-]{10,}"
    r"|(?<![^\W_])AIza[0-9A-Za-z_-]{35}"
    r"|(?<![^\W_])eyJ[\w-]+\.[\w-]+\.[\w-]+"
    r"|(?<![\w-])\d{6,10}:[A-Za-z0-9_-]{30,}"
    r"|(?<![0-9A-Fa-f])(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])"
    r"(?:[0-9a-f]{64}|[0-9a-f]{40}|[0-9a-f]{32})(?![0-9A-Fa-f])"
)
_GENERIC_TOKEN = re.compile(
    rf"(?<![A-Za-z0-9_+/=-])[A-Za-z0-9_+/=-]{{{MIN_GENERIC_LENGTH},}}(?![A-Za-z0-9_+/=-])"
)


def _entropy_bits(token: str) -> float:
    counts = Counter(token)
    return -sum(
        (count / len(token)) * math.log2(count / len(token))
        for count in counts.values()
    )


def _letter_digit_switches(token: str) -> int:
    return sum(
        1
        for left, right in pairwise(token)
        if (left.isdigit() and right.isalpha()) or (left.isalpha() and right.isdigit())
    )


def _case_switches(token: str) -> int:
    return sum(
        1 for left, right in pairwise(token) if left.isupper() != right.isupper()
    )


def _is_random_letters_and_digits(token: str) -> bool:
    return (
        any(char.isdigit() for char in token)
        and any(char.isalpha() for char in token)
        and _letter_digit_switches(token) >= MIN_LETTER_DIGIT_SWITCHES
    )


def _is_random_mixed_case_letters(token: str) -> bool:
    if not token.isalpha():
        return False
    upper_share = sum(char.isupper() for char in token) / len(token)
    return (
        MIN_UPPER_SHARE <= upper_share <= MAX_UPPER_SHARE
        and _case_switches(token) >= MIN_CASE_SWITCHES
    )


def _looks_random(token: str) -> bool:
    if token.count("/") > MAX_PATH_SLASHES:
        return False
    shaped = _is_random_letters_and_digits(token) or _is_random_mixed_case_letters(
        token
    )
    return shaped and _entropy_bits(token) >= MIN_GENERIC_ENTROPY_BITS


def find_api_keys(text: str) -> list[Span]:
    known = [Span(m.start(), m.end()) for m in _KNOWN_SHAPES.finditer(text)]
    generic = [
        Span(m.start(), m.end())
        for m in _GENERIC_TOKEN.finditer(text)
        if _looks_random(m.group())
    ]
    return known + [s for s in generic if not any(s.overlaps(k) for k in known)]
