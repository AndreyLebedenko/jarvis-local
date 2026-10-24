"""Brings a message to one canonical shape before the detectors look at it.

Per character: NFKC folding, Unicode spaces become a plain space (line breaks
become a newline), dashes become '-', and invisible format characters are
dropped. Then every whitespace run collapses to one separator (a newline if
the run held a line break), and combining sequences are composed (NFC).

Zero-width space and word joiner are the one ambiguous case: inside a number
or a key they must vanish, between two letters they may be hiding a word
boundary. `zero_width_as_space` picks the second reading; the gate checks the
text under both readings.

Offsets are kept so a position found in the normalized text can be reported
against the original text.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from jarvis.personal_proxy.common.spans import Span

_DASHES = frozenset("\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d")
_LINE_BREAKS = frozenset("\n\r\x0b\x0c\x85\u2028\u2029")
_ZERO_WIDTH_SEPARATORS = frozenset("\u200b\u2060")
_ZERO_WIDTH_MARK = "\u200b"
_SEPARATORS = " \n"

_Entry = tuple[str, int, int]


def _canonical_chars(char: str) -> str:
    if char.isascii():
        if char in _LINE_BREAKS:
            return "\n"
        return " " if char.isspace() else char
    folded = []
    for part in unicodedata.normalize("NFKC", char):
        if unicodedata.category(part) == "Cf":
            continue
        if part in _LINE_BREAKS:
            folded.append("\n")
        elif part.isspace():
            folded.append(" ")
        elif part in _DASHES:
            folded.append("-")
        else:
            folded.append(part)
    return "".join(folded)


def _canonical_entries(original: str) -> list[_Entry]:
    entries: list[_Entry] = []
    for index, char in enumerate(original):
        if char in _ZERO_WIDTH_SEPARATORS:
            entries.append((_ZERO_WIDTH_MARK, index, index + 1))
            continue
        entries.extend((part, index, index + 1) for part in _canonical_chars(char))
    return entries


def _resolve_zero_width(entries: list[_Entry], *, as_space: bool) -> list[_Entry]:
    next_real = [""] * (len(entries) + 1)
    for position in range(len(entries) - 1, -1, -1):
        char = entries[position][0]
        next_real[position] = (
            next_real[position + 1] if char == _ZERO_WIDTH_MARK else char
        )
    resolved: list[_Entry] = []
    for position, (char, start, end) in enumerate(entries):
        if char != _ZERO_WIDTH_MARK:
            resolved.append((char, start, end))
        elif (
            as_space
            and resolved
            and resolved[-1][0].isalpha()
            and next_real[position + 1].isalpha()
        ):
            resolved.append((" ", start, end))
    return resolved


def _collapse_whitespace(entries: list[_Entry]) -> list[_Entry]:
    collapsed: list[_Entry] = []
    for char, start, end in entries:
        if char in _SEPARATORS and collapsed and collapsed[-1][0] in _SEPARATORS:
            previous, previous_start, _ = collapsed[-1]
            separator = "\n" if "\n" in (previous, char) else " "
            collapsed[-1] = (separator, previous_start, end)
        else:
            collapsed.append((char, start, end))
    return collapsed


def _compose(entries: list[_Entry]) -> list[_Entry]:
    composed: list[_Entry] = []
    position = 0
    while position < len(entries):
        last = position + 1
        while last < len(entries) and unicodedata.combining(entries[last][0]):
            last += 1
        cluster = entries[position:last]
        start, end = cluster[0][1], cluster[-1][2]
        if len(cluster) == 1:
            composed.append(cluster[0])
        else:
            text = unicodedata.normalize("NFC", "".join(c for c, _, _ in cluster))
            composed.extend((char, start, end) for char in text)
        position = last
    return composed


@dataclass(frozen=True, slots=True)
class NormalizedMessage:
    text: str
    _starts: tuple[int, ...]
    _ends: tuple[int, ...]

    def original_span(self, span: Span) -> Span:
        return Span(self._starts[span.start], self._ends[span.end - 1])


def normalize_message(
    original: str, *, zero_width_as_space: bool = False
) -> NormalizedMessage:
    entries = _compose(
        _collapse_whitespace(
            _resolve_zero_width(
                _canonical_entries(original), as_space=zero_width_as_space
            )
        )
    )
    return NormalizedMessage(
        "".join(char for char, _, _ in entries),
        tuple(start for _, start, _ in entries),
        tuple(end for _, _, end in entries),
    )
