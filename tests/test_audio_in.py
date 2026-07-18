import asyncio
import concurrent.futures
import io
import logging
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
import torch
from silero_vad import load_silero_vad, read_audio

from jarvis.audio.input import (
    SAMPLE_RATE,
    AudioInput,
    MicSleepToggled,
    UtteranceChunk,
    VadChunker,
    _default_stream_factory,
    run_hotkey_listener,
    stream_factory_for_device,
)
from jarvis.core.bus import EventBus
from jarvis.core.config import HotkeySettings, VadSettings


@pytest.fixture(scope="module")
def vad_model():
    return load_silero_vad()


class _AlwaysSpeechModel:
    def __call__(self, chunk, sampling_rate):
        return torch.tensor(0.99)

    def reset_states(self):
        pass


def test_a1_fixtures_internal_breath_pause_is_merged_by_default(vad_model):
    """a1.wav is a synthetic TTS fixture with an internal pause.

    Silero returns it as two raw segments. With the default
    request_end_pause_seconds (2.0 s), that pause is a mid-request breath,
    not the end of the request, so it must be merged into a single utterance.
    """
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
    assert sum(c.end_seconds - c.start_seconds for c in chunks) == pytest.approx(
        40.0, abs=0.5
    )


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
        self.settings = SimpleNamespace(
            request_end_pause_seconds=request_end_pause_seconds
        )

    def chunk(self, samples):
        return []


class _CountingFakeChunker(_FakeChunker):
    def __init__(self, request_end_pause_seconds: float = 2.0) -> None:
        super().__init__(request_end_pause_seconds)
        self.chunk_calls = 0

    def chunk(self, samples):
        self.chunk_calls += 1
        return []


class _FreeRunningFakeStream:
    """Free-running fake sd.InputStream: read() returns immediately, so
    tests only need to bound real time loosely (asyncio.sleep windows),
    not synchronize read-by-read."""

    def __init__(self, block_samples: int) -> None:
        self.read_calls = 0
        self.stop_calls = 0
        self.start_calls = 0
        self.enter_calls = 0
        self.exit_calls = 0
        self._block_samples = block_samples

    def __enter__(self):
        self.enter_calls += 1
        return self

    def __exit__(self, *exc_info):
        self.exit_calls += 1
        return False

    def read(self, block_samples):
        self.read_calls += 1
        return np.zeros((block_samples, 1), dtype=np.float32), False

    def stop(self):
        self.stop_calls += 1

    def start(self):
        self.start_calls += 1


class _RestartingStreamProbe(_FreeRunningFakeStream):
    def start(self):
        self.start_calls += 1
        raise AssertionError("the paused stream must not be started again")


async def _run_until_cancelled(task):
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_sleeping_stops_new_reads_from_the_stream():
    fake_stream = _FreeRunningFakeStream(block_samples=160)
    audio_input = AudioInput(
        bus=EventBus(), chunker=_FakeChunker(), stream_factory=lambda bs: fake_stream
    )

    task = asyncio.create_task(
        audio_input.run_microphone_loop(poll_interval_seconds=0.01)
    )
    await asyncio.sleep(0.05)
    assert fake_stream.read_calls > 0

    await audio_input.toggle_user_sleep()
    # Let any read already in flight when toggle_user_sleep() was called
    # complete, and the sleep branch run (the awake-check happens once
    # per iteration, before the read call, so one in-flight read can
    # still land here).
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
    await audio_input.toggle_user_sleep()

    task = asyncio.create_task(
        audio_input.run_microphone_loop(poll_interval_seconds=0.01)
    )
    await asyncio.sleep(0.05)

    assert fake_stream.read_calls == 0

    await _run_until_cancelled(task)


