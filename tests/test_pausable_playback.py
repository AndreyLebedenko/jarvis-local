import asyncio
from collections.abc import Callable

import numpy as np
import sounddevice as sd

from jarvis.audio.replay import PausablePlayback


class _FakeStream:
    """Mirrors the sounddevice OutputStream contract the primitive relies on:
    stop() and abort() both fire the finished callback (as PortAudio does),
    and the callback is pulled frame-batch by frame-batch via pump()."""

    def __init__(
        self,
        samplerate: int,
        channels: int,
        callback: Callable[..., None],
        finished_callback: Callable[[], None],
    ) -> None:
        self.samplerate = samplerate
        self.channels = channels
        self._callback = callback
        self._finished = finished_callback
        self.running = False
        self.aborted = False
        self.closed = False

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False
        self._finished()

    def abort(self) -> None:
        self.aborted = True
        self.running = False
        self._finished()

    def close(self) -> None:
        self.closed = True

    def pump(self, nframes: int) -> None:
        if not self.running:
            return
        outdata = np.zeros((nframes, self.channels), dtype="float32")
        try:
            self._callback(outdata, nframes, None, None)
        except sd.CallbackStop:
            self.running = False
            self._finished()


def _factory(created: list[_FakeStream]):
    def make(sr, ch, cb, fin) -> _FakeStream:
        stream = _FakeStream(sr, ch, cb, fin)
        created.append(stream)
        return stream

    return make


async def _started_playback(
    frames: np.ndarray,
) -> tuple[PausablePlayback, asyncio.Task, _FakeStream]:
    created: list[_FakeStream] = []
    playback = PausablePlayback(
        frames, 16000, asyncio.Lock(), stream_factory=_factory(created)
    )
    task = asyncio.create_task(playback.play_to_completion())
    while not created:
        await asyncio.sleep(0)
    return playback, task, created[0]


def test_plays_all_frames_to_completion():
    async def scenario() -> int:
        playback, task, stream = await _started_playback(
            np.arange(100, dtype="float32")
        )
        stream.pump(40)
        stream.pump(60)
        await task
        assert stream.closed
        return playback.position

    assert asyncio.run(scenario()) == 100


def test_pause_holds_position_and_resume_continues():
    async def scenario() -> list[int]:
        playback, task, stream = await _started_playback(
            np.arange(100, dtype="float32")
        )
        stream.pump(30)
        at_pause = playback.position

        playback.pause()
        assert playback.is_paused
        stream.pump(25)  # ignored while paused
        while_paused = playback.position

        playback.resume()
        assert not playback.is_paused
        stream.pump(40)
        after_resume = playback.position

        stream.pump(30)  # reaches the end
        await task
        return [at_pause, while_paused, after_resume, playback.position]

    assert asyncio.run(scenario()) == [30, 30, 70, 100]


def test_multiple_pause_resume_cycles_within_one_clip():
    async def scenario() -> int:
        playback, task, stream = await _started_playback(np.arange(90, dtype="float32"))
        for _ in range(3):
            stream.pump(20)
            playback.pause()
            stream.pump(20)  # ignored
            playback.resume()
        stream.pump(60)  # drains the rest
        await task
        return playback.position

    assert asyncio.run(scenario()) == 90


def test_stop_ends_playback_and_aborts_stream():
    async def scenario() -> tuple[bool, int]:
        playback, task, stream = await _started_playback(
            np.arange(100, dtype="float32")
        )
        stream.pump(30)
        playback.stop()
        await task
        return stream.aborted, playback.position

    aborted, position = asyncio.run(scenario())
    assert aborted is True
    assert position == 30


def test_stop_while_paused_ends_playback():
    async def scenario() -> bool:
        playback, task, stream = await _started_playback(
            np.arange(100, dtype="float32")
        )
        stream.pump(30)
        playback.pause()
        playback.stop()
        await task
        return stream.aborted

    assert asyncio.run(scenario()) is True
