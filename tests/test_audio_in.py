import asyncio
import io
import threading
from types import SimpleNamespace

import numpy as np
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
    """a1.wav is a synthetic TTS fixture with an internal pause (Silero returns it as two raw
    segments). With the default request_end_pause_seconds (2.0 s), that
    pause is a mid-request breath, not the end of the request, so it must
    be merged into a single utterance."""
    samples = read_audio("audio/a1.wav", sampling_rate=SAMPLE_RATE)
    chunker = VadChunker(VadSettings(), model=vad_model)

    chunks = chunker.chunk(samples)

    assert len(chunks) == 1
    assert chunks[0].start_seconds == pytest.approx(0.5, abs=0.05)
    assert chunks[0].end_seconds == pytest.approx(10.4, abs=0.05)


def test_a1_fixture_stays_split_with_a_short_pause_threshold(vad_model):
    """With a request_end_pause_seconds shorter than a1's internal pause
    gap, the two raw segments must NOT be merged - confirms merging is
    genuinely driven by config, not hardcoded."""
    samples = read_audio("audio/a1.wav", sampling_rate=SAMPLE_RATE)
    chunker = VadChunker(VadSettings(request_end_pause_seconds=0.1), model=vad_model)

    chunks = chunker.chunk(samples)

    assert len(chunks) == 2
    assert chunks[0].start_seconds == pytest.approx(0.5, abs=0.05)
    assert chunks[0].end_seconds == pytest.approx(5.2, abs=0.05)
    assert chunks[1].start_seconds == pytest.approx(6.5, abs=0.05)
    assert chunks[1].end_seconds == pytest.approx(10.4, abs=0.05)


def test_a2_fixture_produces_expected_utterance_boundaries(vad_model):
    samples = read_audio("audio/a2.wav", sampling_rate=SAMPLE_RATE)
    chunker = VadChunker(VadSettings(), model=vad_model)

    chunks = chunker.chunk(samples)

    assert len(chunks) == 1
    assert chunks[0].start_seconds == pytest.approx(0.3, abs=0.05)
    assert chunks[0].end_seconds == pytest.approx(4.7, abs=0.05)


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
    assert received[0].start_seconds == pytest.approx(0.3, abs=0.05)
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


# --- task-09: microphone sleep mode ------------------------------------------


class _FakeChunker:
    """A minimal stand-in for VadChunker that never finds speech. Used for
    tests about the sleep/wake state machine itself, where running the
    real Silero model would only add noise and load time."""

    def __init__(self, request_end_pause_seconds: float = 2.0) -> None:
        self.settings = SimpleNamespace(request_end_pause_seconds=request_end_pause_seconds)

    def chunk(self, samples):
        return []


class _FreeRunningFakeStream:
    """Free-running fake sd.InputStream: read() returns immediately, so
    tests only need to bound real time loosely (asyncio.sleep windows),
    not synchronize read-by-read."""

    def __init__(self, block_samples: int) -> None:
        self.read_calls = 0
        self.stop_calls = 0
        self.start_calls = 0
        self._block_samples = block_samples

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self, block_samples):
        self.read_calls += 1
        return np.zeros((block_samples, 1), dtype=np.float32), False

    def stop(self):
        self.stop_calls += 1

    def start(self):
        self.start_calls += 1


async def _run_until_cancelled(task):
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_sleeping_stops_new_reads_from_the_stream():
    fake_stream = _FreeRunningFakeStream(block_samples=160)
    audio_input = AudioInput(
        bus=EventBus(), chunker=_FakeChunker(), stream_factory=lambda bs: fake_stream
    )

    task = asyncio.create_task(audio_input.run_microphone_loop(poll_interval_seconds=0.01))
    await asyncio.sleep(0.05)
    assert fake_stream.read_calls > 0

    await audio_input.sleep()
    # Let any read already in flight when sleep() was called complete, and
    # the sleep branch run (the awake-check happens once per iteration,
    # before the read call, so one in-flight read can still land here).
    await asyncio.sleep(0.05)
    reads_once_asleep = fake_stream.read_calls
    await asyncio.sleep(0.05)

    assert fake_stream.read_calls == reads_once_asleep
    assert fake_stream.stop_calls >= 1

    await _run_until_cancelled(task)


async def test_asleep_loop_never_reads_and_blocks_without_busy_polling():
    fake_stream = _FreeRunningFakeStream(block_samples=160)
    audio_input = AudioInput(
        bus=EventBus(), chunker=_FakeChunker(), stream_factory=lambda bs: fake_stream
    )
    await audio_input.sleep()

    task = asyncio.create_task(audio_input.run_microphone_loop(poll_interval_seconds=0.01))
    await asyncio.sleep(0.05)

    assert fake_stream.read_calls == 0

    await _run_until_cancelled(task)


async def test_waking_resumes_capture_on_the_same_stream_instance():
    fake_stream = _FreeRunningFakeStream(block_samples=160)
    factory_calls = []

    def stream_factory(block_samples):
        factory_calls.append(fake_stream)
        return fake_stream

    audio_input = AudioInput(bus=EventBus(), chunker=_FakeChunker(), stream_factory=stream_factory)

    task = asyncio.create_task(audio_input.run_microphone_loop(poll_interval_seconds=0.01))
    await asyncio.sleep(0.02)

    await audio_input.sleep()
    await asyncio.sleep(0.02)
    assert fake_stream.stop_calls >= 1

    await audio_input.wake()
    await asyncio.sleep(0.02)

    assert len(factory_calls) == 1
    assert fake_stream.start_calls >= 1

    await _run_until_cancelled(task)


