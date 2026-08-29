import asyncio
import io
import types

import numpy as np
import soundfile as sf

from jarvis.app import (
    App,
    _on_interrupt_requested,
    _on_tts_speech_enabled_changed,
    _run_reply_sequence,
    replay_reply,
    replay_sequence,
)
from jarvis.audio.replay import ReplayOutcome, ReplayPlayer, ReplayProgress
from jarvis.audio.tts_mute import TtsMuteState, TtsSpeechEnabledChanged
from jarvis.core.bus import EventBus
from jarvis.core.config import Settings, TtsSettings
from jarvis.inputs.interrupt import InterruptRequested
from jarvis.journal.events import JournalEvent, JournalEventRef
from jarvis.journal.store import JournalStore
from jarvis.ui.contract import SystemEvent

_SESSION = "20260826-101500-abc"


class _FakeEngine:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []

    async def synthesize(self, text: str, language: str = "ru") -> bytes:
        self.seen.append((text, language))
        return text.encode()


class _RecordingCues:
    def __init__(self) -> None:
        self.played: list[str] = []

    async def play(self, cue: str) -> None:
        self.played.append(cue)


class _RecordingPlay:
    def __init__(self) -> None:
        self.played: list[bytes] = []

    async def __call__(self, audio: bytes) -> None:
        self.played.append(audio)


class _FakeTts:
    def __init__(self) -> None:
        self.cancel_calls = 0

    def cancel(self) -> None:
        self.cancel_calls += 1


def _assistant_event(text: str) -> JournalEvent:
    return JournalEvent(
        session_id=_SESSION,
        timestamp="2026-08-26T10:15:00+00:00",
        source="assistant",
        role="assistant",
        text=text,
        media=(),
        transcript=None,
    )


def _app(
    *,
    store: JournalStore,
    engine: _FakeEngine,
    play: _RecordingPlay,
    cues: _RecordingCues,
    is_busy: bool = False,
    mute_state: TtsMuteState | None = None,
    bus: EventBus | None = None,
) -> App:
    bus = bus or EventBus()
    player = ReplayPlayer(TtsSettings(), engine, play=play, mute_state=mute_state)
    return App(
        bus=bus,
        backend=None,
        audio_input=None,
        tts_output=_FakeTts(),
        capture_input=None,
        orchestrator=types.SimpleNamespace(is_busy=is_busy),
        sound_cues=cues,
        thinking_mode=None,
        settings=Settings(),
        journal_store=store,
        replay_player=player,
    )


def _user_event(text: str) -> JournalEvent:
    return JournalEvent(
        session_id=_SESSION,
        timestamp="2026-08-26T10:15:00+00:00",
        source="user",
        role="user",
        text=text,
        media=(),
        transcript=None,
    )


def _store(tmp_path, *events: JournalEvent) -> JournalStore:
    store = JournalStore(tmp_path)
    for event in events:
        store.append(event)
    return store


def _mixed_store(tmp_path) -> JournalStore:
    return _store(
        tmp_path,
        _user_event("first question"),
        _assistant_event("first answer"),
        _user_event("second question"),
        _assistant_event("second answer"),
    )


def test_replay_reply_plays_a_past_reply_when_free(tmp_path):
    async def scenario():
        engine = _FakeEngine()
        play = _RecordingPlay()
        cues = _RecordingCues()
        store = _store(tmp_path, _assistant_event("Hello there."))
        app = _app(store=store, engine=engine, play=play, cues=cues)

        outcome = await replay_reply(app, JournalEventRef(_SESSION, 0))
        await app.replay_player.wait_for_pending()
        return outcome, engine, play, cues

    outcome, engine, play, cues = asyncio.run(scenario())
    assert outcome is ReplayOutcome.STARTED
    assert engine.seen == [("Hello there.", "en")]
    assert play.played == [b"Hello there."]
    assert cues.played == []


def test_replay_reply_rejected_when_a_turn_is_speaking(tmp_path):
    async def scenario():
        engine = _FakeEngine()
        cues = _RecordingCues()
        bus = EventBus()
        events: list[SystemEvent] = []

        async def collect(event: SystemEvent) -> None:
            events.append(event)

        bus.subscribe(SystemEvent, collect)
        store = _store(tmp_path, _assistant_event("Hello there."))
        app = _app(
            store=store,
            engine=engine,
            play=_RecordingPlay(),
            cues=cues,
            is_busy=True,
            bus=bus,
        )

        outcome = await replay_reply(app, JournalEventRef(_SESSION, 0))
        return outcome, engine, cues, events

    outcome, engine, cues, events = asyncio.run(scenario())
    assert outcome is ReplayOutcome.BUSY
    assert engine.seen == []
    assert cues.played == ["error"]
    assert len(events) == 1


