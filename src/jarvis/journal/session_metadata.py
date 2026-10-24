from __future__ import annotations

import json
import os
import time
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SESSION_METADATA_FILE_NAME = "session.json"
SESSION_METADATA_VERSION = 1
MAX_SESSION_TITLE_CHARS = 80

_TITLE_KEY = "title"
_VERSION_KEY = "version"
_TEMP_SUFFIX = ".tmp"
_REPLACE_ATTEMPTS = 5
_REPLACE_RETRY_SECONDS = 0.02
_LINE_SEPARATORS = "\u2028\u2029"


class SessionTitleError(ValueError):
    """A refused title; `reason` is the stable code the HTTP API reports."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


TITLE_TOO_LONG = "title_too_long"
TITLE_INVALID = "title_invalid"


@dataclass(frozen=True)
class SessionMetadata:
    """User-owned facts about one session, kept apart from its event records.

    `extra` holds every key this version does not know, so a rewrite never
    drops what a later version stored."""

    title: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)
    version: int = SESSION_METADATA_VERSION


def normalize_session_title(raw: object) -> str | None:
    """The stored form of a typed title, or None for "no title" (a reset)."""
    if not isinstance(raw, str):
        raise SessionTitleError(TITLE_INVALID)
    title = raw.strip()
    if any(_is_control(char) for char in title):
        raise SessionTitleError(TITLE_INVALID)
    if title and not any(_is_visible(char) for char in title):
        raise SessionTitleError(TITLE_INVALID)
    if len(title) > MAX_SESSION_TITLE_CHARS:
        raise SessionTitleError(TITLE_TOO_LONG)
    return title or None


def read_session_metadata(session_dir: Path) -> SessionMetadata:
    """Never raises: a missing, unreadable or malformed file is no metadata."""
    try:
        document = json.loads(
            (session_dir / SESSION_METADATA_FILE_NAME).read_text(encoding="utf-8")
        )
    except (OSError, ValueError, RecursionError):
        return SessionMetadata()
    if not isinstance(document, dict):
        return SessionMetadata()
    return SessionMetadata(
        title=_stored_title(document.get(_TITLE_KEY)),
        extra={
            key: value
            for key, value in document.items()
            if key not in (_TITLE_KEY, _VERSION_KEY)
        },
        version=_stored_version(document.get(_VERSION_KEY)),
    )


def write_session_metadata(session_dir: Path, metadata: SessionMetadata) -> None:
    document: dict[str, Any] = {
        **metadata.extra,
        _VERSION_KEY: metadata.version,
    }
    if metadata.title is not None:
        document[_TITLE_KEY] = metadata.title
    target = session_dir / SESSION_METADATA_FILE_NAME
    temporary = target.with_name(target.name + _TEMP_SUFFIX)
    try:
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _replace_with_retry(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _replace_with_retry(source: Path, target: Path) -> None:
    """On Windows a reader that holds the target open blocks the replace for
    a moment; in-process readers are serialized by the store, so this covers
    other readers (a scanner, a second tool)."""
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_RETRY_SECONDS)


def _stored_title(value: object) -> str | None:
    try:
        return normalize_session_title(value)
    except SessionTitleError:
        return None


def _stored_version(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
        return value
    return SESSION_METADATA_VERSION


def _is_control(char: str) -> bool:
    return unicodedata.category(char) in ("Cc", "Cs") or char in _LINE_SEPARATORS


def _is_visible(char: str) -> bool:
    return unicodedata.category(char)[0] not in ("C", "Z")
