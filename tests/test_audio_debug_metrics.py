"""The bridge from a captured utterance to the debug transcript.

Pure wiring test: confirms the do-nothing-when-off property and that a
captured chunk's wav becomes a metrics record when it is on.
"""

import io
import json
import logging

import numpy as np
import pytest
import soundfile as sf

from jarvis.audio.debug_metrics import on_utterance_captured
from jarvis.audio.input import UtteranceChunk
from jarvis.core.config import LoggingSettings
from jarvis.core.debug_transcript import configure_debug_transcript, logger

SAMPLE_RATE = 16000


def _wav_bytes(seconds: float, amplitude: float) -> bytes:
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    samples = (amplitude * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
    buffer = io.BytesIO()
    sf.write(buffer, samples, SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


@pytest.fixture
def transcript(tmp_path):
    path = configure_debug_transcript(LoggingSettings(directory=str(tmp_path)))
    yield path
    for handler in logger.handlers:
        handler.close()
    logger.handlers = []
    logger.setLevel(logging.NOTSET)


async def test_a_captured_utterance_is_not_decoded_without_a_sink():
    """The cost of a normal run: one recording() check, no decode, no
    computation - this is the property begin_exchange() also has."""
    # An UtteranceChunk carrying bytes that are not a valid wav at all
    # proves nothing was decoded, since decoding it would raise.
    chunk = UtteranceChunk(wav_bytes=b"not a wav", start_seconds=0.0, end_seconds=1.0)

    await on_utterance_captured(chunk)  # must not raise


async def test_a_captured_utterance_becomes_one_record_when_debug_is_on(transcript):
    chunk = UtteranceChunk(
        wav_bytes=_wav_bytes(1.2, 0.4), start_seconds=0.0, end_seconds=1.2
    )

    await on_utterance_captured(chunk)

    [line] = transcript.read_text(encoding="utf-8").strip().splitlines()
    record = json.loads(line)
    assert record["kind"] == "utterance"
    assert record["duration_seconds"] == pytest.approx(1.2, abs=0.01)
    assert "peak_dbfs" in record
    assert "speech_level_dbfs" in record
    assert "noise_floor_dbfs" in record


async def test_every_captured_utterance_gets_its_own_record(transcript):
    for _ in range(3):
        await on_utterance_captured(
            UtteranceChunk(
                wav_bytes=_wav_bytes(0.5, 0.3), start_seconds=0.0, end_seconds=0.5
            )
        )

    assert len(transcript.read_text(encoding="utf-8").strip().splitlines()) == 3
