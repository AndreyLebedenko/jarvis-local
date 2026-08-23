from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from jarvis.core.config import FilesSettings
from jarvis.files import (
    NoActiveSessionError,
    SessionFileNotFoundError,
    SessionFileRepository,
    SessionFileScope,
    resolve_session_file_scope,
)
from jarvis.journal import JournalEvent, JournalStore

_CURRENT = "20260716-153000-cur1"
_PARENT = "20260716-152000-par1"
_GRAND = "20260716-151000-gr01"
_TS = "2026-07-16T15:30:00+01:00"


def _start(store: JournalStore, session_id: str) -> None:
    store.append(
        JournalEvent(
            session_id=session_id,
            timestamp=_TS,
            source="voice",
            role="user",
            text="hi",
            media=[],
            transcript=None,
        )
    )


def _fork(store: JournalStore, session_id: str, *, parent: object) -> None:
    store.append(
        JournalEvent(
            session_id=session_id,
            timestamp=_TS,
            source="fork",
            role="system",
            text="forked",
            media=[],
            transcript=None,
            metadata={"continued_from": parent},
        )
    )


def _repo(store: JournalStore) -> SessionFileRepository:
    return SessionFileRepository(
        store.root,
        config=FilesSettings(),
        session_is_visible=lambda sid: bool(store.read_session(sid).records),
    )


def _place(store: JournalStore, session_id: str, name: str, text: str) -> None:
    (store.root / session_id / name).write_text(text, encoding="utf-8")


# ------------------------------------------------------------ scope construction


