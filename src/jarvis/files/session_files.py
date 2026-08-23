"""Loose per-session files the model can create and read (story-v1.8.1).

A session file is a plain file in an existing journal session directory
(`root/<session_id>/`), never a journal event: its content stays out of the
transcript, corpus, and semantic index, and it is discoverable only by the
generated storage name this repository returns. Writes always target the
current session so usage accounting and delete-with-session lifecycle stay
tied to the creating session; reads may span an ordered, read-only scope.

This module is pure logic over a filesystem: it takes a session-visibility
predicate rather than importing JournalStore, so the no-active-session
invariant is enforced without a journal dependency.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from jarvis.core.config import FilesSettings
from jarvis.journal.events import validate_relative_media_path

_EVENTS_FILE_NAME = "events.jsonl"
_IMAGE_MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}


@dataclass(frozen=True)
class SessionFileScope:
    """Ambient runtime file scope injected into the repository, never a
    model-supplied value. Writes target ``write_session_id``; reads/list/stat
    search ``read_session_ids`` in order (current first, ancestors after).
    ``write_session_id`` is None when no active session exists."""

    write_session_id: str | None
    read_session_ids: tuple[str, ...]


@dataclass(frozen=True)
class SessionFileWriteResult:
    storage_name: str
    bytes: int


@dataclass(frozen=True)
class SessionImageView:
    data: bytes
    media_type: str


@dataclass(frozen=True)
class SessionFileStat:
    storage_name: str
    bytes: int
    ext: str
    session_id: str
    scope: str
    mtime_utc: str


class SessionFileError(Exception):
    """Base for every typed session-file failure."""


class NoActiveSessionError(SessionFileError):
    """No active, journal-visible session for the requested operation."""


class InvalidFileNameError(SessionFileError):
    """Requested name is absolute, escapes the session dir, or is empty."""


class DeniedExtensionError(SessionFileError):
    """Requested extension is on the write deny-list."""


class FileTooLargeError(SessionFileError):
    """Write content or read/view target exceeds its configured cap."""


class SessionFileNotFoundError(SessionFileError):
    """No file with that storage name exists in the readable scope."""


class NotTextFileError(SessionFileError):
    """File exists but is not valid UTF-8 text."""


class UnsupportedImageError(SessionFileError):
    """File is not a supported (PNG/JPEG) image for viewing."""


def _extension_of(name: str) -> str:
    return PurePosixPath(name.replace("\\", "/")).suffix.lstrip(".").casefold()


def _generate_storage_name(requested_name: str) -> str:
    flat = PurePosixPath(requested_name.replace("\\", "/"))
    token = uuid4().hex
    base = f"{flat.stem}-{token}" if flat.stem else token
    return f"{base}{flat.suffix}"


class SessionFileRepository:
    def __init__(
        self,
        root: Path,
        *,
        config: FilesSettings,
        session_is_visible: Callable[[str], bool],
    ) -> None:
        self._root = Path(root)
        self._config = config
        self._session_is_visible = session_is_visible

    def write_text(
        self, scope: SessionFileScope, name: str, content: str
    ) -> SessionFileWriteResult:
        cap = self._config.max_text_write_chars
        if len(content) > cap:
            raise FileTooLargeError(f"text exceeds max_text_write_chars ({cap})")
        return self._create(
            scope, name, content.encode("utf-8"), enforce_blacklist=True
        )

    def write_bytes(
        self, scope: SessionFileScope, name: str, data: bytes
    ) -> SessionFileWriteResult:
        return self._create(scope, name, data, enforce_blacklist=False)

    def read_text(self, scope: SessionFileScope, name: str) -> str:
        path, _, _ = self._find_existing(scope, name)
        if path.stat().st_size > self._config.max_text_read_bytes:
            raise FileTooLargeError(
                f"file exceeds max_text_read_bytes ({self._config.max_text_read_bytes})"
            )
        try:
            return path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            raise NotTextFileError(
                f"{name} is not UTF-8 text; use stat or view instead"
            ) from None

    def view_image_bytes(self, scope: SessionFileScope, name: str) -> SessionImageView:
        path, _, _ = self._find_existing(scope, name)
        media_type = _IMAGE_MEDIA_TYPES.get(_extension_of(path.name))
        if media_type is None:
            raise UnsupportedImageError(f"{name} is not a PNG or JPEG image")
        if path.stat().st_size > self._config.max_image_view_bytes:
            raise FileTooLargeError(
                f"image exceeds max_image_view_bytes "
                f"({self._config.max_image_view_bytes})"
            )
        return SessionImageView(data=path.read_bytes(), media_type=media_type)

    def stat(self, scope: SessionFileScope, name: str) -> SessionFileStat:
        path, session_id, label = self._find_existing(scope, name)
        return self._stat_for(path, session_id, label)

    def list(self, scope: SessionFileScope) -> list[SessionFileStat]:
        self._require_active(scope)
        entries: list[SessionFileStat] = []
        shadowed: set[str] = set()
        for index, session_id in enumerate(scope.read_session_ids):
            session_dir = self._session_dir(session_id)
            if not session_dir.is_dir():
                continue
            label = "current" if index == 0 else "inherited"
            for child in sorted(session_dir.iterdir()):
                if not child.is_file() or child.name == _EVENTS_FILE_NAME:
                    continue
                if child.name in shadowed:
                    continue
                shadowed.add(child.name)
                entries.append(self._stat_for(child, session_id, label))
        return entries

    def _create(
        self,
        scope: SessionFileScope,
        name: str,
        data: bytes,
        *,
        enforce_blacklist: bool,
    ) -> SessionFileWriteResult:
        write_session_id = self._require_active(scope)
        self._validate_name(name)
        if enforce_blacklist and (
            _extension_of(name) in self._config.write_ext_blacklist
        ):
            raise DeniedExtensionError(f"{name} has a deny-listed extension")
        session_dir = self._session_dir(write_session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        while True:
            storage_name = _generate_storage_name(name)
            target = self._resolve_within(session_dir, storage_name)
            try:
                # Exclusive create ("x") is the create-only guarantee itself:
                # it fails rather than overwrite, closing the check-then-write
                # window a separate exists() test would leave open.
                with target.open("xb") as handle:
                    handle.write(data)
            except FileExistsError:
                continue
            return SessionFileWriteResult(storage_name=storage_name, bytes=len(data))

    def _find_existing(
        self, scope: SessionFileScope, name: str
    ) -> tuple[Path, str, str]:
        self._require_active(scope)
        self._validate_name(name)
        for index, session_id in enumerate(scope.read_session_ids):
            session_dir = self._session_dir(session_id)
            if not session_dir.is_dir():
                continue
            candidate = self._resolve_within(session_dir, name)
            if candidate.is_file():
                label = "current" if index == 0 else "inherited"
                return candidate, session_id, label
        raise SessionFileNotFoundError(f"{name} not found in session file scope")

    def _require_active(self, scope: SessionFileScope) -> str:
        """The single no-active-session gate for every file tool. The active
        session is the current one (``write_session_id``); reads may still span
        inherited scopes, but only while there is an active, journal-visible
        current session to anchor them. Returns the validated current id."""
        session_id = scope.write_session_id
        if session_id is None:
            raise NoActiveSessionError("no active session")
        if not self._session_is_visible(session_id):
            raise NoActiveSessionError("current session is not journal-visible")
        return session_id

    def _stat_for(self, path: Path, session_id: str, label: str) -> SessionFileStat:
        stat = path.stat()
        return SessionFileStat(
            storage_name=path.name,
            bytes=stat.st_size,
            ext=_extension_of(path.name),
            session_id=session_id,
            scope=label,
            mtime_utc=datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
        )

    @staticmethod
    def _validate_name(name: str) -> None:
        try:
            validate_relative_media_path(name)
        except ValueError as exc:
            raise InvalidFileNameError(str(exc)) from None

    def _session_dir(self, session_id: str) -> Path:
        root = self._root.resolve()
        candidate = (root / session_id).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            raise InvalidFileNameError(
                f"session id {session_id!r} escapes root"
            ) from None
        return candidate

    def _resolve_within(self, session_dir: Path, storage_name: str) -> Path:
        candidate = (session_dir / storage_name).resolve()
        try:
            candidate.relative_to(session_dir.resolve())
        except ValueError:
            raise InvalidFileNameError(
                f"{storage_name!r} escapes the session directory"
            ) from None
        return candidate
