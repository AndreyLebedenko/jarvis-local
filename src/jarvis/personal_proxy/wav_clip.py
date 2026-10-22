"""Turns the WAV bytes of an utterance into the clip the speech stages take:
mono float32 at 16 kHz. Anything else is refused, not converted: another
container or sample rate, no audio, audio longer than the capture path ever
produces, or a sample that is not a finite number."""

from __future__ import annotations

import io

import numpy as np
import soundfile as sf

CLIP_SAMPLE_RATE = 16000
MAX_CLIP_SECONDS = 60
_WAV_FORMAT = "WAV"


class WavClipError(Exception):
    """The bytes are not a WAV the speech stages can take."""

    def __init__(self) -> None:
        super().__init__("the utterance is not a usable 16 kHz WAV")


def wav_to_clip(wav: bytes) -> np.ndarray:
    try:
        with sf.SoundFile(io.BytesIO(wav)) as audio:
            _require_acceptable(audio)
            samples = audio.read(dtype="float32", always_2d=True)
    except WavClipError:
        raise
    except Exception:
        raise WavClipError from None
    clip = np.ascontiguousarray(samples.mean(axis=1), dtype=np.float32)
    if not np.isfinite(clip).all():
        raise WavClipError
    return clip


def _require_acceptable(audio: sf.SoundFile) -> None:
    if audio.format != _WAV_FORMAT or audio.samplerate != CLIP_SAMPLE_RATE:
        raise WavClipError
    if not 0 < audio.frames <= MAX_CLIP_SECONDS * CLIP_SAMPLE_RATE:
        raise WavClipError