def test_scope_follows_continued_from_chain_in_order(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    _start(store, _GRAND)
    _fork(store, _PARENT, parent=_GRAND)
    _fork(store, _CURRENT, parent=_PARENT)

    scope = resolve_session_file_scope(store, _CURRENT)

    assert scope.write_session_id == _CURRENT
    assert scope.read_session_ids == (_CURRENT, _PARENT, _GRAND)


def test_scope_stops_at_missing_ancestor(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    _fork(store, _CURRENT, parent="20260716-140000-gone")

    scope = resolve_session_file_scope(store, _CURRENT)

    assert scope.read_session_ids == (_CURRENT,)


def test_scope_stops_at_deleted_ancestor(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    _start(store, _PARENT)
    _fork(store, _CURRENT, parent=_PARENT)
    store.delete_session(_PARENT)

    scope = resolve_session_file_scope(store, _CURRENT)

    assert scope.read_session_ids == (_CURRENT,)


def test_scope_ignores_non_string_corrupt_provenance(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    _fork(store, _CURRENT, parent=123)

    scope = resolve_session_file_scope(store, _CURRENT)

    assert scope.read_session_ids == (_CURRENT,)


def test_scope_breaks_provenance_cycle(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    _fork(store, _CURRENT, parent=_PARENT)
    _fork(store, _PARENT, parent=_CURRENT)

    scope = resolve_session_file_scope(store, _CURRENT)

    assert scope.read_session_ids == (_CURRENT, _PARENT)


def test_scope_honours_depth_limit(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    _start(store, _GRAND)
    _fork(store, _PARENT, parent=_GRAND)
    _fork(store, _CURRENT, parent=_PARENT)

    scope = resolve_session_file_scope(store, _CURRENT, max_depth=1)

    assert scope.read_session_ids == (_CURRENT, _PARENT)


def test_scope_is_empty_without_current_session(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    assert resolve_session_file_scope(store, None) == SessionFileScope(None, ())


def test_scope_is_empty_when_current_not_journal_visible(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    (tmp_path / _CURRENT).mkdir()  # directory but no valid events
    assert resolve_session_file_scope(store, _CURRENT) == SessionFileScope(None, ())


# --------------------------------------------------------- multi-scope repository


def test_inherited_file_is_readable_while_writes_stay_current(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    _start(store, _PARENT)
    _fork(store, _CURRENT, parent=_PARENT)
    _place(store, _PARENT, "inherited-0001.txt", "from parent")
    repo = _repo(store)
    scope = resolve_session_file_scope(store, _CURRENT)

    assert repo.read_text(scope, "inherited-0001.txt") == "from parent"
    info = repo.stat(scope, "inherited-0001.txt")
    assert info.session_id == _PARENT
    assert info.scope == "inherited"

    written = repo.write_text(scope, "note.md", "child note")
    assert (tmp_path / _CURRENT / written.storage_name).exists()
    assert not (tmp_path / _PARENT / written.storage_name).exists()


@pytest.mark.parametrize("operation", ["read", "stat"])
def test_current_shadows_ancestor_for_reads(tmp_path: Path, operation: str) -> None:
    store = JournalStore(tmp_path)
    _start(store, _PARENT)
    _start(store, _CURRENT)
    _fork(store, _CURRENT, parent=_PARENT)
    _place(store, _PARENT, "dup-abcd.txt", "ancestor")
    _place(store, _CURRENT, "dup-abcd.txt", "current")
    repo = _repo(store)
    scope = resolve_session_file_scope(store, _CURRENT)

    if operation == "read":
        assert repo.read_text(scope, "dup-abcd.txt") == "current"
    else:
        info = repo.stat(scope, "dup-abcd.txt")
        assert info.session_id == _CURRENT
        assert info.scope == "current"


def test_current_shadows_ancestor_for_view(tmp_path: Path) -> None:
    # Two 1x1 PNGs that differ by a single pixel byte, so the returned bytes
    # identify which scope won.
    current_png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6360000002000154a24f0f0000000049454e44ae42"
        "6082"
    )
    ancestor_png = current_png[:-8] + bytes([0]) + current_png[-7:]
    store = JournalStore(tmp_path)
    _start(store, _PARENT)
    _start(store, _CURRENT)
    _fork(store, _CURRENT, parent=_PARENT)
    (store.root / _PARENT / "pic-abcd.png").write_bytes(ancestor_png)
    (store.root / _CURRENT / "pic-abcd.png").write_bytes(current_png)
    repo = _repo(store)
    scope = resolve_session_file_scope(store, _CURRENT)

    assert repo.view_image_bytes(scope, "pic-abcd.png").data == current_png


def test_list_exposes_both_origins_of_a_duplicate_storage_name(
    tmp_path: Path,
) -> None:
    store = JournalStore(tmp_path)
    _start(store, _PARENT)
    _start(store, _CURRENT)
    _fork(store, _CURRENT, parent=_PARENT)
    _place(store, _PARENT, "dup-abcd.txt", "ancestor")
    _place(store, _CURRENT, "dup-abcd.txt", "current")
    repo = _repo(store)
    scope = resolve_session_file_scope(store, _CURRENT)

    entries = [e for e in repo.list(scope) if e.storage_name == "dup-abcd.txt"]

    origins = {(e.session_id, e.scope) for e in entries}
    assert origins == {(_CURRENT, "current"), (_PARENT, "inherited")}


def test_scope_rebuild_is_live_when_an_ancestor_is_deleted(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    _start(store, _PARENT)
    _fork(store, _CURRENT, parent=_PARENT)
    _place(store, _PARENT, "inherited-0001.txt", "from parent")
    repo = _repo(store)

    before = resolve_session_file_scope(store, _CURRENT)
    assert repo.read_text(before, "inherited-0001.txt") == "from parent"

    shutil.rmtree(tmp_path / _PARENT)

    after = resolve_session_file_scope(store, _CURRENT)
    assert after.read_session_ids == (_CURRENT,)
    assert repo.list(after) == []
    with pytest.raises(SessionFileNotFoundError):
        repo.read_text(after, "inherited-0001.txt")


def test_resolved_empty_scope_makes_tools_report_no_active_session(
    tmp_path: Path,
) -> None:
    store = JournalStore(tmp_path)
    repo = _repo(store)
    scope = resolve_session_file_scope(store, None)

    with pytest.raises(NoActiveSessionError):
        repo.write_text(scope, "note.md", "x")
    with pytest.raises(NoActiveSessionError):
        repo.list(scope)
    assert list(tmp_path.iterdir()) == []
