from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.core.config import FilesSettings
from jarvis.files import (
    DeniedExtensionError,
    FileTooLargeError,
    InvalidFileNameError,
    NoActiveSessionError,
    NotTextFileError,
    SessionFileNotFoundError,
    SessionFileRepository,
    SessionFileScope,
    UnsupportedImageError,
)
from jarvis.journal import JournalEvent, JournalStore

_SESSION_ID = "20260716-153000-ab12"
_OTHER_SESSION_ID = "20260716-153500-cd34"

# 1x1 transparent PNG.
_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f0f0000000049454e44ae42"
    "6082"
)


def _event(session_id: str) -> JournalEvent:
    return JournalEvent(
        session_id=session_id,
        timestamp="2026-07-16T15:30:00+01:00",
        source="voice",
        role="user",
        text="hi",
        media=[],
        transcript=None,
    )


def _make_repo(
    tmp_path: Path,
    *,
    config: FilesSettings | None = None,
    visible: tuple[str, ...] = (_SESSION_ID,),
) -> tuple[SessionFileRepository, JournalStore]:
    store = JournalStore(tmp_path)
    for session_id in visible:
        store.append(_event(session_id))
    repo = SessionFileRepository(
        tmp_path,
        config=config or FilesSettings(),
        session_is_visible=lambda sid: bool(store.read_session(sid).records),
    )
    return repo, store


def _scope(session_id: str | None = _SESSION_ID) -> SessionFileScope:
    if session_id is None:
        return SessionFileScope(write_session_id=None, read_session_ids=())
    return SessionFileScope(write_session_id=session_id, read_session_ids=(session_id,))


# ---------------------------------------------------------------- name validation


@pytest.mark.parametrize("bad_name", ["../escape.txt", "/abs.txt", "..\\win.txt"])
@pytest.mark.parametrize("operation", ["write", "read", "view", "stat"])
def test_invalid_names_are_rejected(
    tmp_path: Path, bad_name: str, operation: str
) -> None:
    repo, _ = _make_repo(tmp_path)
    scope = _scope()
    with pytest.raises(InvalidFileNameError):
        if operation == "write":
            repo.write_text(scope, bad_name, "x")
        elif operation == "read":
            repo.read_text(scope, bad_name)
        elif operation == "view":
            repo.view_image_bytes(scope, bad_name)
        else:
            repo.stat(scope, bad_name)


# ------------------------------------------------------------- storage-name shape


def test_write_generates_storage_name_and_never_writes_requested_label(
    tmp_path: Path,
) -> None:
    repo, _ = _make_repo(tmp_path)
    result = repo.write_text(_scope(), "note.md", "hello")

    assert result.storage_name != "note.md"
    assert result.storage_name.startswith("note-")
    assert result.storage_name.endswith(".md")
    assert result.bytes == len(b"hello")

    session_dir = tmp_path / _SESSION_ID
    names = {p.name for p in session_dir.iterdir()}
    assert "note.md" not in names
    assert result.storage_name in names
    # No sidecar/manifest recording the original name.
    assert not any(
        p.name.endswith((".manifest", ".meta", ".orig")) for p in session_dir.iterdir()
    )


