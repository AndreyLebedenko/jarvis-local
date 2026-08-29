import asyncio
import io
from collections.abc import Callable

import numpy as np
import sounddevice as sd
import soundfile as sf

from jarvis.audio.replay import (
    ReplayOutcome,
    ReplayPlayer,
    TextReply,
    VoiceReply,
    reply_speech_text,
)
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


def test_replay_many_plays_all_texts_back_to_back_in_order():
    engine = _FakeEngine()
    play = _RecordingPlay()
    player = ReplayPlayer(_tts_settings(), engine, play=play)

    async def scenario() -> ReplayOutcome:
        outcome = await player.replay_many(["First one.", "Second one."])
        await player.wait_for_pending()
        return outcome

    outcome = asyncio.run(scenario())

    assert outcome is ReplayOutcome.STARTED
    assert engine.seen == [("First one.", "en"), ("Second one.", "en")]
    assert play.played == [b"First one.", b"Second one."]


def test_replay_many_is_one_active_task_spanning_the_whole_sequence():
    async def scenario() -> tuple[ReplayOutcome, ReplayOutcome]:
        release = asyncio.Event()
        play = _BlockingPlay(release)
        player = ReplayPlayer(_tts_settings(), _FakeEngine(), play=play)
        started = await player.replay_many(["First one.", "Second one."])
        await play.started.wait()
        external = await player.replay("An external single reply.")
        release.set()
        await player.wait_for_pending()
        return started, external

    started, external = asyncio.run(scenario())
    assert started is ReplayOutcome.STARTED
    assert external is ReplayOutcome.BUSY


def test_cancel_stops_the_whole_sequence_before_later_segments():
    async def scenario() -> list[tuple[str, str]]:
        release = asyncio.Event()
        play = _BlockingPlay(release)
        engine = _FakeEngine()
        player = ReplayPlayer(_tts_settings(), engine, play=play)
        await player.replay_many(["First one.", "Second one."])
        await play.started.wait()
        player.cancel()
        release.set()
        await player.wait_for_pending()
        return engine.seen

    seen = asyncio.run(scenario())
    assert seen == [("First one.", "en")]


def test_replay_many_reports_empty_when_no_text_is_speakable():
    engine = _FakeEngine()
    player = ReplayPlayer(_tts_settings(), engine, play=_RecordingPlay())

    outcome = asyncio.run(player.replay_many(["   ", ""]))

    assert outcome is ReplayOutcome.EMPTY
    assert engine.seen == []


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


def test_playback_completes_when_the_device_stops_before_the_end():
    # A real OutputStream can fire its finished callback before the clip drains
    # (a device underrun or an unexpected stop mid-clip). That must complete
    # the segment, not hang the sequence waiting for a finish that never comes.
    # Reproduces the field bug where a sequence started on a voice turn played
    # the wav but never advanced to the next reply.
    async def scenario() -> bool:
        created: list[_FakeStream] = []

        def factory(sr, ch, cb, fin) -> _FakeStream:
            stream = _FakeStream(sr, ch, cb, fin)
            created.append(stream)
            return stream

        player = ReplayPlayer(
            _tts_settings(), _WavEngine(_wav_bytes(200)), stream_factory=factory
        )
        await player.replay("One sentence.")
        while not created or not player.is_active:
            await asyncio.sleep(0)
        created[0].pump(50)  # partial playback: pos < len, never paused
        created[0].stop()  # the device stops the stream early
        await asyncio.wait_for(player.wait_for_pending(), timeout=2)
        return player.is_active

    assert asyncio.run(scenario()) is False


def test_replay_items_advances_from_a_voice_wav_to_the_next_reply(tmp_path):
    # Reproduces the field bug: starting a sequence on a voice turn played the
    # wav but never advanced. Drives the real PausablePlayback path (not the
    # RecordingPlay shortcut) for [VoiceReply, TextReply] and asserts both
    # segments open a stream.
    wav = _wav_bytes(120)
    wav_file = tmp_path / "voice.wav"
    wav_file.write_bytes(wav)
    created: list[_FakeStream] = []

    def factory(sr, ch, cb, fin) -> _FakeStream:
        stream = _FakeStream(sr, ch, cb, fin)
        created.append(stream)
        return stream

    player = ReplayPlayer(_tts_settings(), _WavEngine(wav), stream_factory=factory)

    async def scenario() -> int:
        await player.replay_items([VoiceReply(wav_file), TextReply("Second one.")])
        while not created:
            await asyncio.sleep(0)
        created[0].pump(1000)  # drain the voice wav to completion
        while len(created) < 2:
            await asyncio.sleep(0)
        created[1].pump(1000)  # drain the assistant reply
        await player.wait_for_pending()
        return len(created)

    assert asyncio.run(scenario()) == 2


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