async def test_waking_recreates_capture_stream_instead_of_restarting_the_old_one():
    first_stream = _RestartingStreamProbe(block_samples=160)
    second_stream = _FreeRunningFakeStream(block_samples=160)
    stream_sequence = iter([first_stream, second_stream])
    created_streams = []

    def stream_factory(block_samples):
        stream = next(stream_sequence)
        created_streams.append(stream)
        return stream

    audio_input = AudioInput(
        bus=EventBus(), chunker=_FakeChunker(), stream_factory=stream_factory
    )

    task = asyncio.create_task(
        audio_input.run_microphone_loop(poll_interval_seconds=0.01)
    )
    await asyncio.sleep(0.02)

    await audio_input.toggle_user_sleep()
    await asyncio.sleep(0.02)
    assert first_stream.stop_calls >= 1

    await audio_input.toggle_user_sleep()
    await _wait_until(
        lambda: second_stream.read_calls > 0,
        message="wake never created a fresh capture stream",
    )

    assert created_streams == [first_stream, second_stream]
    assert first_stream.start_calls == 0
    assert first_stream.exit_calls == 1
    assert not task.done()

    await audio_input.stop()
    await asyncio.wait_for(task, timeout=2)
    assert second_stream.exit_calls == 1


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


class _StopUnblocksFakeStream:
    def __init__(self, block_samples: int) -> None:
        self._block_samples = block_samples
        self._stopped = threading.Event()
        self._waiting = threading.Event()
        self.read_calls = 0
        self.stop_calls = 0
        self.exited = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.exited = True
        return False

    def block_until_read_is_pending(self, timeout: float) -> None:
        if not self._waiting.wait(timeout):
            raise AssertionError("read() was never called")

    def read(self, block_samples):
        self._waiting.set()
        self._stopped.wait()
        self.read_calls += 1
        return np.zeros((self._block_samples, 1), dtype=np.float32), False

    def stop(self):
        self.stop_calls += 1
        self._stopped.set()

    def start(self):
        raise AssertionError("shutdown stop must not restart the stream")


async def _wait_until_read_pending(fake_stream, timeout=2.0):
    await asyncio.to_thread(fake_stream.block_until_read_is_pending, timeout)


async def _wait_until(condition, timeout=2.0, message="condition never became true"):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while not condition():
        if loop.time() > deadline:
            raise AssertionError(message)
        await asyncio.sleep(0.005)


async def test_sleep_resets_buffer_so_pre_sleep_audio_never_merges_with_post_wake_audio(
    vad_model,
):
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
    silence_block = np.zeros(
        SAMPLE_RATE, dtype=np.float32
    )  # 1s of silence per subsequent read

    fake_stream = _SteppedFakeStream(
        blocks=[a2_samples, leaked_read_filler, a1_samples], fill_value=silence_block
    )

    bus = EventBus()
    received = []

    async def on_chunk(chunk: UtteranceChunk) -> None:
        received.append(chunk)

    bus.subscribe(UtteranceChunk, on_chunk)

    chunker = VadChunker(VadSettings(), model=vad_model)
    audio_input = AudioInput(
        bus=bus, chunker=chunker, stream_factory=lambda bs: fake_stream
    )

    task = asyncio.create_task(
        audio_input.run_microphone_loop(poll_interval_seconds=1.0)
    )

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

    await audio_input.toggle_user_sleep()

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

    await audio_input.toggle_user_sleep()

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
        await _wait_until(
            lambda expected_count=expected_count: (
                fake_stream.read_calls >= expected_count
            )
        )
        if received:
            break

    await _run_until_cancelled(task)

    assert len(received) == 1
    assert received[0].start_seconds == pytest.approx(0.5, abs=0.05)
    assert received[0].end_seconds == pytest.approx(10.4, abs=0.05)


# --- stale-buffer-replay fix (see tasks/bug_reports/) -----------------------
#
# All of these model the live-observed failure: a device that stops
# delivering frames (hardware mute, USB stall) leaves the loop blocked
# inside stream.read(), so none of the top-of-loop pause hygiene runs.
# Whatever was buffered before the pause must never be published after it.


async def test_auto_pause_stops_the_stream_to_interrupt_a_pending_read():
    silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
    fake_stream = _SteppedFakeStream(blocks=[], fill_value=silence)
    audio_input = AudioInput(
        bus=EventBus(), chunker=_FakeChunker(), stream_factory=lambda bs: fake_stream
    )

    task = asyncio.create_task(
        audio_input.run_microphone_loop(poll_interval_seconds=1.0)
    )
    await _wait_until_read_pending(fake_stream)
    assert fake_stream.stop_calls == 0

    await audio_input.auto_pause_for_speech()

    assert fake_stream.stop_calls >= 1  # read interrupted without waiting for it

    fake_stream.release_next_read()  # let the parked read finish before cleanup
    await _run_until_cancelled(task)


