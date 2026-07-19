from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from jarvis.journal import JournalEvent, JournalRecorder, JournalStore, new_session_id
from jarvis.journal.fork import ForkSeedDropReport


def test_journal_event_json_line_round_trip_is_lossless_utf8_and_single_line() -> None:
    event = JournalEvent(
        session_id="20260716-153000-ab12",
        timestamp="2026-07-16T15:30:00+01:00",
        source="voice",
        role="user",
        text="привет",
        media=["audio/request.wav", "images/screen.png"],
        transcript=None,
    )

    line = event.to_json_line()
    encoded = line.encode("utf-8")

    assert encoded.decode("utf-8") == line
    assert line.endswith("\n")
    assert line.count("\n") == 1
    assert JournalEvent.from_json_line(line) == event


def test_new_session_id_uses_sortable_local_timestamp_prefix() -> None:
    local_tz = datetime.now().astimezone().tzinfo
    session_id = new_session_id(
        datetime(2026, 7, 16, 15, 30, 0, tzinfo=local_tz),
        random_bytes=2,
    )

    prefix, random_suffix = session_id.rsplit("-", maxsplit=1)

    assert prefix == "20260716-153000"
    assert len(random_suffix) == 4
    assert (
        JournalEvent(
            session_id=session_id,
            timestamp="2026-07-16T15:30:00+00:00",
            source="voice",
            role="user",
            text="",
            media=[],
            transcript=None,
        ).session_id
        == session_id
    )


def test_journal_event_requires_timezone_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone"):
        JournalEvent(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:00",
            source="clipboard",
            role="user",
            text="hello",
            media=[],
            transcript=None,
        )


def test_journal_event_rejects_unknown_role() -> None:
    with pytest.raises(ValueError, match="role"):
        JournalEvent(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:00+01:00",
            source="tool",
            role="tool",
            text="hello",
            media=[],
            transcript=None,
        )


def test_journal_event_accepts_system_provenance_metadata() -> None:
    event = JournalEvent(
        session_id="20260716-153000-ab12",
        timestamp="2026-07-16T15:30:00+01:00",
        source="fork",
        role="system",
        text="continued",
        media=[],
        transcript=None,
        metadata={
            "continued_from": "20260715-153000-cd34",
            "seed": {"dropped_turns": 2, "truncated": True},
        },
    )

    assert JournalEvent.from_json_line(event.to_json_line()) == event


def test_journal_event_rejects_non_json_metadata() -> None:
    with pytest.raises(ValueError, match="metadata"):
        JournalEvent(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:00+01:00",
            source="fork",
            role="system",
            text="continued",
            media=[],
            transcript=None,
            metadata={"bad": object()},
        )


def test_journal_event_rejects_session_id_that_cannot_be_a_session_directory() -> None:
    with pytest.raises(ValueError, match="session_id"):
        JournalEvent(
            session_id="../outside",
            timestamp="2026-07-16T15:30:00+01:00",
            source="voice",
            role="user",
            text="hello",
            media=[],
            transcript=None,
        )


def test_journal_event_rejects_media_paths_outside_session_directory() -> None:
    for media_path in ("C:\\temp\\audio.wav", "/tmp/audio.wav", "../audio.wav"):
        with pytest.raises(ValueError, match="media paths"):
            JournalEvent(
                session_id="20260716-153000-ab12",
                timestamp="2026-07-16T15:30:00+01:00",
                source="voice",
                role="user",
                text="hello",
                media=[media_path],
                transcript=None,
            )


def test_journal_event_copies_media_paths_from_mutable_input() -> None:
    media = ["audio/request.wav"]
    event = JournalEvent(
        session_id="20260716-153000-ab12",
        timestamp="2026-07-16T15:30:00+01:00",
        source="voice",
        role="user",
        text="hello",
        media=media,
        transcript=None,
    )

    media.append("images/screen.png")

    assert event.media == ("audio/request.wav",)
    assert JournalEvent.from_json_line(event.to_json_line()) == event


