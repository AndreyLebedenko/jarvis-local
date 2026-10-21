"""Reads the judge's constrained JSON answer."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class JudgeResult:
    confidence: float
    fragments: tuple[str, ...]


def parse_judge(reply: str) -> JudgeResult | None:
    """None for anything that is not the expected structure."""
    try:
        document = json.loads(reply)
        confidence = document["confidence"]
        fragments = document["uncertain_fragments"]
    except (ValueError, KeyError, TypeError, RecursionError):
        return None
    if isinstance(confidence, bool) or not isinstance(confidence, int | float):
        return None
    if not 0.0 <= confidence <= 1.0:
        return None
    if not isinstance(fragments, list) or not all(
        isinstance(fragment, str) for fragment in fragments
    ):
        return None
    return JudgeResult(float(confidence), tuple(fragments))
