from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from jarvis.journal import JournalEvent, JournalStore
from jarvis.journal.session_metadata import (
    MAX_SESSION_TITLE_CHARS,
    SESSION_METADATA_FILE_NAME,
    SessionMetadata,
    SessionTitleError,
    normalize_session_title,
    read_session_metadata,
    write_session_metadata,
)

SESSION_ID = "20260716-153000-ab12"


def _store_with_session(tmp_path: Path) -> JournalStore:
    store = JournalStore(tmp_path)
    store.append(
        JournalEvent(
            session_id=SESSION_ID,
            timestamp="2026-07-16T15:30:00+01:00",
            source="assistant",
            role="assistant",
            text="an answer",
            media=[],
            transcript=None,
        )
    )
    return store


def _metadata_file(tmp_path: Path) -> Path:
    return tmp_path / SESSION_ID / SESSION_METADATA_FILE_NAME


# --- title rules -----------------------------------------------------------


def test_title_is_trimmed():
    assert normalize_session_title("  Pump notes \t") == "Pump notes"


def test_title_of_exactly_the_limit_is_kept():
    title = "a" * MAX_SESSION_TITLE_CHARS

    assert normalize_session_title(title) == title


def test_title_one_over_the_limit_is_refused_as_too_long():
    with pytest.raises(SessionTitleError) as refused:
        normalize_session_title("a" * (MAX_SESSION_TITLE_CHARS + 1))

    assert refused.value.reason == "title_too_long"


def test_limit_counts_characters_after_trimming():
    padded = "  " + "a" * MAX_SESSION_TITLE_CHARS + "  "

    assert normalize_session_title(padded) == "a" * MAX_SESSION_TITLE_CHARS


def test_limit_counts_characters_not_bytes():
    title = "ж" * MAX_SESSION_TITLE_CHARS

    assert normalize_session_title(title) == title


@pytest.mark.parametrize(
    "title",
    [
        "two\nlines",
        "carriage\rreturn",
        "tab\tinside",
        "nul\x00byte",
        "escape\x1b[0m",
        "delete\x7fchar",
        "c1\x85control",
        "line separator",
        "paragraph separator",
    ],
)
def test_title_with_a_control_or_line_break_character_is_refused(title):
    with pytest.raises(SessionTitleError) as refused:
        normalize_session_title(title)

    assert refused.value.reason == "title_invalid"


@pytest.mark.parametrize("value", [None, 5, ["a"], {"a": 1}, True])
def test_title_that_is_not_text_is_refused(value):
    with pytest.raises(SessionTitleError) as refused:
        normalize_session_title(value)

    assert refused.value.reason == "title_invalid"


@pytest.mark.parametrize("empty", ["", "   ", " \t\n "])
def test_blank_title_means_reset(empty):
    if "\t" in empty or "\n" in empty:
        assert normalize_session_title(empty) is None
    else:
        assert normalize_session_title(empty) is None


def test_title_keeps_ordinary_unicode_and_emoji_joiners():
    title = "Насос — \U0001f468‍\U0001f4bb"

    assert normalize_session_title(title) == title


# --- reading ---------------------------------------------------------------


def test_missing_file_is_no_metadata(tmp_path):
    assert read_session_metadata(tmp_path) == SessionMetadata()


@pytest.mark.parametrize(
    "content",
    ["", "not json", "[1, 2]", "null", '"text"', "{broken", '{"title": 5}'],
)
def test_unusable_file_is_no_title_and_never_raises(tmp_path, content):
    (tmp_path / SESSION_METADATA_FILE_NAME).write_text(content, encoding="utf-8")

    assert read_session_metadata(tmp_path).title is None


def test_invalid_bytes_in_the_file_are_no_metadata(tmp_path):
    (tmp_path / SESSION_METADATA_FILE_NAME).write_bytes(b"\xff\xfe\x00bad")

    assert read_session_metadata(tmp_path) == SessionMetadata()