def test_append_then_read_session_preserves_order_across_reopened_store(
    tmp_path: Path,
) -> None:
    first = _event(
        session_id="20260716-153000-ab12",
        timestamp="2026-07-16T15:30:00+01:00",
        role="user",
        text="hello",
    )
    second = _event(
        session_id="20260716-153000-ab12",
        timestamp="2026-07-16T15:30:01+01:00",
        role="assistant",
        source="assistant",
        text="hi",
    )

    JournalStore(tmp_path).append(first)
    reopened = JournalStore(tmp_path)
    reopened.append(second)

    replay = JournalStore(tmp_path).read_session("20260716-153000-ab12")

    assert replay.corrupt_lines == 0
    assert replay.events == [first, second]


def test_read_session_skips_and_counts_corrupt_lines(tmp_path: Path) -> None:
    session_id = "20260716-153000-ab12"
    first = _event(session_id=session_id, timestamp="2026-07-16T15:30:00+01:00")
    second = _event(
        session_id=session_id,
        timestamp="2026-07-16T15:30:01+01:00",
        role="assistant",
        source="assistant",
        text="answer",
    )
    store = JournalStore(tmp_path)
    store.append(first)
    events_path = tmp_path / session_id / "events.jsonl"
    with events_path.open("a", encoding="utf-8") as file:
        file.write("{not valid json}\n")
        file.write(second.to_json_line())

    replay = store.read_session(session_id)

    assert replay.corrupt_lines == 1
    assert replay.events == [first, second]


