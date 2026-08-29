import asyncio
import io

import numpy as np
import soundfile as sf

from jarvis.audio.replay import (
    ReplayOutcome,
    ReplayPlayer,
    SequencePlayer,
    TextReply,
    VoiceReply,
)
from jarvis.core.config import TtsSettings
from jarvis.journal.events import JournalEvent, JournalEventRef
from jarvis.journal.store import JournalStore

_SESSION = "20260826-101500-abc"


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


class _FakeEngine:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []

    async def synthesize(self, text: str, language: str = "ru") -> bytes:
        self.seen.append((text, language))
        return text.encode()


class _RecordingPlay:
    def __init__(self) -> None:
        self.played: list[bytes] = []

    async def __call__(self, audio: bytes) -> None:
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


def _mixed_store(tmp_path) -> JournalStore:
    return _store_with(
        tmp_path,
        _event("user", "first question"),
        _event("assistant", "first answer"),
        _event("system", "a system note"),
        _event("user", "second question"),
        _event("assistant", "second answer"),
    )


def _sequence(store: JournalStore) -> SequencePlayer:
    player = ReplayPlayer(TtsSettings(), _FakeEngine(), play=_RecordingPlay())
    return SequencePlayer(store, player)


def test_walk_selects_assistant_texts_in_order_skipping_others(tmp_path):
    sequence = _sequence(_mixed_store(tmp_path))

    texts = sequence.texts_from(JournalEventRef(_SESSION, 0))

    assert texts == ["first answer", "second answer"]


def test_walk_starts_at_the_given_position_not_earlier(tmp_path):
    sequence = _sequence(_mixed_store(tmp_path))

    texts = sequence.texts_from(JournalEventRef(_SESSION, 2))

    assert texts == ["second answer"]


def test_walk_from_a_user_turn_collects_following_assistant_replies(tmp_path):
    sequence = _sequence(_mixed_store(tmp_path))

    texts = sequence.texts_from(JournalEventRef(_SESSION, 3))

    assert texts == ["second answer"]


def test_walk_is_empty_when_no_assistant_at_or_after_start(tmp_path):
    sequence = _sequence(_mixed_store(tmp_path))

    texts = sequence.texts_from(JournalEventRef(_SESSION, 4 + 1))

    assert texts == []


def test_walk_is_empty_for_a_missing_session(tmp_path):
    sequence = _sequence(JournalStore(tmp_path))

    texts = sequence.texts_from(JournalEventRef(_SESSION, 0))

    assert texts == []


def test_play_from_synthesizes_every_assistant_reply_in_order(tmp_path):
    engine = _FakeEngine()
    play = _RecordingPlay()
    player = ReplayPlayer(TtsSettings(), engine, play=play)
    sequence = SequencePlayer(_mixed_store(tmp_path), player)

    async def scenario() -> ReplayOutcome:
        outcome = await sequence.play_from(JournalEventRef(_SESSION, 0))
        await player.wait_for_pending()
        return outcome

    outcome = asyncio.run(scenario())

    assert outcome is ReplayOutcome.STARTED
    assert engine.seen == [("first answer", "en"), ("second answer", "en")]
    assert play.played == [b"first answer", b"second answer"]


def test_play_from_emits_progress_ref_as_each_reply_begins(tmp_path):
    engine = _FakeEngine()
    player = ReplayPlayer(TtsSettings(), engine, play=_RecordingPlay())
    sequence = SequencePlayer(_mixed_store(tmp_path), player)
    seen: list[JournalEventRef] = []

    async def on_segment(reference: JournalEventRef) -> None:
        seen.append(reference)

    async def scenario() -> None:
        await sequence.play_from(JournalEventRef(_SESSION, 0), on_segment=on_segment)
        await player.wait_for_pending()

    asyncio.run(scenario())

    assert seen == [JournalEventRef(_SESSION, 1), JournalEventRef(_SESSION, 4)]