async def test_data_read_across_a_pause_is_discarded_not_published(vad_model):
    """The read that was already in flight when the pause hit delivers
    real speech WITH enough trailing silence to confirm an utterance -
    before the fix, that published as a fresh turn."""
    a2_samples = read_audio("audio/a2.wav", sampling_rate=SAMPLE_RATE).numpy()
    confirmed_speech = np.concatenate(
        [a2_samples, np.zeros(SAMPLE_RATE * 3, dtype=np.float32)]
    )
    silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
    fake_stream = _SteppedFakeStream(blocks=[confirmed_speech], fill_value=silence)

    bus = EventBus()
    received = []

    async def on_chunk(chunk: UtteranceChunk) -> None:
        received.append(chunk)

    bus.subscribe(UtteranceChunk, on_chunk)
    chunker = VadChunker(VadSettings(), model=vad_model)
    audio_input = AudioInput(
        bus=bus, chunker=chunker, stream_factory=lambda bs: fake_stream
    )

    task = asyncio.create_task(
        audio_input.run_microphone_loop(poll_interval_seconds=1.0)
    )
    await _wait_until_read_pending(fake_stream)

    await audio_input.auto_pause_for_speech()
    # Speech + confirming silence arrive across the pause.
    fake_stream.release_next_read()
    await _wait_until(
        lambda: fake_stream.stop_calls >= 1,
        message="loop never reached the pause branch",
    )
    assert received == []

    await audio_input.auto_resume_after_speech()

    # post-resume silence reads: nothing stale must surface
    for _ in range(3):
        await _wait_until_read_pending(fake_stream)
        fake_stream.release_next_read()

    await _run_until_cancelled(task)
    assert received == []


async def test_stalled_read_buffer_is_dropped_on_resume_instead_of_replayed(vad_model):
    """The exact live signature (listening -> thinking in ~35 ms): speech
    is buffered but unconfirmed, the device stalls, pause AND resume both
    pass while the loop is blocked in read(), then frames resume carrying
    the confirming silence. Before the fix the pre-pause speech published
    instantly as a fresh utterance."""
    a2_samples = read_audio("audio/a2.wav", sampling_rate=SAMPLE_RATE).numpy()
    confirming_silence = np.zeros(SAMPLE_RATE * 3, dtype=np.float32)
    silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
    fake_stream = _SteppedFakeStream(
        blocks=[a2_samples, confirming_silence], fill_value=silence
    )
    created_streams = []

    def stream_factory(block_samples):
        created_streams.append(fake_stream)
        return fake_stream

    bus = EventBus()
    received = []

    async def on_chunk(chunk: UtteranceChunk) -> None:
        received.append(chunk)

    bus.subscribe(UtteranceChunk, on_chunk)
    chunker = VadChunker(VadSettings(), model=vad_model)
    audio_input = AudioInput(bus=bus, chunker=chunker, stream_factory=stream_factory)

    task = asyncio.create_task(
        audio_input.run_microphone_loop(poll_interval_seconds=1.0)
    )

    # Read #1: a2's speech lands in the buffer, unconfirmed (no trailing
    # silence yet). The loop parks on read #2 - the "stalled device".
    await _wait_until_read_pending(fake_stream)
    fake_stream.release_next_read()
    await _wait_until(lambda: fake_stream.read_calls >= 1)
    await _wait_until_read_pending(fake_stream)
    assert received == []

    # Pause and resume both pass while read #2 is still blocked; the fake
    # stream's stop() does not unblock the read, modelling a stall.
    await audio_input.auto_pause_for_speech()
    await audio_input.auto_resume_after_speech()

    # Frames resume: read #2 delivers the confirming silence. With the old
    # code the buffer still held a2 and published it immediately.
    fake_stream.release_next_read()
    await _wait_until(lambda: fake_stream.read_calls >= 2)

    for _ in range(3):
        await _wait_until_read_pending(fake_stream)
        fake_stream.release_next_read()

    await _run_until_cancelled(task)
    assert received == []
    assert len(created_streams) >= 2  # capture resumed with a fresh stream context


