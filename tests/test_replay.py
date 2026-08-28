import asyncio
import io
from collections.abc import Callable

import numpy as np
import sounddevice as sd
import soundfile as sf

from jarvis.audio.replay import ReplayOutcome, ReplayPlayer, reply_speech_text
from jarvis.audio.tts_mute import TtsMuteState
from jarvis.core.bus import EventBus
from jarvis.core.config import TtsSettings
from jarvis.journal.events import JournalEvent, JournalEventRef
from jarvis.journal.store import JournalStore

_SESSION = "20260826-101500-abc"


def _tts_settings() -> TtsSettings:
    return TtsSettings()


class _FakeEngine:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []

    async def synthesize(self, text: str, language: str = "ru") -> bytes:
        self.seen.append((text, language))
        return text.encode()


class _RecordingPlay:
    def __init__(self, on_play: Callable[[bytes], None] | None = None) -> None:
        self.played: list[bytes] = []
        self._on_play = on_play

    async def __call__(self, audio: bytes) -> None:
        if self._on_play is not None:
            self._on_play(audio)
        self.played.append(audio)


def _event(role: str, text: str) -> JournalEvent:
    return JournalEvent(
        session_id=_SESSION,
        timestamp="2026-08-26T10:15:00+00:00",
        source=role,
        role=role,
        text=text,
        media=(),
        transcript=None,
    )


def _store_with(tmp_path, *events: JournalEvent) -> JournalStore:
    store = JournalStore(tmp_path)
    for event in events:
        store.append(event)
    return store


def test_reply_speech_text_returns_assistant_reply_for_arbitrary_turn(tmp_path):
    store = _store_with(
        tmp_path,
        _event("user", "first question"),
        _event("assistant", "first answer"),
        _event("user", "second question"),
        _event("assistant", "second answer"),
    )

    older = JournalEventRef(_SESSION, 1)
    assert reply_speech_text(store, older) == "first answer"


def test_reply_speech_text_returns_none_for_non_assistant_turn(tmp_path):
    store = _store_with(tmp_path, _event("user", "a question"))

    assert reply_speech_text(store, JournalEventRef(_SESSION, 0)) is None


def test_reply_speech_text_returns_none_for_missing_session(tmp_path):
    store = JournalStore(tmp_path)

    assert reply_speech_text(store, JournalEventRef(_SESSION, 0)) is None


def test_replay_synthesizes_and_plays_when_channel_free():
    engine = _FakeEngine()
    play = _RecordingPlay()
    player = ReplayPlayer(_tts_settings(), engine, play=play)

    outcome = asyncio.run(_replay_and_wait(player, "Hello there."))

    assert outcome is ReplayOutcome.STARTED
    assert engine.seen == [("Hello there.", "en")]
    assert play.played == [b"Hello there."]


def test_replay_is_rejected_while_disabled():
    bus = EventBus()
    mute = TtsMuteState(bus, enabled=False)
    engine = _FakeEngine()
    player = ReplayPlayer(
        _tts_settings(), engine, play=_RecordingPlay(), mute_state=mute
    )

    outcome = asyncio.run(player.replay("Hello there."))

    assert outcome is ReplayOutcome.DISABLED
    assert engine.seen == []


def test_replay_is_rejected_while_another_replay_is_active():
    async def scenario() -> tuple[ReplayOutcome, ReplayOutcome]:
        release = asyncio.Event()
        engine = _FakeEngine()

        def block(_: bytes) -> None:
            pass

        play = _BlockingPlay(release)
        player = ReplayPlayer(_tts_settings(), engine, play=play)
        first = await player.replay("First one.")
        await play.started.wait()
        second = await player.replay("Second one.")
        release.set()
        await player.wait_for_pending()
        return first, second

    first, second = asyncio.run(scenario())
    assert first is ReplayOutcome.STARTED
    assert second is ReplayOutcome.BUSY


def test_replay_reports_empty_when_nothing_speakable():
    engine = _FakeEngine()
    player = ReplayPlayer(_tts_settings(), engine, play=_RecordingPlay())

    outcome = asyncio.run(player.replay("   "))

    assert outcome is ReplayOutcome.EMPTY
    assert engine.seen == []


def test_cancel_stops_an_active_replay():
    async def scenario() -> bool:
        release = asyncio.Event()
        play = _BlockingPlay(release)
        player = ReplayPlayer(_tts_settings(), _FakeEngine(), play=play)
        await player.replay("A sentence. Another sentence.")
        await play.started.wait()
        cancelled = player.cancel()
        await player.wait_for_pending()
        return cancelled

    assert asyncio.run(scenario()) is True


def test_cancel_is_a_noop_when_idle():
    player = ReplayPlayer(_tts_settings(), _FakeEngine(), play=_RecordingPlay())

    assert player.cancel() is False


def test_pause_and_resume_are_noops_when_idle():
    player = ReplayPlayer(_tts_settings(), _FakeEngine(), play=_RecordingPlay())

    assert player.is_paused is False
    assert player.pause() is False
    assert player.resume() is False


def test_pause_resume_suspend_and_continue_the_default_playback():
    async def scenario() -> bool:
        created: list[_FakeStream] = []

        def factory(sr, ch, cb, fin) -> _FakeStream:
            stream = _FakeStream(sr, ch, cb, fin)
            created.append(stream)
            return stream

        player = ReplayPlayer(
            _tts_settings(), _WavEngine(_wav_bytes(120)), stream_factory=factory
        )
        await player.replay("One sentence.")
        while not created or not player.is_active:
            await asyncio.sleep(0)
        stream = created[0]

        stream.pump(50)
        assert player.pause() is True
        assert player.is_paused is True
        stream.pump(40)  # ignored while paused
        assert player.resume() is True
        assert player.is_paused is False
        stream.pump(200)  # drains to the end
        await player.wait_for_pending()
        return player.is_paused

    assert asyncio.run(scenario()) is False


def _wav_bytes(frames: int, sample_rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    samples = np.linspace(-0.1, 0.1, frames, dtype="float32")
    sf.write(buffer, samples, sample_rate, format="WAV")
    return buffer.getvalue()


class _WavEngine:
    def __init__(self, wav: bytes) -> None:
        self._wav = wav
        self.seen: list[tuple[str, str]] = []

    async def synthesize(self, text: str, language: str = "ru") -> bytes:
        self.seen.append((text, language))
        return self._wav


class _FakeStream:
    def __init__(
        self,
        samplerate: int,
        channels: int,
        callback: Callable[..., None],
        finished_callback: Callable[[], None],
    ) -> None:
        self.channels = channels
        self._callback = callback
        self._finished = finished_callback
        self.running = False

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False
        self._finished()

    def abort(self) -> None:
        self.running = False
        self._finished()

    def close(self) -> None:
        pass

    def pump(self, nframes: int) -> None:
        if not self.running:
            return
        outdata = np.zeros((nframes, self.channels), dtype="float32")
        try:
            self._callback(outdata, nframes, None, None)
        except sd.CallbackStop:
            self.running = False
            self._finished()


class _BlockingPlay:
    def __init__(self, release: asyncio.Event) -> None:
        self.started = asyncio.Event()
        self._release = release
        self.played: list[bytes] = []

    async def __call__(self, audio: bytes) -> None:
        self.started.set()
        await self._release.wait()
        self.played.append(audio)


async def _replay_and_wait(player: ReplayPlayer, text: str) -> ReplayOutcome:
    outcome = await player.replay(text)
    await player.wait_for_pending()
    return outcome
