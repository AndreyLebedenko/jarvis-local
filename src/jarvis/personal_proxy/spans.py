"""A character range inside one message, the only way a match is located."""

from __future__ import annotations

from typing import NamedTuple


class Span(NamedTuple):
    start: int
    end: int

    def overlaps(self, other: Span) -> bool:
        return self.start < other.end and other.start < self.end