def test_list_sessions_returns_timestamps_sorted_by_first_event(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    late_session = "20260716-160000-cd34"
    early_session = "20260716-153000-ab12"
    store.append(
        _event(
            session_id=late_session,
            timestamp="2026-07-16T16:00:00+01:00",
            text="late",
        )
    )
    store.append(
        _event(
            session_id=early_session,
            timestamp="2026-07-16T15:30:00+01:00",
            text="early",
        )
    )
    store.append(
        _event(
            session_id=early_session,
            timestamp="2026-07-16T15:31:00+01:00",
            role="assistant",
            source="assistant",
            text="early answer",
        )
    )

    summaries = store.list_sessions()

    assert [summary.session_id for summary in summaries] == [
        early_session,
        late_session,
    ]
    assert summaries[0].first_timestamp == "2026-07-16T15:30:00+01:00"
    assert summaries[0].last_timestamp == "2026-07-16T15:31:00+01:00"
    assert summaries[1].first_timestamp == "2026-07-16T16:00:00+01:00"
    assert summaries[1].last_timestamp == "2026-07-16T16:00:00+01:00"


def test_list_sessions_sorts_mixed_timezone_offsets_chronologically(
    tmp_path: Path,
) -> None:
    store = JournalStore(tmp_path)
    early_session = "20260716-153000-ab12"
    late_session = "20260716-153100-cd34"
    store.append(
        _event(
            session_id=late_session,
            timestamp="2026-07-16T15:31:00+01:00",
            text="late",
        )
    )
    store.append(
        _event(
            session_id=early_session,
            timestamp="2026-07-16T14:30:00+00:00",
            text="early",
        )
    )

    summaries = store.list_sessions()

    assert [summary.session_id for summary in summaries] == [
        early_session,
        late_session,
    ]


def test_store_usage_reports_log_plus_media_bytes_per_session(tmp_path: Path) -> None:
    store = _CountingJournalStore(tmp_path)
    first = _event(
        session_id="20260716-153000-ab12",
        timestamp="2026-07-16T15:30:00+01:00",
        text="first",
    )
    second = _event(
        session_id="20260717-153000-cd34",
        timestamp="2026-07-17T15:30:00+01:00",
        text="second",
    )
    store.append(first)
    store.append(second)
    store.write_media(first.session_id, "clip.wav", b"12345")

    usage = store.usage()

    first_bytes = (tmp_path / first.session_id / "events.jsonl").stat().st_size + 5
    second_bytes = (tmp_path / second.session_id / "events.jsonl").stat().st_size
    assert usage.total_bytes == first_bytes + second_bytes
    assert [(session.session_id, session.bytes) for session in usage.sessions] == [
        (first.session_id, first_bytes),
        (second.session_id, second_bytes),
    ]
    assert store.list_sessions_calls == 1


def test_store_delete_session_removes_log_and_media(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    session_id = "20260716-153000-ab12"
    store.append(
        _event(
            session_id=session_id,
            timestamp="2026-07-16T15:30:00+01:00",
            text="first",
        )
    )
    store.write_media(session_id, "clip.wav", b"12345")

    store.delete_session(session_id)

    assert not (tmp_path / session_id).exists()
    assert store.list_sessions() == []


def test_store_delete_session_rejects_unknown_and_traversal_ids(
    tmp_path: Path,
) -> None:
    store = JournalStore(tmp_path)
    store.append(
        _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:00+01:00",
            text="first",
        )
    )
    (tmp_path / "outside.txt").write_text("keep", encoding="utf-8")

    for session_id in ("20260716-153000-missing", "../outside.txt"):
        with pytest.raises(KeyError):
            store.delete_session(session_id)

    assert (tmp_path / "outside.txt").read_text(encoding="utf-8") == "keep"


async def test_recorder_writes_voice_clipboard_and_assistant_events(
    tmp_path: Path,
) -> None:
    recorder = JournalRecorder(
        JournalStore(tmp_path),
        clock=_fixed_clock(
            datetime(2026, 7, 16, 15, 30, 0, tzinfo=UTC),
            datetime(2026, 7, 16, 15, 30, 1, tzinfo=UTC),
            datetime(2026, 7, 16, 15, 30, 2, tzinfo=UTC),
        ),
    )

    await recorder.record_voice_user(b"same wav bytes sent to model")
    await recorder.record_text_user("clipboard text")
    await recorder.record_assistant("final answer")
    await recorder.wait_for_pending()

    assert recorder.session_id is not None
    session_dir = tmp_path / recorder.session_id
    replay = JournalStore(tmp_path).read_session(recorder.session_id)

    assert replay.corrupt_lines == 0
    assert [
        (event.role, event.source, event.text, event.media) for event in replay.events
    ] == [
        ("user", "voice", "", ("utterance-20260716-153000-0001.wav",)),
        ("user", "text", "clipboard text", ()),
        ("assistant", "assistant", "final answer", ()),
    ]
    assert (
        session_dir / "utterance-20260716-153000-0001.wav"
    ).read_bytes() == b"same wav bytes sent to model"


async def test_recorder_writes_voice_event_with_screenshot_media(
    tmp_path: Path,
) -> None:
    recorder = JournalRecorder(
        JournalStore(tmp_path),
        clock=_fixed_clock(datetime(2026, 7, 16, 15, 30, 0, tzinfo=UTC)),
    )

    await recorder.record_voice_user(
        b"same wav bytes sent to model",
        screenshot_png_bytes=b"\x89PNG same screenshot bytes sent to model",
    )
    await recorder.wait_for_pending()

    assert recorder.session_id is not None
    session_dir = tmp_path / recorder.session_id
    replay = JournalStore(tmp_path).read_session(recorder.session_id)
    [event] = replay.events
    assert event.media == (
        "utterance-20260716-153000-0001.wav",
        "utterance-20260716-153000-0002.png",
    )
    assert (
        session_dir / "utterance-20260716-153000-0001.wav"
    ).read_bytes() == b"same wav bytes sent to model"
    assert (
        session_dir / "utterance-20260716-153000-0002.png"
    ).read_bytes() == b"\x89PNG same screenshot bytes sent to model"


async def test_recorder_writes_a_custom_source_label(tmp_path: Path) -> None:
    """record_text_user()'s source parameter defaults to "text" (clipboard),
    but task-v1.6.0-6's attachment turns pass source="attachment" - proves
    that label round-trips through the real store, not just a test fake."""
    recorder = JournalRecorder(
        JournalStore(tmp_path),
        clock=_fixed_clock(datetime(2026, 7, 19, 12, 0, 0, tzinfo=UTC)),
    )

    await recorder.record_text_user("attached notes.txt content", source="attachment")
    await recorder.wait_for_pending()

    replay = JournalStore(tmp_path).read_session(recorder.session_id)
    [event] = replay.events
    assert (event.role, event.source, event.text, event.media) == (
        "user",
        "attachment",
        "attached notes.txt content",
        (),
    )


async def test_recorder_starts_blank_session_with_context_provenance(
    tmp_path: Path,
) -> None:
    recorder = JournalRecorder(
        JournalStore(tmp_path),
        clock=_fixed_clock(datetime(2026, 7, 19, 10, 0, 0, tzinfo=UTC)),
    )

    session_id = await recorder.start_blank_session(
        provenance_text="Новый пустой контекст создан пользователем."
    )

    assert session_id == recorder.session_id
    assert session_id is not None
    replay = JournalStore(tmp_path).read_session(session_id)
    [event] = replay.events
    assert (event.role, event.source, event.text, event.media) == (
        "system",
        "context",
        "Новый пустой контекст создан пользователем.",
        (),
    )
    assert event.metadata == {"kind": "new_context"}


async def test_recorder_start_fork_session_writes_provenance_before_return(
    tmp_path: Path,
) -> None:
    store = JournalStore(tmp_path)
    recorder = JournalRecorder(
        store,
        clock=_fixed_clock(datetime(2026, 7, 19, 10, 0, 0, tzinfo=UTC)),
    )

    session_id = await recorder.start_fork_session(
        source_session_id="20260718-100000-ab12",
        provenance_text="continued from earlier",
        seed_drop_report=ForkSeedDropReport(
            dropped_turns=0, skipped_events=0, truncated=False
        ),
    )

    assert session_id is not None
    replay = store.read_session(session_id)
    [event] = replay.events
    assert event.source == "fork"
    assert event.role == "system"
    assert event.text == "continued from earlier"
    assert event.metadata == {
        "continued_from": "20260718-100000-ab12",
        "seed": {
            "dropped_turns": 0,
            "skipped_events": 0,
            "excluded_events": 0,
            "truncated": False,
        },
    }


async def test_recorder_pending_event_keeps_the_session_it_was_scheduled_for(
    tmp_path: Path,
) -> None:
    recorder = JournalRecorder(
        JournalStore(tmp_path),
        clock=_fixed_clock(
            datetime(2026, 7, 19, 10, 0, 0, tzinfo=UTC),
            datetime(2026, 7, 19, 10, 0, 1, tzinfo=UTC),
        ),
    )

    await recorder.record_text_user("old session turn")
    old_session_id = recorder.session_id
    new_session_id = await recorder.start_blank_session(
        provenance_text="Новый пустой контекст создан пользователем."
    )
    await recorder.wait_for_pending()

    assert old_session_id is not None
    assert new_session_id is not None
    old_replay = JournalStore(tmp_path).read_session(old_session_id)
    new_replay = JournalStore(tmp_path).read_session(new_session_id)
    assert [event.text for event in old_replay.events] == ["old session turn"]
    assert [event.source for event in new_replay.events] == ["context"]


async def test_recorder_write_failure_is_logged_and_not_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorder = JournalRecorder(
        _FailingStore(),
        clock=_fixed_clock(datetime(2026, 7, 16, 15, 30, 0, tzinfo=UTC)),
    )

    with caplog.at_level("WARNING"):
        await recorder.record_text_user("still accepted")
        await recorder.wait_for_pending()

    assert "Journal write failed" in caplog.text


async def test_disabled_recorder_does_not_start_a_session(tmp_path: Path) -> None:
    recorder = JournalRecorder(JournalStore(tmp_path), enabled=False)

    await recorder.record_text_user("ignored")
    await recorder.record_assistant("ignored")
    await recorder.wait_for_pending()

    assert recorder.session_id is None
    assert list(tmp_path.iterdir()) == []


def _event(
    *,
    session_id: str,
    timestamp: str,
    role: str = "user",
    source: str = "voice",
    text: str = "",
) -> JournalEvent:
    return JournalEvent(
        session_id=session_id,
        timestamp=timestamp,
        source=source,
        role=role,
        text=text,
        media=[],
        transcript=None,
    )


def _fixed_clock(*timestamps: datetime):
    remaining = list(timestamps)

    def now() -> datetime:
        if len(remaining) == 1:
            return remaining[0]
        return remaining.pop(0)

    return now


class _FailingStore:
    root = Path("unused")

    def append(self, event: JournalEvent) -> None:
        del event
        raise OSError("read-only")


class _CountingJournalStore(JournalStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.list_sessions_calls = 0

    def list_sessions(self):
        self.list_sessions_calls += 1
        return super().list_sessions()