def test_stored_title_that_breaks_the_rules_is_ignored(tmp_path):
    document = {"version": 1, "title": "a" * (MAX_SESSION_TITLE_CHARS + 1)}
    (tmp_path / SESSION_METADATA_FILE_NAME).write_text(
        json.dumps(document), encoding="utf-8"
    )

    assert read_session_metadata(tmp_path).title is None


def test_unknown_keys_are_read_into_extra(tmp_path):
    document = {"version": 1, "title": "T", "project_id": "p-7", "paths": ["a"]}
    (tmp_path / SESSION_METADATA_FILE_NAME).write_text(
        json.dumps(document), encoding="utf-8"
    )

    metadata = read_session_metadata(tmp_path)

    assert metadata.title == "T"
    assert metadata.extra == {"project_id": "p-7", "paths": ["a"]}


# --- writing ---------------------------------------------------------------


def test_write_then_read_round_trips_title_extra_and_version(tmp_path):
    original = SessionMetadata(title="Насос", extra={"project_id": "p-7"}, version=3)

    write_session_metadata(tmp_path, original)

    assert read_session_metadata(tmp_path) == original


def test_file_is_utf8_json_with_version_and_title(tmp_path):
    write_session_metadata(tmp_path, SessionMetadata(title="Насос"))

    raw = (tmp_path / SESSION_METADATA_FILE_NAME).read_bytes().decode("utf-8")

    assert json.loads(raw) == {"version": 1, "title": "Насос"}
    assert "Насос" in raw


def test_metadata_without_title_writes_no_title_key(tmp_path):
    write_session_metadata(tmp_path, SessionMetadata(extra={"k": 1}))

    document = json.loads((tmp_path / SESSION_METADATA_FILE_NAME).read_text("utf-8"))

    assert document == {"version": 1, "k": 1}


def test_failed_replace_keeps_the_old_file_and_leaves_no_temporary(
    tmp_path, monkeypatch
):
    write_session_metadata(tmp_path, SessionMetadata(title="old"))

    def broken_replace(source, target):
        raise OSError("disk went away")

    monkeypatch.setattr(os, "replace", broken_replace)

    with pytest.raises(OSError):
        write_session_metadata(tmp_path, SessionMetadata(title="new"))

    monkeypatch.undo()
    assert read_session_metadata(tmp_path).title == "old"
    assert [path.name for path in tmp_path.iterdir()] == [SESSION_METADATA_FILE_NAME]


def test_target_is_never_opened_for_writing_directly(tmp_path, monkeypatch):
    write_session_metadata(tmp_path, SessionMetadata(title="old"))
    seen_replacements = []
    real_replace = os.replace

    def spying_replace(source, target):
        seen_replacements.append((Path(source).name, Path(target).name))
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", spying_replace)

    write_session_metadata(tmp_path, SessionMetadata(title="new"))

    assert seen_replacements == [
        (SESSION_METADATA_FILE_NAME + ".tmp", SESSION_METADATA_FILE_NAME)
    ]


# --- store -----------------------------------------------------------------


def test_store_reports_no_metadata_for_a_session_without_a_file(tmp_path):
    store = _store_with_session(tmp_path)

    assert store.read_session_metadata(SESSION_ID) == SessionMetadata()


def test_rename_stores_the_trimmed_title_in_its_own_file(tmp_path):
    store = _store_with_session(tmp_path)

    store.rename_session(SESSION_ID, "  Pump notes ")

    assert store.read_session_metadata(SESSION_ID).title == "Pump notes"
    assert _metadata_file(tmp_path).is_file()


def test_rename_does_not_change_the_event_log_bytes(tmp_path):
    store = _store_with_session(tmp_path)
    events_file = tmp_path / SESSION_ID / "events.jsonl"
    before = events_file.read_bytes()

    store.rename_session(SESSION_ID, "Pump notes")
    store.rename_session(SESSION_ID, "")

    assert events_file.read_bytes() == before


def test_rename_to_empty_removes_the_title(tmp_path):
    store = _store_with_session(tmp_path)
    store.rename_session(SESSION_ID, "Pump notes")

    store.rename_session(SESSION_ID, "   ")

    assert store.read_session_metadata(SESSION_ID).title is None


