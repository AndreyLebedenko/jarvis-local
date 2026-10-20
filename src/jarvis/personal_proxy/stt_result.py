"""What a speech-to-text engine returns: the text, every word with its
probability, and the per-segment signals the engine reports."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Word:
    word: str
    start_seconds: float
    end_seconds: float
    probability: float


@dataclass(frozen=True)
class Segment:
    text: str
    avg_logprob: float
    no_speech_prob: float
    compression_ratio: float


@dataclass(frozen=True)
class Transcription:
    text: str
    words: tuple[Word, ...]
    segments: tuple[Segment, ...]
