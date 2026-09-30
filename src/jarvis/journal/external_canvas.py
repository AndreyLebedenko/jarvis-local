"""Vocabulary for answers produced by an external assistant and journaled here.

An external canvas is stored as one ``role="assistant"`` event whose source is
``MCP_CANVAS_SOURCE``. The journal role stays ``assistant`` so replay and the
derivative locator index work unchanged; provenance, not role, says the text
is not Jarvis's own claim. This module is pure and dependency-light so the
recorder, provenance, fork, and tool layers can share it without cycles.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from jarvis.journal.events import JSONValue

MCP_CANVAS_SOURCE = "mcp_canvas"

CALLER_METADATA_KEY = "caller"
SPEECH_ORIGIN_METADATA_KEY = "speech_origin"
SPEECH_STATUS_METADATA_KEY = "speech_status"
GUIDANCE_METADATA_KEY = "guidance"
_CALLER_NAME_KEY = "name"
_CALLER_VERSION_KEY = "version"
_CALLER_TRANSPORT_SESSION_KEY = "transport_session_id"


class SpeechOrigin(Enum):
    """Where the spoken form of a canvas came from."""

    DERIVATIVE = "derivative"
    VERBATIM = "verbatim"
    CALLER = "caller"


class SpeechStatus(Enum):
    """What happened to the speech of a canvas.

    ``MUTED`` means the speech was produced and stored but not played because
    the global TTS switch was off.
    """

    SPOKEN = "spoken"
    MUTED = "muted"
    INTERRUPTED = "interrupted"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class ExternalCanvasCaller:
    """Who sent the canvas. Every field is nullable: a caller may send none."""

    name: str | None = None
    version: str | None = None
    transport_session_id: str | None = None

    def to_metadata(self) -> dict[str, JSONValue]:
        return {
            _CALLER_NAME_KEY: self.name,
            _CALLER_VERSION_KEY: self.version,
            _CALLER_TRANSPORT_SESSION_KEY: self.transport_session_id,
        }


def caller_name_from_metadata(metadata: Mapping[str, JSONValue]) -> str | None:
    caller = metadata.get(CALLER_METADATA_KEY)
    if not isinstance(caller, dict):
        return None
    name = caller.get(_CALLER_NAME_KEY)
    return name if isinstance(name, str) else None