def test_reset_keeps_unknown_keys(tmp_path):
    store = _store_with_session(tmp_path)
    store.rename_session(SESSION_ID, "Pump notes")
    document = json.loads(_metadata_file(tmp_path).read_text("utf-8"))
    document["project_id"] = "p-7"
    _metadata_file(tmp_path).write_text(json.dumps(document), encoding="utf-8")

    store.rename_session(SESSION_ID, "")

    assert store.read_session_metadata(SESSION_ID).extra == {"project_id": "p-7"}


def test_rename_keeps_unknown_keys_and_a_newer_version(tmp_path):
    store = _store_with_session(tmp_path)
    _metadata_file(tmp_path).write_text(
        json.dumps({"version": 4, "project_id": "p-7", "urls": ["u"]}),
        encoding="utf-8",
    )

    store.rename_session(SESSION_ID, "New")

    assert json.loads(_metadata_file(tmp_path).read_text("utf-8")) == {
        "version": 4,
        "project_id": "p-7",
        "urls": ["u"],
        "title": "New",
    }


def test_refused_title_changes_nothing(tmp_path):
    store = _store_with_session(tmp_path)
    store.rename_session(SESSION_ID, "Keep me")

    with pytest.raises(SessionTitleError):
        store.rename_session(SESSION_ID, "a" * (MAX_SESSION_TITLE_CHARS + 1))
    with pytest.raises(SessionTitleError):
        store.rename_session(SESSION_ID, "two\nlines")

    assert store.read_session_metadata(SESSION_ID).title == "Keep me"


def test_rename_of_an_unknown_session_raises_key_error_and_writes_nothing(tmp_path):
    store = _store_with_session(tmp_path)

    with pytest.raises(KeyError):
        store.rename_session("20260101-000000-zzzz", "x")
    with pytest.raises(KeyError):
        store.rename_session("../outside", "x")

    assert sorted(path.name for path in tmp_path.iterdir()) == [SESSION_ID]


def test_rename_over_a_corrupted_file_replaces_it(tmp_path):
    store = _store_with_session(tmp_path)
    _metadata_file(tmp_path).write_text("{broken", encoding="utf-8")

    store.rename_session(SESSION_ID, "Fresh")

    assert store.read_session_metadata(SESSION_ID).title == "Fresh"


def test_deleting_a_session_deletes_its_metadata_file(tmp_path):
    store = _store_with_session(tmp_path)
    store.rename_session(SESSION_ID, "Pump notes")

    store.delete_session(SESSION_ID)

    assert not (tmp_path / SESSION_ID).exists()


def test_metadata_file_does_not_make_an_eventless_directory_a_session(tmp_path):
    store = JournalStore(tmp_path)
    (tmp_path / SESSION_ID).mkdir()
    write_session_metadata(tmp_path / SESSION_ID, SessionMetadata(title="ghost"))

    assert store.list_sessions() == []


def test_concurrent_renames_leave_one_complete_valid_file(tmp_path):
    store = _store_with_session(tmp_path)
    titles = [f"title {number}" for number in range(40)]
    errors: list[BaseException] = []

    def rename(title: str) -> None:
        try:
            store.rename_session(SESSION_ID, title)
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=rename, args=(title,)) for title in titles]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert store.read_session_metadata(SESSION_ID).title in titles
    assert [path.name for path in (tmp_path / SESSION_ID).iterdir()] == [
        "events.jsonl",
        SESSION_METADATA_FILE_NAME,
    ]


# --- review round 1 ---------------------------------------------------------


def test_lone_surrogate_title_is_refused_as_invalid():
    with pytest.raises(SessionTitleError) as refused:
        normalize_session_title("bad\ud800title")

    assert refused.value.reason == "title_invalid"


@pytest.mark.parametrize("title", ["​", " ​‍ ", "⁠﻿"])
def test_title_of_only_invisible_characters_is_refused(title):
    with pytest.raises(SessionTitleError) as refused:
        normalize_session_title(title)

    assert refused.value.reason == "title_invalid"


