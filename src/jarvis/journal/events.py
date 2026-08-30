from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

_SESSION_ID_PATTERN = re.compile(r"\A\d{8}-\d{6}-[A-Za-z0-9_-]+\Z")
_VALID_ROLES = frozenset({"user", "assistant", "system"})

JSONScalar = str | int | float | bool | None
JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


@dataclass(frozen=True)
class JournalEventRef:
    session_id: str
    event_position: int

    def __post_init__(self) -> None:
        if not _SESSION_ID_PATTERN.fullmatch(self.session_id):
            raise ValueError("session_id must match YYYYMMDD-HHMMSS-<short-random>")
        if (
            isinstance(self.event_position, bool)
            or not isinstance(self.event_position, int)
            or self.event_position < 0
        ):
            raise ValueError("event_position must be a non-negative integer")


class TurnOutcome(Enum):
    """How a turn ended without a normal completed answer (task-v1.7.0-3).
    Stored as ``metadata["outcome"]`` on an assistant JournalEvent, and used
    to pick the ConversationHistory system note - see
    Orchestrator.record_aborted_turn() in app.py.

    FAILED specifically means no response was ever produced (the
    backend/dispatch call itself failed) - deliberately not a generic
    "something went wrong" value, so the journal never tells a user "no
    response - backend error" for a turn the model actually answered.

    A third outcome for "the model answered but TTS failed to flush/play
    it" was considered and rejected (task-v1.7.0-3 review, second round):
    the real TtsOutput.on_response_complete() only performs synchronous,
    in-memory buffer operations and cannot raise, and every real
    synthesis/playback failure surfaces later, through wait_for_pending(),
    by which point the turn is already fully and correctly recorded - there
    is no reachable gap to label."""

    INTERRUPTED = "interrupted"
    FAILED = "failed"
    # A recognized mode-switch voice command (story-v1.9.0, task 4): the
    # turn was obeyed, not interrupted and not failed - there was simply
    # no answer to produce. A distinct member rather than reusing
    # INTERRUPTED keeps every journal consumer that already knows the two
    # task-v1.7.0-3 values from misreporting an obeyed command as cut
    # short; the journal UI renders it through the same
    # journal_outcome_* i18n mechanism.
    MODE_SWITCHED = "mode_switched"


@dataclass(frozen=True)
class JournalEvent:
    session_id: str
    timestamp: str
    source: str
    role: str
    text: str
    media: tuple[str, ...]
    transcript: str | None
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _SESSION_ID_PATTERN.fullmatch(self.session_id):
            raise ValueError("session_id must match YYYYMMDD-HHMMSS-<short-random>")
        if not self.source:
            raise ValueError("source must not be empty")
        if self.role not in _VALID_ROLES:
            raise ValueError("role must be 'user', 'assistant', or 'system'")
        parse_journal_timestamp(self.timestamp)
        object.__setattr__(self, "media", tuple(self.media))
        for path in self.media:
            validate_relative_media_path(path)
        _validate_metadata(self.metadata)
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_json_line(self) -> str:
        payload = {
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "source": self.source,
            "role": self.role,
            "text": self.text,
            "media": list(self.media),
            "transcript": self.transcript,
            "metadata": self.metadata,
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"

    @classmethod
    def from_json_line(cls, line: str) -> JournalEvent:
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError("journal event must be a JSON object")
        return cls(
            session_id=_require_str(payload, "session_id"),
            timestamp=_require_str(payload, "timestamp"),
            source=_require_str(payload, "source"),
            role=_require_str(payload, "role"),
            text=_require_str(payload, "text"),
            media=_require_str_list(payload, "media"),
            transcript=_require_optional_str(payload, "transcript"),
            metadata=_require_metadata(payload),
        )


@dataclass(frozen=True)
class JournalEventRecord:
    reference: JournalEventRef
    event: JournalEvent

    def __post_init__(self) -> None:
        if self.reference.session_id != self.event.session_id:
            raise ValueError("journal event reference session_id must match the event")


def new_session_id(now: datetime | None = None, *, random_bytes: int = 3) -> str:
    if random_bytes < 1:
        raise ValueError("random_bytes must be positive")
    if now is None:
        timestamp = datetime.now().astimezone()
    else:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("session id timestamp must include timezone")
        timestamp = now.astimezone()
    return f"{timestamp.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(random_bytes)}"


def parse_journal_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("timestamp must be ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return parsed


def validate_relative_media_path(value: str) -> None:
    """The one relative-path containment predicate for anything written into a
    session directory: journal event media here, and loose session files in
    jarvis.files. Rejects empty, absolute, and `..`-bearing paths; the caller
    still resolves the final path against the session dir for defense in depth."""
    if not value:
        raise ValueError("media paths must not be empty")
    if PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute():
        raise ValueError("media paths must be relative")
    if ".." in PurePosixPath(value).parts or ".." in PureWindowsPath(value).parts:
        raise ValueError("media paths must stay inside the session directory")


def _validate_metadata(value: dict[str, JSONValue]) -> None:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("metadata must be a JSON object")
    for item in value.values():
        _validate_json_value(item)


def _validate_json_value(value: JSONValue) -> None:
    if value is None or isinstance(value, str | int | float | bool):
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item)
        return
    if isinstance(value, dict):
        _validate_metadata(value)
        return
    raise ValueError("metadata must contain only JSON values")


def _require_str(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _require_optional_str(payload: dict[str, Any], field: str) -> str | None:
    value = payload.get(field)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{field} must be a string or null")
    return value


def _require_metadata(payload: dict[str, Any]) -> dict[str, JSONValue]:
    value = payload.get("metadata", {})
    if not isinstance(value, dict):
        raise ValueError("metadata must be a JSON object")
    metadata = dict(value)
    _validate_metadata(metadata)
    return metadata


def _require_str_list(payload: dict[str, Any], field: str) -> list[str]:
    value = payload.get(field)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return list(value)


@dataclass(frozen=True)
class JournalEventAppended:
    reference: JournalEventRef
    event: JournalEvent
