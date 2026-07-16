from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from jarvis.journal import JournalEvent, JournalStore, new_session_id


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
            role="system",
            text="hello",
            media=[],
            transcript=None,
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