def test_zero_width_joiner_inside_an_emoji_sequence_is_kept():
    title = "\U0001f468‍\U0001f4bb"

    assert normalize_session_title(title) == title


def test_deeply_nested_file_reads_as_no_metadata(tmp_path):
    (tmp_path / SESSION_METADATA_FILE_NAME).write_text("[" * 200000, encoding="utf-8")

    assert read_session_metadata(tmp_path) == SessionMetadata()


def test_stored_boolean_version_is_not_taken_as_a_version(tmp_path):
    (tmp_path / SESSION_METADATA_FILE_NAME).write_text(
        '{"version": true, "title": "T"}', encoding="utf-8"
    )

    assert type(read_session_metadata(tmp_path).version) is int


def test_write_retries_a_replace_blocked_by_a_reader(tmp_path, monkeypatch):
    real_replace = os.replace
    attempts = []

    def flaky_replace(source, target):
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError("file in use")
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", flaky_replace)

    write_session_metadata(tmp_path, SessionMetadata(title="T"))

    monkeypatch.undo()
    assert read_session_metadata(tmp_path).title == "T"


def test_reading_waits_for_a_rename_in_progress(tmp_path):
    store = _store_with_session(tmp_path)
    finished = threading.Event()

    def read() -> None:
        store.read_session_metadata(SESSION_ID)
        finished.set()

    with store._metadata_lock:
        reader = threading.Thread(target=read)
        reader.start()
        assert not finished.wait(0.3)
    reader.join(5)

    assert finished.is_set()


def test_concurrent_readers_and_writers_never_fail(tmp_path):
    store = _store_with_session(tmp_path)
    errors: list[BaseException] = []
    seen_titles: list[str | None] = []

    def write() -> None:
        try:
            for number in range(60):
                store.rename_session(SESSION_ID, f"title {number}")
        except BaseException as error:
            errors.append(error)

    def read() -> None:
        try:
            for _ in range(150):
                seen_titles.append(store.read_session_metadata(SESSION_ID).title)
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=write)] + [
        threading.Thread(target=read) for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert all(title is None or title.startswith("title ") for title in seen_titles)


def test_delete_waits_for_a_rename_in_progress(tmp_path, monkeypatch):
    import jarvis.journal.store as store_module

    store = _store_with_session(tmp_path)
    real_write = store_module.write_session_metadata
    errors: list[BaseException] = []
    deleters: list[threading.Thread] = []

    def delete() -> None:
        try:
            store.delete_session(SESSION_ID)
        except BaseException as error:
            errors.append(error)

    def write_while_a_delete_is_attempted(session_dir, metadata):
        deleter = threading.Thread(target=delete)
        deleters.append(deleter)
        deleter.start()
        deleter.join(0.3)
        real_write(session_dir, metadata)

    monkeypatch.setattr(
        store_module, "write_session_metadata", write_while_a_delete_is_attempted
    )

    store.rename_session(SESSION_ID, "Pump notes")

    deleters[0].join(5)
    assert errors == []
    assert not (tmp_path / SESSION_ID).exists()


def test_resetting_a_session_without_a_title_writes_nothing(tmp_path):
    store = _store_with_session(tmp_path)

    store.rename_session(SESSION_ID, "")
    store.rename_session(SESSION_ID, "   ")

    assert not _metadata_file(tmp_path).exists()


def test_saving_the_unchanged_title_writes_nothing(tmp_path, monkeypatch):
    import jarvis.journal.store as store_module

    store = _store_with_session(tmp_path)
    store.rename_session(SESSION_ID, "Same")
    before = _metadata_file(tmp_path).read_bytes()

    def forbidden(session_dir, metadata):
        raise AssertionError("an unchanged title must not be written")

    monkeypatch.setattr(store_module, "write_session_metadata", forbidden)

    store.rename_session(SESSION_ID, " Same ")

    assert _metadata_file(tmp_path).read_bytes() == before
