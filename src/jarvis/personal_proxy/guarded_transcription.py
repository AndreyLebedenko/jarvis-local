"""Transcription that keeps clips without enough speech away from the engine."""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np

from jarvis.personal_proxy.clip_check import require_valid_clip
from jarvis.personal_proxy.speech_guard import (
    NoSpeech,
    SpeechGuardError,
    SpeechProbabilities,
    speech_seconds,
)
from jarvis.personal_proxy.stt_engine import SpeechEngine
from jarvis.personal_proxy.stt_result import Transcription

ProbabilitySource = Callable[[np.ndarray], SpeechProbabilities]


def transcribe_guarded(
    clip: np.ndarray,
    engine: SpeechEngine,
    probability_source: ProbabilitySource,
    *,
    vad_threshold: float,
    minimum_speech_seconds: float,
) -> Transcription | NoSpeech:
    if not math.isfinite(vad_threshold) or not 0.0 <= vad_threshold <= 1.0:
        raise SpeechGuardError(
            f"vad_threshold must be within [0, 1], got {vad_threshold}"
        )
    require_valid_clip(clip)
    try:
        probabilities = probability_source(clip)
    except Exception as error:
        # from None: the original message may carry paths or audio details.
        raise SpeechGuardError(
            f"the speech presence check failed ({type(error).__name__})"
        ) from None
    heard = speech_seconds(probabilities, vad_threshold)
    if heard < minimum_speech_seconds:
        return NoSpeech(speech_seconds=heard, required_seconds=minimum_speech_seconds)
    return engine.transcribe(clip)
