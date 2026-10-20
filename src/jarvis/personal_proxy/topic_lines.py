"""Finds lines of the local-only topics text inside a message.

A line is compared as word tokens folded like the rest of the package (case,
yo/ye). Leading bullet, number, dash and '#' markers and trailing punctuation
do not count. The match is on token boundaries, so "test" does not hit
"contest". A hyphenated word matches in its joined and its separated form, on
either side. Lines shorter than MIN_LINE_LENGTH characters are ignored.

Tokens are joined into one string and searched with `str.find`, which keeps
long repetitive inputs fast.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from collections.abc import Callable

from jarvis.personal_proxy.spans import Span
from jarvis.personal_proxy.text import TokenSpan, joined_token_spans, token_spans

MIN_LINE_LENGTH = 3

_MARKER_CHARS = r"[\s#*\-•\u2014]*"
_LEADING_MARKERS = re.compile(rf"^{_MARKER_CHARS}(?:\d+[.)]\s*)?{_MARKER_CHARS}")

_Tokenizer = Callable[[str], list[TokenSpan]]


def _line_needles(topics_text: str, tokenizer: _Tokenizer) -> set[tuple[str, ...]]:
    needles: set[tuple[str, ...]] = set()
    for raw_line in topics_text.splitlines():
        line = _LEADING_MARKERS.sub("", raw_line)
        tokens = tuple(span.token for span in tokenizer(line))
        if tokens and len(" ".join(tokens)) >= MIN_LINE_LENGTH:
            needles.add(tokens)
    return needles


def _occurrences(haystack: str, needle: str) -> list[int]:
    found: list[int] = []
    index = haystack.find(needle)
    while index != -1:
        end = index + len(needle)
        if (index == 0 or haystack[index - 1] == " ") and (
            end == len(haystack) or haystack[end] == " "
        ):
            found.append(index)
        index = haystack.find(needle, index + 1)
    return found


def _matches(text: str, topics_text: str, tokenizer: _Tokenizer) -> set[Span]:
    spans = tokenizer(text)
    haystack = " ".join(span.token for span in spans)
    starts: list[int] = []
    offset = 0
    for span in spans:
        starts.append(offset)
        offset += len(span.token) + 1
    found: set[Span] = set()
    for needle in _line_needles(topics_text, tokenizer):
        for index in _occurrences(haystack, " ".join(needle)):
            first = bisect_left(starts, index)
            last = first + len(needle) - 1
            found.add(Span(spans[first].start, spans[last].end))
    return found


def find_topic_lines(text: str, topics_text: str) -> list[Span]:
    found = _matches(text, topics_text, token_spans)
    found |= _matches(text, topics_text, joined_token_spans)
    return sorted(found)
