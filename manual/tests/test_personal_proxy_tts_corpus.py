import io

import numpy as np
import soundfile as sf

from jarvis.core.config import VadSettings
from manual.personal_proxy.tts_corpus import CAPTURE_RATE, to_capture_wav


def _wav(seconds, rate, value=0.1):
    buffer = io.BytesIO()
    samples = np.full(int(rate * seconds), value, dtype=np.float32)
    sf.write(buffer, samples, rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


PADDED = VadSettings(min_chunk_seconds=3.0, padding_noise_rms=0.002)
UNPADDED = VadSettings(min_chunk_seconds=0, padding_noise_rms=0.0)


def _read(wav):
    samples, rate = sf.read(io.BytesIO(wav), dtype="float32")
    return samples, rate


def test_output_is_16khz_mono_pcm16_like_the_production_capture():
    samples, rate = _read(to_capture_wav(_wav(4.0, 24000)))

    assert rate == CAPTURE_RATE
    assert samples.ndim == 1
    assert abs(len(samples) / rate - 4.0) < 0.01


def test_a_short_clip_is_padded_to_the_minimum_chunk_length():
    samples, rate = _read(to_capture_wav(_wav(1.0, 24000), PADDED))

    assert abs(len(samples) / rate - 3.0) < 0.01


def test_a_long_clip_is_not_padded():
    samples, rate = _read(to_capture_wav(_wav(5.0, 48000), PADDED))

    assert abs(len(samples) / rate - 5.0) < 0.01


def test_conversion_is_deterministic():
    wav = _wav(1.0, 24000)

    assert to_capture_wav(wav, PADDED) == to_capture_wav(wav, PADDED)


def test_a_configuration_without_padding_keeps_a_short_clip_short():
    samples, rate = _read(to_capture_wav(_wav(1.0, 24000), UNPADDED))

    assert abs(len(samples) / rate - 1.0) < 0.01
