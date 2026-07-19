"""Format-gate check for task-v1.6.0-1: which audio containers the
already-declared project stack (soundfile/torchaudio, both already in
requirements.txt) can decode without adding a new dependency.

Pure and deterministic - no Ollama, no hardware, no network. WAV is the
existing baseline (audio/a1.wav, also used by test_audio_in.py). MP3 is
round-tripped in-memory using soundfile itself (libsndfile 1.1+ bundles a
native MP3 decoder/encoder, confirmed present via
soundfile.available_formats()). M4A/AAC cannot be produced by anything in
the declared stack, so audio/sample.m4a is a small pre-built fixture (built
once with PyAV, a tool incidentally available on the authoring machine, not
a project dependency) committed purely to prove the negative: the stack
raises on a real M4A file rather than silently misreading it.

See tasks/attachment-policy-v1.6.0.md for the resulting policy decision.
"""

import io

import numpy as np
import pytest
import soundfile as sf
import torchaudio

SAMPLE_RATE = 16000


def test_wav_decodes_via_soundfile():
    samples, sample_rate = sf.read("audio/a1.wav")

    assert sample_rate > 0
    assert len(samples) > 0


def test_mp3_round_trips_through_existing_soundfile_stack():
    phase = 2 * np.pi * 440 * np.arange(SAMPLE_RATE) / SAMPLE_RATE
    tone = (0.2 * np.sin(phase)).astype(np.float32)

    mp3_buffer = io.BytesIO()
    sf.write(mp3_buffer, tone, SAMPLE_RATE, format="MP3")
    mp3_bytes = mp3_buffer.getvalue()

    assert len(mp3_bytes) > 0

    decoded, decoded_rate = sf.read(io.BytesIO(mp3_bytes))
    assert decoded_rate == SAMPLE_RATE
    assert len(decoded) > 0

    waveform, torchaudio_rate = torchaudio.load(io.BytesIO(mp3_bytes))
    assert torchaudio_rate == SAMPLE_RATE
    assert waveform.shape[-1] > 0


def test_m4a_is_not_decodable_by_the_existing_stack():
    with pytest.raises(sf.LibsndfileError):
        sf.read("audio/sample.m4a")

    with pytest.raises(sf.LibsndfileError):
        torchaudio.load("audio/sample.m4a")


def test_soundfile_available_formats_confirms_mp3_but_not_m4a():
    formats = sf.available_formats()

    assert "MP3" in formats
    assert "M4A" not in formats
    assert "MP4" not in formats
    assert "AAC" not in formats
