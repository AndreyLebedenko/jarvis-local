"""One server-sent event of an OpenAI-compatible chat stream."""

from __future__ import annotations

import json
from dataclasses import dataclass

from jarvis.personal_proxy.external_error import (
    ExternalClientError,
    ExternalErrorKind,
)

_DONE = "[DONE]"
_DATA_PREFIX = "data:"
_INVALID = object()


@dataclass(frozen=True)
class StreamEvent:
    text: str = ""
    finish_reason: str | None = None
    done: bool = False


def _bad_stream() -> ExternalClientError:
    return ExternalClientError(ExternalErrorKind.BAD_STREAM)


def _parse_json(data: str) -> object:
    try:
        return json.loads(data)
    except (ValueError, RecursionError):
        return _INVALID


def _first_choice(document: dict) -> dict | None:
    """Only the choice with index 0 (or without an index) is the answer."""
    choices = document.get("choices")
    if choices is None:
        return None
    if not isinstance(choices, list):
        raise _bad_stream()
    selected = None
    for choice in choices:
        if not isinstance(choice, dict):
            raise _bad_stream()
        if selected is None and choice.get("index", 0) == 0:
            selected = choice
    return selected


def _delta_text(choice: dict) -> str:
    delta = choice.get("delta")
    if delta is None:
        return ""
    if not isinstance(delta, dict):
        raise _bad_stream()
    content = delta.get("content")
    if content is None:
        return ""
    if not isinstance(content, str):
        raise _bad_stream()
    return content


def _finish_reason(choice: dict) -> str | None:
    reason = choice.get("finish_reason")
    if reason is not None and not isinstance(reason, str):
        raise _bad_stream()
    return reason


def parse_event_line(line: str) -> StreamEvent | None:
    """None for a line that is not a data event (blank, comment, other field)."""
    if not line.startswith(_DATA_PREFIX):
        return None
    data = line[len(_DATA_PREFIX) :].strip()
    if data == _DONE:
        return StreamEvent(done=True)
    document = _parse_json(data)
    if not isinstance(document, dict):
        raise _bad_stream()
    if document.get("error") is not None:
        raise _bad_stream()
    choice = _first_choice(document)
    if choice is None:
        return StreamEvent()
    return StreamEvent(text=_delta_text(choice), finish_reason=_finish_reason(choice))