class _PauseRaisingFakeStream:
    """Models the real device behavior where stopping the stream makes the
    blocked read() raise (PortAudio returns an error from Pa_ReadStream on
    a stopped stream). start() re-arms it so post-resume reads succeed."""

    def __init__(self, block_samples: int) -> None:
        self._block_samples = block_samples
        self._stopped = threading.Event()
        self._waiting = threading.Event()
        self.read_calls = 0
        self.stop_calls = 0
        self.start_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def block_until_read_is_pending(self, timeout: float) -> None:
        if not self._waiting.wait(timeout):
            raise AssertionError("read() was never called")
        self._waiting.clear()

    def read(self, block_samples):
        self.read_calls += 1
        if self._stopped.is_set():
            raise RuntimeError("Error reading stream: stream is stopped")
        self._waiting.set()
        self._stopped.wait()
        raise RuntimeError("Error reading stream: stream was stopped")

    def stop(self):
        self.stop_calls += 1
        self._stopped.set()

    def start(self):
        self.start_calls += 1
        self._stopped.clear()


async def test_read_exception_from_a_pause_stop_recreates_the_stream_without_crashing():
    created_streams: list[_PauseRaisingFakeStream] = []

    def stream_factory(block_samples):
        stream = _PauseRaisingFakeStream(block_samples)
        created_streams.append(stream)
        return stream

    audio_input = AudioInput(
        bus=EventBus(), chunker=_FakeChunker(), stream_factory=stream_factory
    )

    task = asyncio.create_task(
        audio_input.run_microphone_loop(poll_interval_seconds=0.01)
    )
    await _wait_until(lambda: len(created_streams) == 1)
    await _wait_until_read_pending(created_streams[0])

    await audio_input.auto_pause_for_speech()  # stop() makes the blocked read raise
    await _wait_until(
        lambda: created_streams[0].stop_calls >= 1,
        message="loop never reached the pause branch after the read raised",
    )
    assert not task.done()  # the loop survived the interrupted read

    await audio_input.auto_resume_after_speech()
    await _wait_until(
        lambda: len(created_streams) >= 2 and created_streams[1].read_calls >= 1,
        message="loop never created a fresh stream after resume",
    )

    # stop() unblocks the read parked after resume, so the loop (and its
    # worker thread) exits cleanly instead of being abandoned mid-read.
    await audio_input.stop()
    await asyncio.wait_for(task, timeout=2)


async def test_stop_unblocks_a_microphone_loop_waiting_inside_stream_read():
    fake_stream = _StopUnblocksFakeStream(block_samples=160)
    chunker = _CountingFakeChunker()
    audio_input = AudioInput(
        bus=EventBus(), chunker=chunker, stream_factory=lambda bs: fake_stream
    )

    task = asyncio.create_task(
        audio_input.run_microphone_loop(poll_interval_seconds=0.01)
    )
    await _wait_until_read_pending(fake_stream)

    await audio_input.stop()
    await asyncio.wait_for(task, timeout=2)

    assert fake_stream.stop_calls >= 1
    assert fake_stream.read_calls == 1
    assert fake_stream.exited is True
    assert chunker.chunk_calls == 0


# --- task-v1.5.1-1: terminal stop boundary -----------------------------------
#
# run_until_shutdown() cancels background tasks right after stop() returns
# and the process tears down the loop/executor shortly after. If the
# microphone loop or its read worker is still alive at that point, teardown
# races them (see
# tasks/bug_reports/2026-07-17-shutdown-microphone-executor-race.md).
# stop() is terminal: it completes only once the loop has actually exited,
# and a loop starting after stop() must exit without opening a stream.


