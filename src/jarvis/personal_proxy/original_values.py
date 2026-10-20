"""Finds the original values of the sanitizer's mapping inside a message,
exactly or in another declension. Tokens inside a placeholder such as
<PERSON_1> are ignored: they are the sanitizer's own text.

A token shorter than the stem minimum is compared exactly, because a prefix of
two letters would match unrelated words. In a multi-token original those short
tokens ("в", "ли") are skipped when a longer token exists, since they would
block ordinary prose; if every token is short, all of them are compared.

`exact_only` turns the stem rule off: the system prompt is a trusted constant,
and a stem such as "Per" or "Lan" would otherwise match its ordinary words.
A whole-word equality still counts.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from collections.abc import Iterable

from jarvis.personal_proxy.spans import Span
from jarvis.personal_proxy.text import (
    MIN_STEM_LENGTH,
    TokenSpan,
    stem_present,
    token_spans,
    tokenize,
)

_PLACEHOLDER = re.compile(r"<[A-Z_]+_\d+>")


def _tokens_to_check(original: str) -> list[str]:
    tokens = tokenize(original)
    long_tokens = [token for token in tokens if len(token) >= MIN_STEM_LENGTH]
    return long_tokens or tokens


def _matches(form: str, token: str, exact_only: bool) -> bool:
    if exact_only or len(form) < MIN_STEM_LENGTH:
        return token == form
    return stem_present(form, [token])


def _outside_placeholders(text: str) -> list[TokenSpan]:
    spans = token_spans(text)
    starts = [span.start for span in spans]
    masked: set[int] = set()
    for placeholder in _PLACEHOLDER.finditer(text):
        position = bisect_left(starts, placeholder.start())
        while position < len(spans) and starts[position] < placeholder.end():
            masked.add(position)
            position += 1
    return [span for index, span in enumerate(spans) if index not in masked]


def find_original_values(
    text: str, originals: Iterable[str], exact_only: bool = False
) -> list[Span]:
    forms = [form for original in originals for form in _tokens_to_check(original)]
    found = {
        Span(span.start, span.end)
        for span in _outside_placeholders(text)
        if any(_matches(form, span.token, exact_only) for form in forms)
    }
    return sorted(found)
