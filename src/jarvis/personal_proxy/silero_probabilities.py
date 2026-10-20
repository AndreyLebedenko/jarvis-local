"""Per-window speech probabilities from the Silero VAD the microphone capture
already uses (same library, same loader)."""

from __future__ import annotations

import numpy as np

from jarvis.personal_proxy.clip_check import require_valid_clip
from jarvis.personal_proxy.speech_guard import SpeechProbabilities

SAMPLE_RATE = 16000
WINDOW_SAMPLES = 512


class SileroSpeechProbabilities:
    """Per-window probabilities for a whole clip. It must not be given the live
    VadChunker's model instance: `audio_forward` resets the model's state."""

    def __init__(self, model: object | None = None) -> None:
        if model is None:
            from silero_vad import load_silero_vad

            model = load_silero_vad()
        self._model = model

    def __call__(self, clip: np.ndarray) -> SpeechProbabilities:
        require_valid_clip(clip)
        window_seconds = WINDOW_SAMPLES / SAMPLE_RATE
        if clip.size == 0:
            return SpeechProbabilities((), window_seconds)
        import torch

        padded = np.pad(clip, (0, max(0, WINDOW_SAMPLES - clip.size)))
        values = self._model.audio_forward(torch.from_numpy(padded), SAMPLE_RATE)
        return SpeechProbabilities(tuple(values.flatten().tolist()), window_seconds)