class _SlowDrainFakeStream:
    """stop() unblocks a pending read, but the worker thread then takes a
    while to actually return - modelling a device read that drains slowly
    after the stream is stopped. This is the window the pre-fix stop()
    left open: it returned while the loop (and its read worker) were
    still alive."""

    def __init__(self, block_samples: int, drain_seconds: float = 0.3) -> None:
        self._block_samples = block_samples
        self._drain_seconds = drain_seconds
        self._stopped = threading.Event()
        self._waiting = threading.Event()
        self.stop_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def block_until_read_is_pending(self, timeout: float) -> None:
        if not self._waiting.wait(timeout):
            raise AssertionError("read() was never called")

    def read(self, block_samples):
        self._waiting.set()
        self._stopped.wait()
        time.sleep(self._drain_seconds)
        return np.zeros((self._block_samples, 1), dtype=np.float32), False

    def stop(self):
        self.stop_calls += 1
        self._stopped.set()

    def start(self):
        raise AssertionError("shutdown stop must not restart the stream")


async def test_stop_stays_pending_until_the_read_worker_and_loop_have_finished(
    caplog,
):
    """The regression property: with the read worker still blocked, stop()
    must not complete (the pre-fix stop() returned here, leaving the loop
    and its worker alive for teardown to race). Once the worker is
    released, the loop finishes first and only then does stop()."""
    silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
    # _SteppedFakeStream's stop() does not unblock a pending read - the
    # worker stays parked until the test releases it.
    fake_stream = _SteppedFakeStream(blocks=[], fill_value=silence)
    audio_input = AudioInput(
        bus=EventBus(), chunker=_FakeChunker(), stream_factory=lambda bs: fake_stream
    )

    task = asyncio.create_task(
        audio_input.run_microphone_loop(poll_interval_seconds=1.0)
    )
    await _wait_until_read_pending(fake_stream)

    with caplog.at_level(logging.WARNING, logger="jarvis.audio.input"):
        stop_task = asyncio.create_task(audio_input.stop())
        try:
            await asyncio.sleep(0.1)

            assert not task.done()
            assert not stop_task.done()
        finally:
            # Release on every path, including a failing assertion (the
            # pre-fix stop() completing early): a worker left parked in
            # read() would hang pytest's executor teardown instead of
            # letting the failure report.
            fake_stream.release_next_read()
        await asyncio.wait_for(stop_task, timeout=2)

    assert task.done()

    # Mirror run_until_shutdown()'s exact ordering: cancel-after-stop must
    # find an already-finished task and the shutdown gather must see a
    # clean exit, not an exception it would log as a task failure.
    task.cancel()
    [result] = await asyncio.gather(task, return_exceptions=True)
    assert result is None
    assert caplog.records == []


class _CountingExecutor(concurrent.futures.ThreadPoolExecutor):
    def __init__(self) -> None:
        super().__init__(max_workers=4)
        self.submissions = 0

    def submit(self, fn, /, *args, **kwargs):
        self.submissions += 1
        return super().submit(fn, *args, **kwargs)


async def test_no_executor_submission_happens_after_stop_has_returned():
    """Supporting evidence for the terminal-stop boundary (the regression
    property is the pending-stop test above): asyncio.to_thread() routes
    through the loop's default executor, so a counting executor observes
    that nothing is submitted once stop() has returned - even with a read
    worker that drains slowly after the stream stop."""
    executor = _CountingExecutor()
    asyncio.get_running_loop().set_default_executor(executor)

    fake_stream = _SlowDrainFakeStream(block_samples=160)
    audio_input = AudioInput(
        bus=EventBus(), chunker=_FakeChunker(), stream_factory=lambda bs: fake_stream
    )
    task = asyncio.create_task(
        audio_input.run_microphone_loop(poll_interval_seconds=0.01)
    )
    await asyncio.to_thread(fake_stream.block_until_read_is_pending, 2.0)

    await audio_input.stop()
    submissions_at_boundary = executor.submissions

    assert task.done()
    await asyncio.sleep(0.05)
    assert executor.submissions == submissions_at_boundary


async def test_stop_before_the_loop_ever_started_returns_immediately():
    audio_input = AudioInput(bus=EventBus(), chunker=_FakeChunker())

    await asyncio.wait_for(audio_input.stop(), timeout=1)