class _SteppedFakeStream:
    """A fake sd.InputStream that serves pre-loaded blocks one at a time.
    Each read() blocks on a threading.Event gate until the test releases
    it, and signals a separate "waiting" event the instant it starts
    blocking - so the test can deterministically observe "the loop has
    just reached this read call and parked there" before deciding what to
    do next (asyncio.to_thread runs read() in a real thread, so blocking
    waits here work correctly without stalling the event loop)."""

    def __init__(self, blocks: list[np.ndarray], fill_value: np.ndarray) -> None:
        self._blocks = list(blocks)
        self._fill_value = fill_value
        self.read_calls = 0
        self.stop_calls = 0
        self.start_calls = 0
        self._gate = threading.Event()
        self._waiting = threading.Event()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def release_next_read(self) -> None:
        self._gate.set()

    def block_until_read_is_pending(self, timeout: float) -> None:
        if not self._waiting.wait(timeout):
            raise AssertionError("read() was never called")
        self._waiting.clear()

    def read(self, block_samples):
        self._waiting.set()
        self._gate.wait()
        self._gate.clear()
        self.read_calls += 1
        block = self._blocks.pop(0) if self._blocks else self._fill_value
        return block.reshape(-1, 1), False

    def stop(self):
        self.stop_calls += 1

    def start(self):
        self.start_calls += 1


async def _wait_until_read_pending(fake_stream, timeout=2.0):
    await asyncio.to_thread(fake_stream.block_until_read_is_pending, timeout)


async def _wait_until(condition, timeout=2.0, message="condition never became true"):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while not condition():
        if loop.time() > deadline:
            raise AssertionError(message)
        await asyncio.sleep(0.005)


async def test_sleep_resets_buffer_so_pre_sleep_audio_never_merges_with_post_wake_audio(vad_model):
    """Regression for the buffer-reset requirement: a2's speech is fed but
    left unconfirmed (no trailing silence yet) when sleep is triggered - it
    must be discarded, not merged with a1's speech fed after wake. If the
    buffer were not reset, a2's raw samples would still be sitting there and
    the concatenated a2+a1 audio (no real gap between them) would VAD/merge
    into one long utterance instead of a1's alone.

    _wait_until_read_pending() is used throughout instead of real-time
    sleeps to eliminate the race between "the loop's next read call has
    already started" and "sleep() takes effect before that call starts":
    sleep() is only ever issued while the loop is confirmed to be parked
    inside a read() call, so it deterministically takes effect on the
    following iteration, not the current one.
    """
    a2_samples = read_audio("audio/a2.wav", sampling_rate=SAMPLE_RATE).numpy()
    a1_samples = read_audio("audio/a1.wav", sampling_rate=SAMPLE_RATE).numpy()
    # This filler is what the loop's already-pending read (parked before
    # sleep() is called, see below) actually receives - short enough that
    # a2 + filler still falls short of the 2.0s pause-to-confirm threshold.
    leaked_read_filler = np.zeros(int(SAMPLE_RATE * 0.3), dtype=np.float32)
    silence_block = np.zeros(SAMPLE_RATE, dtype=np.float32)  # 1s of silence per subsequent read

    fake_stream = _SteppedFakeStream(
        blocks=[a2_samples, leaked_read_filler, a1_samples], fill_value=silence_block
    )

    bus = EventBus()
    received = []

    async def on_chunk(chunk: UtteranceChunk) -> None:
        received.append(chunk)

    bus.subscribe(UtteranceChunk, on_chunk)

    chunker = VadChunker(VadSettings(), model=vad_model)
    audio_input = AudioInput(bus=bus, chunker=chunker, stream_factory=lambda bs: fake_stream)

    task = asyncio.create_task(audio_input.run_microphone_loop(poll_interval_seconds=1.0))

    # Read #1: a2's whole clip lands in the buffer, with no trailing silence
    # yet - still "extending", not yet confirmed/published.
    await _wait_until_read_pending(fake_stream)
    fake_stream.release_next_read()
    await _wait_until(lambda: fake_stream.read_calls >= 1)
    assert received == []

    # Confirm the loop has fully processed read #1 and is now parked on its
    # next read attempt, still awake - only then is it safe to sleep().
    await _wait_until_read_pending(fake_stream)
    assert received == []

    await audio_input.sleep()

    # This queued read is the one the loop was already parked on above; it
    # completes as if still awake (the awake-check only runs once per
    # iteration, before the read call) and adds the short filler - still
    # not enough trailing silence for a2's utterance to be confirmed.
    fake_stream.release_next_read()
    await _wait_until(
        lambda: fake_stream.stop_calls >= 1,
        message="loop never stopped the stream after sleep()",
    )
    assert received == []  # a2 + short filler is still short of the 2.0s pause

    await audio_input.wake()

    # Read #3: a1's whole clip, into what must now be a fresh buffer.
    await _wait_until_read_pending(fake_stream)
    fake_stream.release_next_read()
    await _wait_until(lambda: fake_stream.read_calls >= 3)
    assert received == []  # a1 alone is also still short of the pause threshold

    # Reads #4+: trailing silence until a1's utterance accumulates enough
    # trailing pause (request_end_pause_seconds) to be confirmed.
    for expected_count in range(4, 9):
        await _wait_until_read_pending(fake_stream)
        fake_stream.release_next_read()
        await _wait_until(lambda: fake_stream.read_calls >= expected_count)
        if received:
            break

    await _run_until_cancelled(task)

    assert len(received) == 1
    assert received[0].start_seconds == pytest.approx(0.5, abs=0.05)
    assert received[0].end_seconds == pytest.approx(10.4, abs=0.05)
