"""The seam between the pipeline and a speech-to-text engine."""

from __future__ import annotations

from typing import Protocol

import numpy as np

from jarvis.personal_proxy.stt.stt_result import Transcription


class SpeechEngineLoadError(Exception):
    """The engine cannot be loaded; the message says what to do about it."""


class MissingSpeechDependencyError(SpeechEngineLoadError):
    pass


class SpeechModelUnavailableError(SpeechEngineLoadError):
    pass


class SpeechDeviceError(SpeechEngineLoadError):
    pass


class SpeechEngine(Protocol):
    def transcribe(self, clip: np.ndarray) -> Transcription:
        """`clip` is mono 16 kHz float32, the format the capture path delivers."""
        ...