async def test_stop_is_terminal_a_late_starting_loop_never_opens_a_stream():
    """stop() must win a stop-before-start race: a loop scheduled after
    stop() exits immediately without opening a stream or submitting any
    executor job (before the fix, the loop reset the stop flag on entry
    and ran as if stop() had never happened)."""
    factory_calls: list[int] = []

    def stream_factory(block_samples: int):
        factory_calls.append(block_samples)
        raise AssertionError("a stopped AudioInput must not open a stream")

    audio_input = AudioInput(
        bus=EventBus(), chunker=_FakeChunker(), stream_factory=stream_factory
    )

    await asyncio.wait_for(audio_input.stop(), timeout=1)

    await asyncio.wait_for(
        audio_input.run_microphone_loop(poll_interval_seconds=0.01), timeout=1
    )
    assert factory_calls == []


# --- task-10: MicSleepToggled event and real hotkey listener -----------------


async def test_toggle_user_sleep_publishes_mic_sleep_toggled():
    bus = EventBus()
    received = []

    async def on_event(event: MicSleepToggled) -> None:
        received.append(event)

    bus.subscribe(MicSleepToggled, on_event)
    audio_input = AudioInput(bus=bus, chunker=_FakeChunker())

    await audio_input.toggle_user_sleep()
    await audio_input.toggle_user_sleep()

    assert received == [MicSleepToggled(is_awake=False), MicSleepToggled(is_awake=True)]


async def test_auto_pause_and_resume_do_not_publish_mic_sleep_toggled():
    """The internal echo mitigation is not a user-visible privacy action
    (task-10 review finding): it must not fire the event that drives the
    mic_sleep/mic_wake cues, or every spoken response would sound like
    the user's own privacy toggle."""
    bus = EventBus()
    received = []

    async def on_event(event: MicSleepToggled) -> None:
        received.append(event)

    bus.subscribe(MicSleepToggled, on_event)
    audio_input = AudioInput(bus=bus, chunker=_FakeChunker())

    await audio_input.auto_pause_for_speech()
    await audio_input.auto_resume_after_speech()

    assert received == []


async def test_auto_pause_does_not_wake_a_user_requested_sleep():
    """Regression for the P1 bug found in task-10 review: a single
    is_awake bit could not represent "user wants privacy" and "Jarvis is
    auto-pausing for its own speech" independently, so auto-resume could
    wake the mic against an explicit user sleep (e.g. a clipboard turn
    submitted while asleep, then answered aloud)."""
    audio_input = AudioInput(bus=EventBus(), chunker=_FakeChunker())

    await audio_input.toggle_user_sleep()  # user explicitly wants privacy
    assert audio_input.is_awake is False

    await audio_input.auto_pause_for_speech()
    assert audio_input.is_awake is False

    await audio_input.auto_resume_after_speech()
    assert audio_input.is_awake is False  # still asleep - the user never asked to wake


async def test_user_toggle_during_auto_pause_keeps_user_intent():
    """Regression for the other half of the same P1 bug: pressing the
    privacy hotkey while auto-paused (e.g. mid-speech) must register
    the user's actual request, not get reinterpreted based on whatever
    the combined capture state happens to be at that instant."""
    bus = EventBus()
    received = []

    async def on_event(event: MicSleepToggled) -> None:
        received.append(event)

    bus.subscribe(MicSleepToggled, on_event)
    audio_input = AudioInput(bus=bus, chunker=_FakeChunker())

    await audio_input.auto_pause_for_speech()  # e.g. Jarvis started speaking
    assert audio_input.is_awake is False

    # User presses the privacy hotkey while auto-paused, wanting sleep -
    # must be registered as such, not skipped just because capture is
    # already (coincidentally) off.
    await audio_input.toggle_user_sleep()
    assert received == [MicSleepToggled(is_awake=False)]

    await audio_input.auto_resume_after_speech()  # Jarvis stops speaking
    assert audio_input.is_awake is False  # the user's own sleep request stands


