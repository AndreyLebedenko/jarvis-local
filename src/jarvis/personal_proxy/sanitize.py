"""The sanitize stage: the local model turns the checked transcript into a
request that can go out, with typed placeholders and a mapping of originals, or
refuses it. Every failure is typed and nothing is sent.

The one retry is the same request to the same local model, so nothing leaves the
machine and the output is parsed and validated as usual. It covers a malformed
answer and a refusal that no topic can explain; it never covers an unreachable
backend, a refusal while topics exist, or the "no speech" refusal. The second
outcome is final."""

from __future__ import annotations

from jarvis.core.config import PersonalProxySettings
from jarvis.personal_proxy.check_backend import ChatRequest, CheckBackend
from jarvis.personal_proxy.check_result import CheckedTranscript
from jarvis.personal_proxy.sanitize_parsing import parse_sanitize_output
from jarvis.personal_proxy.sanitize_prompts import topics_present
from jarvis.personal_proxy.sanitize_requests import build_sanitize_request
from jarvis.personal_proxy.sanitize_result import (
    NO_SPEECH_REASON,
    SanitizeFailure,
    SanitizeFailureClass,
    SanitizeResult,
    SanitizeVerdict,
)
from jarvis.personal_proxy.visible_text import has_visible_text

SANITIZE_RETRIES = 1

_RETRYABLE_FAILURES = frozenset(
    {
        SanitizeFailureClass.EMPTY,
        SanitizeFailureClass.BAD_PLACEHOLDER,
        SanitizeFailureClass.EMPTY_SANITIZED_TEXT,
        SanitizeFailureClass.EMPTY_MAPPING_VALUE,
        SanitizeFailureClass.NO_JSON,
        SanitizeFailureClass.EXTRA_PROSE,
        SanitizeFailureClass.MISSING_FIELD,
        SanitizeFailureClass.WRONG_TYPE,
        SanitizeFailureClass.BAD_VERDICT,
    }
)

Outcome = SanitizeResult | SanitizeFailure


async def sanitize(
    checked_transcript: CheckedTranscript,
    topics: str,
    backend: CheckBackend,
    settings: PersonalProxySettings,
) -> Outcome:
    return await sanitize_with_retries(
        checked_transcript, topics, backend, settings, SANITIZE_RETRIES
    )


async def sanitize_with_retries(
    checked_transcript: CheckedTranscript,
    topics: str,
    backend: CheckBackend,
    settings: PersonalProxySettings,
    retries: int,
) -> Outcome:
    text = checked_transcript.text
    if not has_visible_text(text):
        return SanitizeResult(SanitizeVerdict.REFUSE, NO_SPEECH_REASON, "", {})
    request = build_sanitize_request(text, topics, settings.check_temperature)
    has_topics = topics_present(topics)
    outcome = await _attempt(request, backend)
    for _ in range(retries):
        if not _is_retryable(outcome, has_topics):
            break
        outcome = await _attempt(request, backend)
    if _is_refusal_without_a_cause(outcome, has_topics):
        return SanitizeFailure(SanitizeFailureClass.UNEXPECTED_REFUSAL)
    return outcome


async def _attempt(request: ChatRequest, backend: CheckBackend) -> Outcome:
    try:
        reply = await backend.complete(request)
    except Exception:
        return SanitizeFailure(SanitizeFailureClass.BACKEND_FAILED)
    if not isinstance(reply, str):
        return SanitizeFailure(SanitizeFailureClass.BACKEND_FAILED)
    return parse_sanitize_output(reply)


def _is_retryable(outcome: Outcome, has_topics: bool) -> bool:
    if isinstance(outcome, SanitizeFailure):
        return outcome.failure in _RETRYABLE_FAILURES
    return _is_refusal_without_a_cause(outcome, has_topics)


def _is_refusal_without_a_cause(outcome: Outcome, has_topics: bool) -> bool:
    return (
        isinstance(outcome, SanitizeResult)
        and outcome.verdict is SanitizeVerdict.REFUSE
        and not has_topics
        and outcome.reason.strip().casefold() != NO_SPEECH_REASON
    )
