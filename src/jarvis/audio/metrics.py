"""Utterance-quality metrics for the debug transcript.

During the 2026-07-25 voice-comprehension investigation, exactly these
numbers - not peak level, which was misleading on its own - separated a
comprehended utterance from an unintelligible one, and nothing recorded
them at capture time: they were reconstructed by hand from journal wav
files, after the fact, with a throwaway script. This module computes them
where the utterance is actually captured.

No project-module dependencies by design, matching audio/utils.py's own
rule: this is pure numeric analysis over samples already in memory, with
nothing to test that needs a live microphone.
"""

import io
from dataclasses import dataclass

import numpy as np
import soundfile as sf

# 20 ms frames, matching the ad hoc analysis run during the investigation.
FRAME_SECONDS = 0.02

# Floor before log10, so true digital silence reports a large negative
# number instead of -inf.
_MIN_LINEAR = 1e-9


@dataclass(frozen=True)
class UtteranceMetrics:
    duration_seconds: float
    peak_dbfs: float
    rms_dbfs: float
    # 95th/20th percentile of 20 ms frame RMS: loud frames versus quiet
    # ones within the same clip. This is what separated intelligible from
    # unintelligible during the investigation - overall peak/RMS did not,
    # since a comprehended utterance was quieter by peak than a refused
    # one on the same evening.
    speech_level_dbfs: float
    noise_floor_dbfs: float


def _dbfs(linear: float) -> float:
    return 20.0 * float(np.log10(max(linear, _MIN_LINEAR)))


def _frame_rms(samples: np.ndarray, frame_len: int) -> np.ndarray:
    sample_count = len(samples)
    usable = sample_count - (sample_count % frame_len)
    frames = (
        samples[:usable].reshape(-1, frame_len)
        if usable >= frame_len
        else samples.reshape(1, -1)
    )
    return np.sqrt((frames**2).mean(axis=1))


def compute_utterance_metrics(
    samples: np.ndarray, sample_rate: int
) -> UtteranceMetrics:
    """samples: mono, normalized float in [-1, 1] - full scale is 1.0, so
    dBFS is computed directly against it. This is what soundfile.read()
    returns by default (utterance_metrics_from_wav_bytes()'s path), not
    what a raw int16 PCM buffer looks like: an unnormalized int16 array
    would report a peak around +90 dBFS instead of ~0. Do not widen this
    contract to accept raw integer PCM without normalizing first."""
    sample_count = len(samples)
    if sample_count == 0:
        floor = _dbfs(0.0)
        return UtteranceMetrics(0.0, floor, floor, floor, floor)

    samples = samples.astype(np.float64)
    frame_len = max(1, int(sample_rate * FRAME_SECONDS))
    frame_rms = _frame_rms(samples, frame_len)

    return UtteranceMetrics(
        duration_seconds=sample_count / sample_rate,
        peak_dbfs=_dbfs(float(np.max(np.abs(samples)))),
        rms_dbfs=_dbfs(float(np.sqrt((samples**2).mean()))),
        speech_level_dbfs=_dbfs(float(np.percentile(frame_rms, 95))),
        noise_floor_dbfs=_dbfs(float(np.percentile(frame_rms, 20))),
    )


def utterance_metrics_from_wav_bytes(wav_bytes: bytes) -> UtteranceMetrics:
    """Only the first channel is analyzed - VadChunker's own capture path
    is mono, and a stereo source (a manually supplied fixture, say) should
    still produce one number per metric rather than an ambiguous pair."""
    samples, sample_rate = sf.read(io.BytesIO(wav_bytes))
    if samples.ndim > 1:
        samples = samples[:, 0]
    return compute_utterance_metrics(samples, sample_rate)