class _FakeKeyboardModule:
    """Records provider registrations and cleanup per binding."""

    def __init__(self) -> None:
        self.registered: dict[str, callable] = {}
        self.removed_handles: list[object] = []
        self._handle_by_binding: dict[str, object] = {}

    def register(self, binding, callback) -> None:
        self.registered[binding] = callback
        handle = object()
        self._handle_by_binding[binding] = handle

    def start(self) -> None:
        pass

    def stop(self) -> None:
        self.removed_handles.extend(self._handle_by_binding.values())

    def handle_for(self, binding: str) -> object:
        return self._handle_by_binding[binding]


async def test_mic_sleep_hotkey_listener_registers_binding_from_config():
    hotkeys = HotkeySettings(mic_sleep_toggle="ctrl+alt+z")
    fake_kb = _FakeKeyboardModule()
    audio_input = AudioInput(bus=EventBus(), chunker=_FakeChunker())

    task = asyncio.create_task(
        run_hotkey_listener(audio_input, hotkeys, provider=fake_kb)
    )
    await asyncio.sleep(0)

    assert set(fake_kb.registered) == {"ctrl+alt+z"}

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert fake_kb.removed_handles == [fake_kb.handle_for("ctrl+alt+z")]


async def test_mic_sleep_hotkey_callback_toggles_awake_state():
    hotkeys = HotkeySettings(mic_sleep_toggle="ctrl+alt+z")
    fake_kb = _FakeKeyboardModule()
    audio_input = AudioInput(bus=EventBus(), chunker=_FakeChunker())
    assert audio_input.is_awake is True

    task = asyncio.create_task(
        run_hotkey_listener(audio_input, hotkeys, provider=fake_kb)
    )
    await asyncio.sleep(0)

    fake_kb.registered["ctrl+alt+z"]()
    await asyncio.sleep(0.05)
    assert audio_input.is_awake is False

    fake_kb.registered["ctrl+alt+z"]()
    await asyncio.sleep(0.05)
    assert audio_input.is_awake is True

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_two_rapid_hotkey_presses_toggle_twice_not_the_same_action_twice():
    """Regression for the P2 bug found in task-10 review: an earlier
    version read audio_input.is_awake in the keyboard callback (on a
    different thread than the event loop) to decide whether to schedule
    sleep() or wake(), before the first press's mutation had actually run
    - two presses in quick succession could both read the same stale
    value and schedule the *same* action twice instead of toggling twice.
    Invoking the callback twice back-to-back here, before yielding to the
    loop, reproduces that scheduling order; toggle_user_sleep() reads and
    flips the state on the event loop with no intervening await, so it is
    always the current value when each scheduled call actually runs."""
    hotkeys = HotkeySettings(mic_sleep_toggle="ctrl+alt+z")
    fake_kb = _FakeKeyboardModule()
    bus = EventBus()
    received = []

    async def on_event(event: MicSleepToggled) -> None:
        received.append(event)

    bus.subscribe(MicSleepToggled, on_event)
    audio_input = AudioInput(bus=bus, chunker=_FakeChunker())
    assert audio_input.is_awake is True

    task = asyncio.create_task(
        run_hotkey_listener(audio_input, hotkeys, provider=fake_kb)
    )
    await asyncio.sleep(0)

    fake_kb.registered["ctrl+alt+z"]()
    fake_kb.registered["ctrl+alt+z"]()  # back-to-back, before either has run yet
    await asyncio.sleep(0.05)

    assert audio_input.is_awake is True  # toggled twice: back to the original state
    assert [event.is_awake for event in received] == [False, True]

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# --- story-v1.2.4-task-3: device-aware stream factory -----------------------


def test_stream_factory_for_device_binds_the_device_argument_without_opening_a_stream():
    """functools.partial inspection only - never call the resulting
    factory here, since _default_stream_factory calls the real
    sounddevice.InputStream and would try to touch real hardware."""
    factory = stream_factory_for_device("USB Headset")

    assert factory.func is _default_stream_factory
    assert factory.keywords == {"device": "USB Headset"}


def test_stream_factory_for_device_with_empty_string_means_system_default():
    factory = stream_factory_for_device("")

    assert factory.keywords == {"device": ""}
