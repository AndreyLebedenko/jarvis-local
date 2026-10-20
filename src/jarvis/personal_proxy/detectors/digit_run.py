"""Long digit runs that no more specific detector recognized."""

from __future__ import annotations

from jarvis.personal_proxy.detectors.digit_groups import digit_runs
from jarvis.personal_proxy.spans import Span

MIN_DIGITS = 9


def find_long_digit_runs(text: str) -> list[Span]:
    return [
        Span(run[0].span.start, run[-1].span.end)
        for run in digit_runs(text)
        if sum(len(group.digits) for group in run) >= MIN_DIGITS
    ]