def test_play_from_progress_ref_precedes_that_reply_audio(tmp_path):
    engine = _FakeEngine()
    play = _RecordingPlay()
    player = ReplayPlayer(TtsSettings(), engine, play=play)
    sequence = SequencePlayer(_mixed_store(tmp_path), player)
    trace: list[str] = []

    async def on_segment(reference: JournalEventRef) -> None:
        trace.append(f"progress:{reference.event_position}")

    class _TracingPlay:
        async def __call__(self, audio: bytes) -> None:
            trace.append(f"play:{audio.decode()}")

    player._play = _TracingPlay()

    async def scenario() -> None:
        await sequence.play_from(JournalEventRef(_SESSION, 0), on_segment=on_segment)
        await player.wait_for_pending()

    asyncio.run(scenario())

    assert trace == [
        "progress:1",
        "play:first answer",
        "progress:4",
        "play:second answer",
    ]


def test_play_from_reports_empty_when_nothing_speakable(tmp_path):
    player = ReplayPlayer(TtsSettings(), _FakeEngine(), play=_RecordingPlay())
    sequence = SequencePlayer(_store_with(tmp_path, _event("user", "q")), player)

    outcome = asyncio.run(sequence.play_from(JournalEventRef(_SESSION, 0)))

    assert outcome is ReplayOutcome.EMPTY


def test_play_item_maps_each_source_kind(tmp_path):
    store = JournalStore(tmp_path)
    sequence = _sequence(store)

    assert sequence._play_item(_event("assistant", "hi")) == TextReply("hi")
    assert sequence._play_item(_voice_event("q.wav")) == VoiceReply(
        store.media_path(_SESSION, "q.wav")
    )
    assert sequence._play_item(_event("user", "typed")) is None
    assert sequence._play_item(_event("system", "note")) is None


def _voice_store(tmp_path) -> tuple[JournalStore, bytes]:
    store = JournalStore(tmp_path)
    wav = _wav_bytes()
    store.append(_voice_event("q1.wav"))
    store.write_media(_SESSION, "q1.wav", wav)
    store.append(_event("assistant", "first answer"))
    store.append(_event("user", "typed aside"))
    store.append(_voice_event("q2.wav"))
    store.write_media(_SESSION, "q2.wav", wav)
    store.append(_event("assistant", "second answer"))
    return store, wav


def test_play_from_interleaves_voice_wav_and_assistant_synthesis(tmp_path):
    store, wav = _voice_store(tmp_path)
    engine = _FakeEngine()
    play = _RecordingPlay()
    player = ReplayPlayer(TtsSettings(), engine, play=play)
    sequence = SequencePlayer(store, player)

    async def scenario() -> None:
        await sequence.play_from(JournalEventRef(_SESSION, 0))
        await player.wait_for_pending()

    asyncio.run(scenario())

    assert engine.seen == [("first answer", "en"), ("second answer", "en")]
    assert play.played == [wav, b"first answer", wav, b"second answer"]


def test_play_from_progress_covers_voice_and_assistant_in_order(tmp_path):
    store, _ = _voice_store(tmp_path)
    player = ReplayPlayer(TtsSettings(), _FakeEngine(), play=_RecordingPlay())
    sequence = SequencePlayer(store, player)
    positions: list[int] = []

    async def on_segment(reference: JournalEventRef) -> None:
        positions.append(reference.event_position)

    async def scenario() -> None:
        await sequence.play_from(JournalEventRef(_SESSION, 0), on_segment=on_segment)
        await player.wait_for_pending()

    asyncio.run(scenario())

    assert positions == [0, 1, 3, 4]


def test_play_from_skips_a_voice_turn_whose_wav_is_missing(tmp_path):
    store = JournalStore(tmp_path)
    store.append(_voice_event("gone.wav"))  # no write_media: the file is absent
    store.append(_event("assistant", "after the gap"))
    engine = _FakeEngine()
    play = _RecordingPlay()
    player = ReplayPlayer(TtsSettings(), engine, play=play)
    sequence = SequencePlayer(store, player)
    positions: list[int] = []

    async def on_segment(reference: JournalEventRef) -> None:
        positions.append(reference.event_position)

    async def scenario() -> None:
        await sequence.play_from(JournalEventRef(_SESSION, 0), on_segment=on_segment)
        await player.wait_for_pending()

    asyncio.run(scenario())

    assert engine.seen == [("after the gap", "en")]
    assert play.played == [b"after the gap"]
    # The missing voice turn is skipped outright: no audio, no highlight.
    assert positions == [1]
