"""What the restoration stage yields per sentence. The text is an original
value in places, so it stays out of every repr."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RestorationMethod(Enum):
    PASSTHROUGH = "passthrough"
    MODEL = "model"
    SUBSTITUTED = "substituted"


@dataclass(frozen=True)
class RestoredSentence:
    text: str = field(repr=False)
    method: RestorationMethod
    unresolved_placeholders: bool
