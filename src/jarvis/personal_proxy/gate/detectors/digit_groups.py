"""Runs of digit groups, shared by the card and the long-digit-run detectors.

A run is digits joined by a single space or hyphen (a hyphen may have a space
on each side). With `across_lines` a line break joins groups too: a card split
over two lines is still a card, but a list of short numbers, one per line, is
not a long digit run.

Without `across_lines`, two runs on adjacent lines still form one run when
each has at least MIN_DIGITS_ACROSS_BREAK digits (a number wrapped over two
lines: "112-233" then "445 95"). A column of short numbers stays separate.

A second kind of run joins groups with '.', ',' or '/', but only when every
group has at least three digits: that keeps dates (20.10.2026), prices
(1,500,000) and decimals out of it while 4539.1488.0343.6467 and 123/456/789
still count.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from jarvis.personal_proxy.common.spans import Span

_SAME_LINE_JOIN = r"(?: ?- ?| )"
_ACROSS_LINES_JOIN = r"(?:[ \n]?-[ \n]?|[ \n])"
_PUNCTUATED_RUN = re.compile(r"(?<!\d)\d{3,}(?:[./,]\d{3,})+")
_SAME_LINE_RUN = re.compile(rf"(?<!\d)\d+(?:{_SAME_LINE_JOIN}\d+)*")
_ACROSS_LINES_RUN = re.compile(rf"(?<!\d)\d+(?:{_ACROSS_LINES_JOIN}\d+)*")
_GROUP = re.compile(r"\d+")
MIN_DIGITS_ACROSS_BREAK = 4


class DigitGroup(NamedTuple):
    span: Span
    digits: str


def _groups(run: re.Match[str]) -> list[DigitGroup]:
    offset = run.start()
    return [
        DigitGroup(Span(offset + group.start(), offset + group.end()), group.group())
        for group in _GROUP.finditer(run.group())
    ]


def _digit_count(run: list[DigitGroup]) -> int:
    return sum(len(group.digits) for group in run)


def _wrapped_over_a_line_break(
    previous: list[DigitGroup], run: list[DigitGroup], text: str
) -> bool:
    return (
        text[previous[-1].span.end : run[0].span.start] == "\n"
        and _digit_count(previous) >= MIN_DIGITS_ACROSS_BREAK
        and _digit_count(run) >= MIN_DIGITS_ACROSS_BREAK
    )


def _join_wrapped_runs(
    runs: list[list[DigitGroup]], text: str
) -> list[list[DigitGroup]]:
    joined: list[list[DigitGroup]] = []
    previous: list[DigitGroup] = []
    for run in runs:
        if joined and _wrapped_over_a_line_break(previous, run, text):
            joined[-1] = joined[-1] + run
        else:
            joined.append(run)
        previous = run
    return joined


def digit_runs(text: str, *, across_lines: bool = False) -> list[list[DigitGroup]]:
    spaced = _ACROSS_LINES_RUN if across_lines else _SAME_LINE_RUN
    runs = [_groups(run) for run in spaced.finditer(text)]
    if not across_lines:
        runs = _join_wrapped_runs(runs, text)
    return runs + [_groups(run) for run in _PUNCTUATED_RUN.finditer(text)]
