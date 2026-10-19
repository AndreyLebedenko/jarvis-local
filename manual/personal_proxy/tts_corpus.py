"""Turns a Silero synthesis into a recording shaped like the production capture.

The production path hands Ollama 16 kHz mono chunks padded to the configured
minimum chunk length (`pad_samples_to_min_duration`, from `[vad]` in
config.toml); the TTS voices of the second corpus go through the same padding so
that they are comparable with the owner's takes.
"""

from __future__ import annotations

import io

import numpy as np
import soundfile as sf
import torch
from scipy.signal import resample_poly

from jarvis.audio.utils import pad_samples_to_min_duration, samples_to_wav_bytes
from jarvis.core.config import VadSettings

CAPTURE_RATE = 16000


def to_capture_wav(wav: bytes, vad: VadSettings | None = None) -> bytes:
    samples, rate = sf.read(io.BytesIO(wav), dtype="float32")
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    if rate != CAPTURE_RATE:
        divisor = int(np.gcd(rate, CAPTURE_RATE))
        samples = resample_poly(samples, CAPTURE_RATE // divisor, rate // divisor)
    settings = vad or VadSettings()
    padded = pad_samples_to_min_duration(
        torch.from_numpy(np.ascontiguousarray(samples, dtype=np.float32)),
        CAPTURE_RATE,
        min_duration_seconds=settings.min_chunk_seconds,
        padding_noise_rms=settings.padding_noise_rms,
    )
    return samples_to_wav_bytes(padded, CAPTURE_RATE)
