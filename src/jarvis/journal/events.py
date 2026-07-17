from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

_SESSION_ID_PATTERN = re.compile(r"\A\d{8}-\d{6}-[A-Za-z0-9_-]+\Z")
_VALID_ROLES = frozenset({"user", "assistant"})


@dataclass(frozen=True)
class JournalEvent:
    session_id: str
    timestamp: str
    source: str
    role: str
    text: str
    media: tuple[str, ...]
    transcript: str | None

    def __post_init__(self) -> None:
        if not _SESSION_ID_PATTERN.fullmatch(self.session_id):
            raise ValueError("session_id must match YYYYMMDD-HHMMSS-<short-random>")
        if not self.source:
            raise ValueError("source must not be empty")
        if self.role not in _VALID_ROLES:
            raise ValueError("role must be 'user' or 'assistant'")
        parse_journal_timestamp(self.timestamp)
        object.__setattr__(self, "media", tuple(self.media))
        for path in self.media:
            _validate_media_path(path)

    def to_json_line(self) -> str:
        payload = {
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "source": self.source,
            "role": self.role,
            "text": self.text,
            "media": list(self.media),
            "transcript": self.transcript,
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
        )


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


def _validate_media_path(value: str) -> None:
    if not value:
        raise ValueError("media paths must not be empty")
    if PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute():
        raise ValueError("media paths must be relative")
    if ".." in PurePosixPath(value).parts or ".." in PureWindowsPath(value).parts:
        raise ValueError("media paths must stay inside the session directory")


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


def _require_str_list(payload: dict[str, Any], field: str) -> list[str]:
    value = payload.get(field)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return list(value)


@dataclass(frozen=True)
class JournalEventAppended:
    event: JournalEvent