def test_replay_reply_rejected_when_tts_disabled(tmp_path):
    async def scenario():
        engine = _FakeEngine()
        cues = _RecordingCues()
        bus = EventBus()
        store = _store(tmp_path, _assistant_event("Hello there."))
        app = _app(
            store=store,
            engine=engine,
            play=_RecordingPlay(),
            cues=cues,
            mute_state=TtsMuteState(bus, enabled=False),
            bus=bus,
        )
        return await replay_reply(app, JournalEventRef(_SESSION, 0)), engine, cues

    outcome, engine, cues = asyncio.run(scenario())
    assert outcome is ReplayOutcome.DISABLED
    assert engine.seen == []
    assert cues.played == ["error"]


def test_replay_reply_rejected_for_non_assistant_reference(tmp_path):
    async def scenario():
        cues = _RecordingCues()
        user_event = JournalEvent(
            session_id=_SESSION,
            timestamp="2026-08-26T10:15:00+00:00",
            source="user",
            role="user",
            text="a question",
            media=(),
            transcript=None,
        )
        store = _store(tmp_path, user_event)
        app = _app(
            store=store,
            engine=_FakeEngine(),
            play=_RecordingPlay(),
            cues=cues,
        )
        return await replay_reply(app, JournalEventRef(_SESSION, 0)), cues

    outcome, cues = asyncio.run(scenario())
    assert outcome is None
    assert cues.played == ["error"]


def test_replay_sequence_plays_every_assistant_reply_and_resolves(tmp_path):
    async def scenario():
        engine = _FakeEngine()
        play = _RecordingPlay()
        app = _app(
            store=_mixed_store(tmp_path),
            engine=engine,
            play=play,
            cues=_RecordingCues(),
        )
        result = await _run_reply_sequence(app, JournalEventRef(_SESSION, 1))
        return result, app.replay_player.is_active, engine, play

    result, active_after, engine, play = asyncio.run(scenario())
    assert result == "started"
    # The held request resolved only after the whole sequence finished.
    assert active_after is False
    assert engine.seen == [("first answer", "en"), ("second answer", "en")]
    assert play.played == [b"first answer", b"second answer"]


