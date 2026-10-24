"""Text primitives for comparing a payload with original values: tokens that
keep their position, and a declension-tolerant stem match."""

from __future__ import annotations

import re
from typing import NamedTuple

_WORD = re.compile(r"[^\W_]+", re.UNICODE)

MIN_STEM_LENGTH = 3
STEM_ENDING_LENGTH = 2


class TokenSpan(NamedTuple):
    token: str
    start: int
    end: int


def _canonical(word: str) -> str:
    return word.casefold().replace("ё", "е")


def token_spans(text: str) -> list[TokenSpan]:
    return [
        TokenSpan(_canonical(match.group()), match.start(), match.end())
        for match in _WORD.finditer(text)
    ]


_HYPHENATED_WORD = re.compile(r"[^\W_]+(?:-[^\W_]+)*", re.UNICODE)


def joined_token_spans(text: str) -> list[TokenSpan]:
    """Like token_spans, but a hyphenated word is one token with its hyphens removed."""
    return [
        TokenSpan(
            _canonical(match.group().replace("-", "")), match.start(), match.end()
        )
        for match in _HYPHENATED_WORD.finditer(text)
    ]


def tokenize(text: str) -> list[str]:
    return [span.token for span in token_spans(text)]


def stem(token: str) -> str:
    return token[: max(MIN_STEM_LENGTH, len(token) - STEM_ENDING_LENGTH)]


def stem_present(form: str, tokens: list[str]) -> bool:
    prefix = stem(form)
    return any(token.startswith(prefix) for token in tokens)