def test_write_preserves_no_extension_names(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    result = repo.write_text(_scope(), "README", "x")
    assert result.storage_name.startswith("README-")
    assert "." not in result.storage_name


def test_write_is_create_only_on_uuid_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = _make_repo(tmp_path)
    names = iter(["fixed-collision", "fixed-collision", "fresh-name"])
    monkeypatch.setattr(
        "jarvis.files.session_files.uuid4",
        lambda: type("U", (), {"hex": next(names)})(),
    )

    first = repo.write_text(_scope(), "a.txt", "one")
    second = repo.write_text(_scope(), "a.txt", "two")

    assert first.storage_name == "a-fixed-collision.txt"
    assert second.storage_name == "a-fresh-name.txt"
    session_dir = tmp_path / _SESSION_ID
    assert (session_dir / first.storage_name).read_text(encoding="utf-8") == "one"
    assert (session_dir / second.storage_name).read_text(encoding="utf-8") == "two"


# --------------------------------------------------------------------- deny-list


def test_denylisted_extension_is_refused_case_insensitively(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path, config=FilesSettings(write_ext_blacklist=("exe",)))
    with pytest.raises(DeniedExtensionError):
        repo.write_text(_scope(), "payload.EXE", "x")


def test_non_denylisted_and_no_extension_writes_are_allowed(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path, config=FilesSettings(write_ext_blacklist=("exe",)))
    assert repo.write_text(_scope(), "note.md", "x").storage_name.endswith(".md")
    assert "." not in repo.write_text(_scope(), "PLAIN", "x").storage_name


# ------------------------------------------------------------------------- caps


def test_text_write_char_cap_is_enforced(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path, config=FilesSettings(max_text_write_chars=4))
    repo.write_text(_scope(), "ok.txt", "abcd")
    with pytest.raises(FileTooLargeError):
        repo.write_text(_scope(), "big.txt", "abcde")


def test_text_read_byte_cap_is_enforced(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path, config=FilesSettings(max_text_read_bytes=3))
    stored = repo.write_text(_scope(), "x.txt", "abc")
    assert repo.read_text(_scope(), stored.storage_name) == "abc"

    oversize = repo.write_text(_scope(), "y.txt", "abcd")
    with pytest.raises(FileTooLargeError):
        repo.read_text(_scope(), oversize.storage_name)


def test_image_view_byte_cap_is_enforced(tmp_path: Path) -> None:
    repo, _ = _make_repo(
        tmp_path, config=FilesSettings(max_image_view_bytes=len(_PNG_BYTES) - 1)
    )
    stored = repo.write_bytes(_scope(), "pic.png", _PNG_BYTES)
    with pytest.raises(FileTooLargeError):
        repo.view_image_bytes(_scope(), stored.storage_name)


# ------------------------------------------------------------------ typed reads


def test_read_text_returns_content(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    stored = repo.write_text(_scope(), "note.txt", "body")
    assert repo.read_text(_scope(), stored.storage_name) == "body"


def test_read_missing_file_raises_not_found(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    with pytest.raises(SessionFileNotFoundError):
        repo.read_text(_scope(), "ghost-0000.txt")


def test_read_text_on_binary_file_raises_not_text(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    stored = repo.write_bytes(_scope(), "pic.png", _PNG_BYTES)
    with pytest.raises(NotTextFileError):
        repo.read_text(_scope(), stored.storage_name)


def test_view_image_returns_bytes_for_png(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    stored = repo.write_bytes(_scope(), "pic.png", _PNG_BYTES)
    view = repo.view_image_bytes(_scope(), stored.storage_name)
    assert view.data == _PNG_BYTES
    assert view.media_type == "image/png"


def test_view_image_rejects_unsupported_format(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    stored = repo.write_text(_scope(), "note.txt", "x")
    with pytest.raises(UnsupportedImageError):
        repo.view_image_bytes(_scope(), stored.storage_name)


# ---------------------------------------------------------------- stat and list


def test_stat_reports_metadata(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    stored = repo.write_text(_scope(), "note.md", "hello")
    info = repo.stat(_scope(), stored.storage_name)
    assert info.storage_name == stored.storage_name
    assert info.bytes == 5
    assert info.ext == "md"
    assert info.session_id == _SESSION_ID
    assert info.scope == "current"
    assert info.mtime_utc.endswith("+00:00")


def test_stat_missing_file_raises_not_found(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    with pytest.raises(SessionFileNotFoundError):
        repo.stat(_scope(), "ghost-0000.md")


def test_list_reports_entries_and_never_errors_when_empty(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    assert repo.list(_scope()) == []
    stored = repo.write_text(_scope(), "note.md", "hello")
    entries = repo.list(_scope())
    assert [e.storage_name for e in entries] == [stored.storage_name]
    assert entries[0].session_id == _SESSION_ID
    assert entries[0].scope == "current"


def test_list_ignores_the_events_log(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    repo.write_text(_scope(), "note.md", "hello")
    entries = repo.list(_scope())
    assert all(e.storage_name != "events.jsonl" for e in entries)


# --------------------------------------------------------------------- lifecycle


def test_written_file_is_loose_and_counts_toward_usage_and_delete(
    tmp_path: Path,
) -> None:
    repo, store = _make_repo(tmp_path)
    stored = repo.write_text(_scope(), "note.md", "hello world")

    events_path = tmp_path / _SESSION_ID / "events.jsonl"
    events_before = events_path.read_text(encoding="utf-8")
    # Writing a loose file appends no journal event.
    assert repo.write_text(_scope(), "again.md", "x")
    assert events_path.read_text(encoding="utf-8") == events_before

    usage = store.usage()
    session_usage = next(s for s in usage.sessions if s.session_id == _SESSION_ID)
    file_size = (tmp_path / _SESSION_ID / stored.storage_name).stat().st_size
    assert session_usage.bytes >= file_size

    store.delete_session(_SESSION_ID)
    assert not (tmp_path / _SESSION_ID).exists()


def test_write_refuses_and_creates_nothing_without_active_session(
    tmp_path: Path,
) -> None:
    # _OTHER_SESSION_ID has no journal events -> not visible.
    repo, _ = _make_repo(tmp_path, visible=(_SESSION_ID,))
    scope = SessionFileScope(
        write_session_id=_OTHER_SESSION_ID,
        read_session_ids=(_OTHER_SESSION_ID,),
    )
    with pytest.raises(NoActiveSessionError):
        repo.write_text(scope, "note.md", "x")
    assert not (tmp_path / _OTHER_SESSION_ID).exists()


def _assert_every_tool_reports_no_active_session(
    repo: SessionFileRepository, scope: SessionFileScope
) -> None:
    with pytest.raises(NoActiveSessionError):
        repo.write_text(scope, "note.md", "x")
    with pytest.raises(NoActiveSessionError):
        repo.write_bytes(scope, "pic.png", _PNG_BYTES)
    with pytest.raises(NoActiveSessionError):
        repo.read_text(scope, "note-0000.md")
    with pytest.raises(NoActiveSessionError):
        repo.view_image_bytes(scope, "pic-0000.png")
    with pytest.raises(NoActiveSessionError):
        repo.stat(scope, "note-0000.md")
    with pytest.raises(NoActiveSessionError):
        repo.list(scope)


def test_all_tools_error_when_scope_has_no_active_session(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    _assert_every_tool_reports_no_active_session(repo, _scope(None))


def test_reads_error_when_current_session_absent_despite_readable_scope(
    tmp_path: Path,
) -> None:
    # No active current session (write_session_id is None), yet an inherited
    # readable scope is present: the no-active-session gate is keyed on the
    # current session, so every tool must still refuse.
    repo, _ = _make_repo(tmp_path)
    scope = SessionFileScope(write_session_id=None, read_session_ids=(_SESSION_ID,))
    _assert_every_tool_reports_no_active_session(repo, scope)


def test_all_tools_error_when_current_session_not_journal_visible(
    tmp_path: Path,
) -> None:
    # _OTHER_SESSION_ID has a directory but no journal events -> not visible.
    repo, _ = _make_repo(tmp_path, visible=(_SESSION_ID,))
    (tmp_path / _OTHER_SESSION_ID).mkdir()
    scope = SessionFileScope(
        write_session_id=_OTHER_SESSION_ID,
        read_session_ids=(_OTHER_SESSION_ID,),
    )
    _assert_every_tool_reports_no_active_session(repo, scope)


def test_repeated_writes_of_one_name_never_overwrite(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    first = repo.write_text(_scope(), "note.md", "one")
    second = repo.write_text(_scope(), "note.md", "two")

    assert first.storage_name != second.storage_name
    session_dir = tmp_path / _SESSION_ID
    assert (session_dir / first.storage_name).read_text(encoding="utf-8") == "one"
    assert (session_dir / second.storage_name).read_text(encoding="utf-8") == "two"
