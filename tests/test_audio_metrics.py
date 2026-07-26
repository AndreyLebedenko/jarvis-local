"""Utterance-quality metrics: pure numeric analysis, no hardware.

These are the numbers a throwaway script computed by hand during the
2026-07-25 voice-comprehension investigation - speech level and noise
floor separated a comprehended utterance from an unintelligible one,
while peak and RMS alone did not.
"""

import io

import numpy as np
import pytest
import soundfile as sf

from jarvis.audio.metrics import (
    UtteranceMetrics,
    compute_utterance_metrics,
    utterance_metrics_from_wav_bytes,
)

SAMPLE_RATE = 16000


def _sine(seconds: float, amplitude: float, frequency: float = 440.0) -> np.ndarray:
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    return (amplitude * np.sin(2 * np.pi * frequency * t)).astype(np.float64)


def _sine_rms_dbfs(amplitude: float) -> float:
    """A sine wave's RMS is amplitude / sqrt(2) - the closed-form value the
    frame-RMS percentiles should land on for a clip with no quiet/loud
    transition inside a single frame."""
    return 20 * np.log10(amplitude / np.sqrt(2))


def test_duration_matches_sample_count_and_rate():
    metrics = compute_utterance_metrics(_sine(1.5, 0.5), SAMPLE_RATE)

    assert metrics.duration_seconds == pytest.approx(1.5)


def test_a_full_scale_sine_peaks_near_zero_dbfs():
    metrics = compute_utterance_metrics(_sine(1.0, 1.0), SAMPLE_RATE)

    assert metrics.peak_dbfs == pytest.approx(0.0, abs=0.1)


def test_digital_silence_reports_a_floor_instead_of_negative_infinity():
    metrics = compute_utterance_metrics(np.zeros(SAMPLE_RATE), SAMPLE_RATE)

    assert metrics.peak_dbfs < -150
    assert metrics.rms_dbfs < -150
    assert metrics.speech_level_dbfs < -150
    assert metrics.noise_floor_dbfs < -150


def test_empty_samples_do_not_crash_and_report_the_floor():
    metrics = compute_utterance_metrics(np.zeros(0), SAMPLE_RATE)

    assert metrics.duration_seconds == 0.0
    assert metrics.peak_dbfs < -150


def test_a_clip_shorter_than_one_frame_does_not_crash():
    """20 ms at 16 kHz is 320 samples; five samples is not even one frame."""
    metrics = compute_utterance_metrics(_sine(0.0003, 0.5), SAMPLE_RATE)

    assert metrics.duration_seconds > 0.0
    assert metrics.peak_dbfs > -150


def test_speech_level_and_noise_floor_separate_a_loud_region_from_a_quiet_one():
    """The measurement the investigation actually needed: two regions of
    the same clip at different levels must be told apart, not averaged
    into one number the way overall RMS would."""
    quiet = _sine(2.0, 0.001)
    loud = _sine(2.0, 0.3)
    metrics = compute_utterance_metrics(np.concatenate([quiet, loud]), SAMPLE_RATE)

    assert metrics.speech_level_dbfs > metrics.noise_floor_dbfs + 20
    assert metrics.speech_level_dbfs == pytest.approx(_sine_rms_dbfs(0.3), abs=0.5)
    assert metrics.noise_floor_dbfs == pytest.approx(_sine_rms_dbfs(0.001), abs=0.5)


def test_a_uniformly_loud_clip_has_a_small_gap_between_speech_and_floor():
    """The negative control for the test above: a clip with no quiet
    region at all must not manufacture a large gap out of noise."""
    metrics = compute_utterance_metrics(_sine(2.0, 0.3), SAMPLE_RATE)

    assert metrics.speech_level_dbfs - metrics.noise_floor_dbfs < 3.0


def test_utterance_metrics_from_wav_bytes_matches_direct_computation():
    samples = _sine(1.0, 0.4)
    buffer = io.BytesIO()
    sf.write(
        buffer, samples.astype(np.float32), SAMPLE_RATE, format="WAV", subtype="PCM_16"
    )

    from_wav = utterance_metrics_from_wav_bytes(buffer.getvalue())
    direct = compute_utterance_metrics(samples, SAMPLE_RATE)

    # PCM_16 quantizes, so this is a close match rather than an exact one.
    assert from_wav.duration_seconds == pytest.approx(direct.duration_seconds, abs=0.01)
    assert from_wav.peak_dbfs == pytest.approx(direct.peak_dbfs, abs=0.5)
    assert from_wav.speech_level_dbfs == pytest.approx(
        direct.speech_level_dbfs, abs=0.5
    )


def test_a_stereo_wav_is_analyzed_from_its_first_channel_only():
    """VadChunker's own capture path is mono; a stereo fixture should still
    produce one number per metric rather than an ambiguous pair."""
    left = _sine(1.0, 0.5).astype(np.float32)
    right = _sine(1.0, 0.01).astype(np.float32)
    buffer = io.BytesIO()
    sf.write(
        buffer,
        np.stack([left, right], axis=1),
        SAMPLE_RATE,
        format="WAV",
        subtype="PCM_16",
    )

    metrics = utterance_metrics_from_wav_bytes(buffer.getvalue())

    assert metrics.peak_dbfs == pytest.approx(20 * np.log10(0.5), abs=0.5)


def test_utterance_metrics_is_a_plain_frozen_dataclass():
    """asdict() is what the debug bridge serializes - this pins that the
    shape stays flat and JSON-serializable without a custom encoder."""
    from dataclasses import asdict, fields

    metrics = compute_utterance_metrics(_sine(0.5, 0.2), SAMPLE_RATE)

    assert set(asdict(metrics)) == {f.name for f in fields(UtteranceMetrics)}
    assert all(isinstance(value, float) for value in asdict(metrics).values())
