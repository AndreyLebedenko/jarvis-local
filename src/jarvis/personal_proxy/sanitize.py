"""The sanitize stage: the local model turns the checked transcript into a
request that can go out, with typed placeholders and a mapping of originals, or
refuses it. Every failure is typed and nothing is sent or retried."""

from __future__ import annotations

from jarvis.core.config import PersonalProxySettings
from jarvis.personal_proxy.check_backend import CheckBackend
from jarvis.personal_proxy.check_result import CheckedTranscript
from jarvis.personal_proxy.sanitize_parsing import parse_sanitize_output
from jarvis.personal_proxy.sanitize_requests import build_sanitize_request
from jarvis.personal_proxy.sanitize_result import (
    NO_SPEECH_REASON,
    SanitizeFailure,
    SanitizeFailureClass,
    SanitizeResult,
    SanitizeVerdict,
)
from jarvis.personal_proxy.visible_text import has_visible_text


async def sanitize(
    checked_transcript: CheckedTranscript,
    topics: str,
    backend: CheckBackend,
    settings: PersonalProxySettings,
) -> SanitizeResult | SanitizeFailure:
    text = checked_transcript.text
    if not has_visible_text(text):
        return SanitizeResult(SanitizeVerdict.REFUSE, NO_SPEECH_REASON, "", {})
    request = build_sanitize_request(text, topics, settings.check_temperature)
    try:
        reply = await backend.complete(request)
    except Exception:
        return SanitizeFailure(SanitizeFailureClass.BACKEND_FAILED)
    if not isinstance(reply, str):
        return SanitizeFailure(SanitizeFailureClass.BACKEND_FAILED)
    return parse_sanitize_output(reply)
