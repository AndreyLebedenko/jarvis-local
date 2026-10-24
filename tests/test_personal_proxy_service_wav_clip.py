import io

import numpy as np
import pytest
import soundfile as sf

from jarvis.personal_proxy.stt.clip_check import require_valid_clip
from jarvis.personal_proxy.stt.wav_clip import WavClipError, wav_to_clip


def _wav(samples, rate=16000, subtype="PCM_16"):
    buffer = io.BytesIO()
    sf.write(buffer, samples, rate, format="WAV", subtype=subtype)
    return buffer.getvalue()


def test_a_mono_16khz_wav_becomes_a_valid_float32_clip():
    samples = np.linspace(-0.5, 0.5, 1600, dtype=np.float32)

    clip = wav_to_clip(_wav(samples))

    require_valid_clip(clip)
    assert clip.dtype == np.float32
    assert clip.shape == (1600,)
    assert np.allclose(clip, samples, atol=1e-3)


def test_a_stereo_wav_is_averaged_to_mono():
    left = np.full(800, 0.5, dtype=np.float32)
    right = np.full(800, -0.5, dtype=np.float32)

    clip = wav_to_clip(_wav(np.stack([left, right], axis=1)))

    assert clip.shape == (800,)
    assert np.allclose(clip, 0.0, atol=1e-3)


def test_a_zero_length_wav_is_refused():
    with pytest.raises(WavClipError):
        wav_to_clip(_wav(np.zeros(0, dtype=np.float32)))


def test_a_wav_of_exactly_the_longest_accepted_duration_is_taken():
    clip = wav_to_clip(_wav(np.zeros(60 * 16000, dtype=np.float32)))

    assert clip.shape == (60 * 16000,)


def test_a_wav_longer_than_sixty_seconds_is_refused():
    with pytest.raises(WavClipError):
        wav_to_clip(_wav(np.zeros(60 * 16000 + 1, dtype=np.float32)))


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_a_non_finite_sample_is_refused(bad):
    samples = np.zeros(1600, dtype=np.float32)
    samples[10] = bad

    with pytest.raises(WavClipError):
        wav_to_clip(_wav(samples, subtype="FLOAT"))


@pytest.mark.parametrize("container", ["FLAC", "OGG", "AIFF"])
def test_a_container_other_than_wav_is_refused(container):
    buffer = io.BytesIO()
    subtype = "VORBIS" if container == "OGG" else "PCM_16"
    sf.write(
        buffer,
        np.zeros(1600, dtype=np.float32),
        16000,
        format=container,
        subtype=subtype,
    )

    with pytest.raises(WavClipError):
        wav_to_clip(buffer.getvalue())


@pytest.mark.parametrize("rate", [8000, 44100])
def test_another_sample_rate_is_refused_not_resampled(rate):
    with pytest.raises(WavClipError):
        wav_to_clip(_wav(np.zeros(100, dtype=np.float32), rate=rate))


@pytest.mark.parametrize("data", [b"", b"not a wav at all", b"RIFF\x00\x00"])
def test_bytes_that_are_not_a_wav_are_refused(data):
    with pytest.raises(WavClipError):
        wav_to_clip(data)


def test_the_error_carries_no_detail_of_the_input():
    with pytest.raises(WavClipError) as raised:
        wav_to_clip(b"SECRET-NOT-A-WAV")

    assert "SECRET" not in repr(raised.value)
    assert "SECRET" not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True