def _wav_bytes(frames: int = 64, sample_rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    samples = np.linspace(-0.1, 0.1, frames, dtype="float32")
    sf.write(buffer, samples, sample_rate, format="WAV")
    return buffer.getvalue()


def _voice_event(media_name: str) -> JournalEvent:
    return JournalEvent(
        session_id=_SESSION,
        timestamp="2026-08-26T10:15:00+00:00",
        source="voice",
        role="user",
        text="",
        media=(media_name,),
        transcript=None,
    )


def test_replay_sequence_plays_voice_wav_and_assistant_tts_in_order(tmp_path):
    # Acceptance: a mixed log plays voice user turns from their stored wav and
    # assistant replies via TTS, in journal order (story-v1.8.3 task 3).
    async def scenario():
        store = JournalStore(tmp_path)
        wav = _wav_bytes()
        store.append(_voice_event("q.wav"))
        store.write_media(_SESSION, "q.wav", wav)
        store.append(_assistant_event("an answer"))
        engine = _FakeEngine()
        play = _RecordingPlay()
        app = _app(store=store, engine=engine, play=play, cues=_RecordingCues())
        result = await _run_reply_sequence(app, JournalEventRef(_SESSION, 0))
        return result, engine.seen, play.played, wav

    result, seen, played, wav = asyncio.run(scenario())
    assert result == "started"
    assert seen == [("an answer", "en")]
    assert played == [wav, b"an answer"]


def test_replay_sequence_publishes_progress_per_reply_then_clears(tmp_path):
    # The now-playing highlight follows playback: one ReplayProgress(ref) as
    # each assistant reply begins, in journal order, then ReplayProgress(None)
    # when the sequence ends so the UI clears the highlight (story-v1.8.3).
    async def scenario():
        bus = EventBus()
        progress: list[ReplayProgress] = []

        async def collect(event: ReplayProgress) -> None:
            progress.append(event)

        bus.subscribe(ReplayProgress, collect)
        app = _app(
            store=_mixed_store(tmp_path),
            engine=_FakeEngine(),
            play=_RecordingPlay(),
            cues=_RecordingCues(),
            bus=bus,
        )
        await _run_reply_sequence(app, JournalEventRef(_SESSION, 1))
        return [event.reference for event in progress]

    references = asyncio.run(scenario())
    assert references == [
        JournalEventRef(_SESSION, 1),
        JournalEventRef(_SESSION, 3),
        None,
    ]


def test_replay_sequence_clears_progress_when_a_live_turn_cancels_it(tmp_path):
    # A live turn cancels mid-sequence: the held request unwinds and still
    # emits ReplayProgress(None) so the highlight never sticks (story-v1.8.3).
    async def scenario():
        release = asyncio.Event()

        class _BlockingPlay:
            def __init__(self) -> None:
                self.started = asyncio.Event()

            async def __call__(self, audio: bytes) -> None:
                self.started.set()
                await release.wait()

        bus = EventBus()
        progress: list[ReplayProgress] = []

        async def collect(event: ReplayProgress) -> None:
            progress.append(event)

        bus.subscribe(ReplayProgress, collect)
        play = _BlockingPlay()
        app = _app(
            store=_mixed_store(tmp_path),
            engine=_FakeEngine(),
            play=play,
            cues=_RecordingCues(),
            bus=bus,
        )
        run = asyncio.create_task(
            _run_reply_sequence(app, JournalEventRef(_SESSION, 1))
        )
        await play.started.wait()
        app.replay_player.cancel()
        await run
        return [event.reference for event in progress]

    references = asyncio.run(scenario())
    assert references[0] == JournalEventRef(_SESSION, 1)
    assert references[-1] is None


def test_replay_sequence_rejected_when_a_turn_is_speaking(tmp_path):
    async def scenario():
        engine = _FakeEngine()
        cues = _RecordingCues()
        bus = EventBus()
        events: list[SystemEvent] = []

        async def collect(event: SystemEvent) -> None:
            events.append(event)

        bus.subscribe(SystemEvent, collect)
        app = _app(
            store=_mixed_store(tmp_path),
            engine=engine,
            play=_RecordingPlay(),
            cues=cues,
            is_busy=True,
            bus=bus,
        )
        outcome = await replay_sequence(app, JournalEventRef(_SESSION, 1))
        return outcome, engine, cues, events

    outcome, engine, cues, events = asyncio.run(scenario())
    assert outcome is ReplayOutcome.BUSY
    assert engine.seen == []
    assert cues.played == ["error"]
    assert len(events) == 1


def test_replay_sequence_reports_unavailable_when_no_assistant_from_here(tmp_path):
    async def scenario():
        cues = _RecordingCues()
        store = _store(tmp_path, _user_event("only a question"))
        app = _app(
            store=store,
            engine=_FakeEngine(),
            play=_RecordingPlay(),
            cues=cues,
        )
        return await replay_sequence(app, JournalEventRef(_SESSION, 0)), cues

    outcome, cues = asyncio.run(scenario())
    assert outcome is ReplayOutcome.EMPTY
    assert cues.played == ["error"]


def test_interrupt_cancels_the_whole_active_sequence(tmp_path):
    # A live turn cancels a sequence through the same ReplayPlayer.cancel()
    # path on_turn_start is wired to, so cancelling mid-first-segment stops the
    # whole sequence and later segments are never synthesized.
    async def scenario():
        release = asyncio.Event()

        class _BlockingPlay:
            def __init__(self) -> None:
                self.started = asyncio.Event()

            async def __call__(self, audio: bytes) -> None:
                self.started.set()
                await release.wait()

        play = _BlockingPlay()
        engine = _FakeEngine()
        app = _app(
            store=_mixed_store(tmp_path),
            engine=engine,
            play=play,
            cues=_RecordingCues(),
        )
        await replay_sequence(app, JournalEventRef(_SESSION, 1))
        await play.started.wait()
        await _on_interrupt_requested(app, InterruptRequested())
        await app.replay_player.wait_for_pending()
        return app.replay_player.is_active, engine

    active_after, engine = asyncio.run(scenario())
    assert active_after is False
    assert engine.seen == [("first answer", "en")]


def test_interrupt_cancels_an_active_replay(tmp_path):
    async def scenario():
        release = asyncio.Event()

        class _BlockingPlay:
            def __init__(self) -> None:
                self.started = asyncio.Event()

            async def __call__(self, audio: bytes) -> None:
                self.started.set()
                await release.wait()

        play = _BlockingPlay()
        engine = _FakeEngine()
        store = _store(tmp_path, _assistant_event("One. Two. Three."))
        app = _app(store=store, engine=engine, play=play, cues=_RecordingCues())
        await replay_reply(app, JournalEventRef(_SESSION, 0))
        await play.started.wait()
        await _on_interrupt_requested(app, InterruptRequested())
        await app.replay_player.wait_for_pending()
        return app.replay_player.is_active, engine

    active_after, engine = asyncio.run(scenario())
    assert active_after is False
    # Cancelled mid-first-unit: the later units were never synthesized.
    assert engine.seen == [("One.", "en")]


def test_disabling_tts_cancels_an_active_replay(tmp_path):
    async def scenario():
        release = asyncio.Event()

        class _BlockingPlay:
            def __init__(self) -> None:
                self.started = asyncio.Event()

            async def __call__(self, audio: bytes) -> None:
                self.started.set()
                await release.wait()

        play = _BlockingPlay()
        store = _store(tmp_path, _assistant_event("One. Two. Three."))
        app = _app(store=store, engine=_FakeEngine(), play=play, cues=_RecordingCues())
        await replay_reply(app, JournalEventRef(_SESSION, 0))
        await play.started.wait()
        await _on_tts_speech_enabled_changed(
            app, TtsSpeechEnabledChanged(enabled=False)
        )
        await app.replay_player.wait_for_pending()
        return app.replay_player.is_active

    assert asyncio.run(scenario()) is False
