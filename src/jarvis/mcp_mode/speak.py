"""The `speak` tool's rules, free of any transport: argument validation into a
`VoiceGuideRequest`, and an `EnqueueResult` into the tool's result.

Every refusal is a `SpeakError` whose `text` starts with a stable,
machine-readable code, so the server only has to wrap it in an error result.
Error texts name limits, never the caller's text.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from jarvis.core.config import McpModeSettings
from jarvis.dialog.voice_guide import (
    EnqueueResult,
    VoiceGuideAccepted,
    VoiceGuideRejection,
    VoiceGuideRequest,
)
from jarvis.journal.external_canvas import ExternalCanvasCaller, SpeechOrigin


class SpeakErrorCode(Enum):
    EMPTY_CANVAS = "empty_canvas"
    CANVAS_TOO_LONG = "canvas_too_long"
    EMPTY_SPOKEN_TEXT = "empty_spoken_text"
    SPOKEN_TEXT_TOO_LONG = "spoken_text_too_long"
    GUIDANCE_TOO_LONG = "guidance_too_long"
    QUEUE_FULL = "queue_full"
    CLOSED = "closed"


@dataclass(frozen=True)
class SpeakError:
    code: SpeakErrorCode
    detail: str

    @property
    def text(self) -> str:
        return f"{self.code.value}: {self.detail}"


@dataclass(frozen=True)
class SpeakQueued:
    position: int
    speech_origin: SpeechOrigin
    guidance_ignored: bool = False

    def payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": "queued",
            "position": self.position,
            "speech_origin": self.speech_origin.value,
        }
        if self.guidance_ignored:
            payload["guidance_ignored"] = True
        return payload


_REJECTION_ERRORS: dict[VoiceGuideRejection, SpeakError] = {
    VoiceGuideRejection.QUEUE_FULL: SpeakError(
        SpeakErrorCode.QUEUE_FULL,
        "too many calls are waiting to be spoken; try again later",
    ),
    VoiceGuideRejection.CLOSED: SpeakError(
        SpeakErrorCode.CLOSED, "Jarvis is shutting down and accepts no calls"
    ),
}


def request_or_error(
    canvas: str,
    spoken_text: str | None,
    guidance: str | None,
    *,
    limits: McpModeSettings,
    caller: ExternalCanvasCaller,
) -> VoiceGuideRequest | SpeakError:
    """The first failing check wins, in this order: canvas, spoken text,
    guidance. A blank guidance counts as absent."""
    if guidance is not None and not guidance.strip():
        guidance = None
    error = (
        _canvas_error(canvas, limits.max_canvas_chars)
        or _spoken_text_error(spoken_text, limits.max_spoken_text_chars)
        or _too_long_error(
            guidance, limits.max_guidance_chars, SpeakErrorCode.GUIDANCE_TOO_LONG
        )
    )
    if error is not None:
        return error
    return VoiceGuideRequest(
        canvas=canvas, spoken_text=spoken_text, guidance=guidance, caller=caller
    )


def queued_or_error(
    request: VoiceGuideRequest, result: EnqueueResult
) -> SpeakQueued | SpeakError:
    if not isinstance(result, VoiceGuideAccepted):
        return _REJECTION_ERRORS[result.reason]
    return SpeakQueued(
        position=result.position,
        speech_origin=result.speech_origin,
        guidance_ignored=(
            request.guidance is not None and request.spoken_text is not None
        ),
    )


def _canvas_error(canvas: str, limit: int) -> SpeakError | None:
    if not canvas.strip():
        return SpeakError(SpeakErrorCode.EMPTY_CANVAS, "canvas must not be blank")
    return _too_long_error(canvas, limit, SpeakErrorCode.CANVAS_TOO_LONG)


def _spoken_text_error(spoken_text: str | None, limit: int) -> SpeakError | None:
    if spoken_text is not None and not spoken_text.strip():
        return SpeakError(
            SpeakErrorCode.EMPTY_SPOKEN_TEXT,
            "spoken_text must not be blank; omit it to have the canvas spoken",
        )
    return _too_long_error(spoken_text, limit, SpeakErrorCode.SPOKEN_TEXT_TOO_LONG)


def _too_long_error(
    value: str | None, limit: int, code: SpeakErrorCode
) -> SpeakError | None:
    if value is None or len(value) <= limit:
        return None
    return SpeakError(
        code, f"{len(value)} characters given, the limit is {limit} characters"
    )
