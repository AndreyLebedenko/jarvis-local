"""Decides from a series of speech probabilities whether a clip holds enough
speech to be worth transcribing."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


class SpeechGuardError(Exception):
    """The presence check could not be completed; nothing was transcribed."""


@dataclass(frozen=True)
class SpeechProbabilities:
    """One probability per consecutive window of `window_seconds`."""

    values: Sequence[float]
    window_seconds: float


@dataclass(frozen=True)
class NoSpeech:
    speech_seconds: float
    required_seconds: float


def speech_seconds(probabilities: SpeechProbabilities, threshold: float) -> float:
    windows = sum(1 for value in probabilities.values if value >= threshold)
    return windows * probabilities.window_seconds
