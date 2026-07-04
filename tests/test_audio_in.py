import io

import pytest
import soundfile as sf
import torch
from silero_vad import load_silero_vad, read_audio

from audio_in import SAMPLE_RATE, AudioInput, UtteranceChunk, VadChunker
from bus import EventBus
from config import VadSettings


@pytest.fixture(scope="module")
def vad_model():
    return load_silero_vad()


class _AlwaysSpeechModel:
    def __call__(self, chunk, sampling_rate):
        return torch.tensor(0.99)

    def reset_states(self):
        pass


def test_a1_fixtures_internal_breath_pause_is_merged_by_default(vad_model):
    """a1.wav has an internal ~0.3 s pause (Silero returns it as two raw
    segments). With the default request_end_pause_seconds (2.0 s), that
    pause is a mid-request breath, not the end of the request, so it must
    be merged into a single utterance."""
    samples = read_audio("audio/a1.wav", sampling_rate=SAMPLE_RATE)
    chunker = VadChunker(VadSettings(), model=vad_model)

    chunks = chunker.chunk(samples)

    assert len(chunks) == 1
    assert chunks[0].start_seconds == pytest.approx(0.1, abs=0.05)
    assert chunks[0].end_seconds == pytest.approx(5.6, abs=0.05)


def test_a1_fixture_stays_split_with_a_short_pause_threshold(vad_model):
    """With a request_end_pause_seconds shorter than a1's internal ~0.3 s
    gap, the two raw segments must NOT be merged - confirms merging is
    genuinely driven by config, not hardcoded."""
    samples = read_audio("audio/a1.wav", sampling_rate=SAMPLE_RATE)
    chunker = VadChunker(VadSettings(request_end_pause_seconds=0.1), model=vad_model)

    chunks = chunker.chunk(samples)

    assert len(chunks) == 2
    assert chunks[0].start_seconds == pytest.approx(0.1, abs=0.05)
    assert chunks[0].end_seconds == pytest.approx(2.8, abs=0.05)
    assert chunks[1].start_seconds == pytest.approx(3.1, abs=0.05)
    assert chunks[1].end_seconds == pytest.approx(5.6, abs=0.05)


def test_a2_fixture_produces_expected_utterance_boundaries(vad_model):
    samples = read_audio("audio/a2.wav", sampling_rate=SAMPLE_RATE)
    chunker = VadChunker(VadSettings(), model=vad_model)

    chunks = chunker.chunk(samples)

    assert len(chunks) == 1
    assert chunks[0].start_seconds == pytest.approx(0.1, abs=0.05)
    assert chunks[0].end_seconds == pytest.approx(5.1, abs=0.05)


def test_silence_only_produces_zero_chunks(vad_model):
    samples = torch.zeros(SAMPLE_RATE * 3)
    chunker = VadChunker(VadSettings(), model=vad_model)

    assert chunker.chunk(samples) == []


def test_long_utterance_is_split_at_max_chunk_seconds():
    settings = VadSettings(max_chunk_seconds=30)
    chunker = VadChunker(settings, model=_AlwaysSpeechModel())
    samples = torch.zeros(SAMPLE_RATE * 40)

    chunks = chunker.chunk(samples)

    assert len(chunks) >= 2
    assert all(c.end_seconds - c.start_seconds <= 30.0 + 1e-6 for c in chunks)
    assert sum(c.end_seconds - c.start_seconds for c in chunks) == pytest.approx(40.0, abs=0.5)


def test_chunk_wav_bytes_round_trip_to_same_sample_count(vad_model):
    samples = read_audio("audio/a2.wav", sampling_rate=SAMPLE_RATE)
    chunker = VadChunker(VadSettings(), model=vad_model)

    [chunk] = chunker.chunk(samples)
    decoded, sample_rate = sf.read(io.BytesIO(chunk.wav_bytes))

    assert sample_rate == SAMPLE_RATE
    expected_samples = int((chunk.end_seconds - chunk.start_seconds) * SAMPLE_RATE)
    assert abs(len(decoded) - expected_samples) <= 1


async def test_publish_from_samples_publishes_expected_chunks(vad_model):
    bus = EventBus()
    received = []

    async def on_chunk(chunk: UtteranceChunk) -> None:
        received.append(chunk)

    bus.subscribe(UtteranceChunk, on_chunk)

    chunker = VadChunker(VadSettings(), model=vad_model)
    audio_input = AudioInput(bus=bus, chunker=chunker)
    samples = read_audio("audio/a2.wav", sampling_rate=SAMPLE_RATE)

    await audio_input.publish_from_samples(samples)

    assert len(received) == 1
    assert received[0].start_seconds == pytest.approx(0.1, abs=0.05)
    assert isinstance(received[0].wav_bytes, bytes)
    assert len(received[0].wav_bytes) > 0


async def test_publish_from_samples_publishes_one_merged_chunk_for_a1(vad_model):
    bus = EventBus()
    received = []

    async def on_chunk(chunk: UtteranceChunk) -> None:
        received.append(chunk)

    bus.subscribe(UtteranceChunk, on_chunk)

    chunker = VadChunker(VadSettings(), model=vad_model)
    audio_input = AudioInput(bus=bus, chunker=chunker)
    samples = read_audio("audio/a1.wav", sampling_rate=SAMPLE_RATE)

    await audio_input.publish_from_samples(samples)

    assert len(received) == 1
    assert isinstance(received[0].wav_bytes, bytes) and len(received[0].wav_bytes) > 0


async def test_publish_from_samples_publishes_nothing_for_silence(vad_model):
    bus = EventBus()
    received = []

    async def on_chunk(chunk: UtteranceChunk) -> None:
        received.append(chunk)

    bus.subscribe(UtteranceChunk, on_chunk)

    chunker = VadChunker(VadSettings(), model=vad_model)
    audio_input = AudioInput(bus=bus, chunker=chunker)

    await audio_input.publish_from_samples(torch.zeros(SAMPLE_RATE * 3))

    assert received == []


async def test_publish_from_samples_publishes_multiple_chunks_within_cap():
    settings = VadSettings(max_chunk_seconds=30)
    bus = EventBus()
    received = []

    async def on_chunk(chunk: UtteranceChunk) -> None:
        received.append(chunk)

    bus.subscribe(UtteranceChunk, on_chunk)

    chunker = VadChunker(settings, model=_AlwaysSpeechModel())
    audio_input = AudioInput(bus=bus, chunker=chunker)

    await audio_input.publish_from_samples(torch.zeros(SAMPLE_RATE * 40))

    assert len(received) >= 2
    assert all(c.end_seconds - c.start_seconds <= 30.0 + 1e-6 for c in received)
