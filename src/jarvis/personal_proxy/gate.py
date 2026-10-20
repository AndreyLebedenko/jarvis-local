"""The deterministic gate over a built outbound payload.

It fails closed: any error, an input that is not a built payload with a gate
context, a payload that is not exactly (system, user) with non-empty text, a
message that is empty after normalization, and text above a length cap all end
as a block. A block names the stage that failed, never the cause.

Each message is checked under two readings of the zero-width space (see
`normalize`) when the two readings differ.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from jarvis.personal_proxy.detectors import PATTERN_DETECTORS
from jarvis.personal_proxy.findings import (
    Finding,
    GateCategory,
    GateResult,
    GateStage,
)
from jarvis.personal_proxy.gate_context import GateContext
from jarvis.personal_proxy.normalize import NormalizedMessage, normalize_message
from jarvis.personal_proxy.original_values import find_original_values
from jarvis.personal_proxy.payload import OutboundMessage, OutboundPayload
from jarvis.personal_proxy.spans import Span
from jarvis.personal_proxy.topic_lines import find_topic_lines

MAX_MESSAGE_LENGTH = 20000
MAX_TOPICS_LENGTH = 50000
_EXPECTED_ROLES = ("system", "user")

_T = TypeVar("_T")


class _StageFailure(Exception):
    def __init__(self, stage: GateStage, message_index: int) -> None:
        super().__init__(stage.value)
        self.stage = stage
        self.message_index = message_index


def _run(
    stage: GateStage, index: int, function: Callable[..., _T], *args: object
) -> _T:
    try:
        return function(*args)
    except Exception:
        raise _StageFailure(stage, index) from None


def _pattern_spans(text: str) -> list[tuple[GateCategory, Span]]:
    claimed: list[Span] = []
    found: list[tuple[GateCategory, Span]] = []
    for category, detect in PATTERN_DETECTORS:
        for span in detect(text):
            if any(span.overlaps(other) for other in claimed):
                continue
            claimed.append(span)
            found.append((category, span))
    return found


def _readings(content: str) -> list[NormalizedMessage]:
    dropped = normalize_message(content)
    spaced = normalize_message(content, zero_width_as_space=True)
    return [dropped] if spaced.text == dropped.text else [dropped, spaced]


def _normalized_texts(context: GateContext) -> tuple[list[str], str]:
    originals = [normalize_message(value).text for value in context.mapping.values()]
    return originals, normalize_message(context.topics_text).text


def _reading_findings(
    index: int,
    reading: NormalizedMessage,
    exact_only: bool,
    originals: list[str],
    topics: str,
) -> list[Finding]:
    text = reading.text
    spans = _run(GateStage.PATTERNS, index, _pattern_spans, text)
    spans += [
        (GateCategory.MAPPING_ORIGINAL, span)
        for span in _run(
            GateStage.MAPPING, index, find_original_values, text, originals, exact_only
        )
    ]
    spans += [
        (GateCategory.TOPIC_TEXT, span)
        for span in _run(GateStage.TOPICS, index, find_topic_lines, text, topics)
    ]
    findings = []
    for category, span in spans:
        original = reading.original_span(span)
        findings.append(Finding(category, index, original.start, original.end))
    return findings


def _message_findings(
    index: int, message: OutboundMessage, originals: list[str], topics: str
) -> list[Finding]:
    content = message.content
    if not isinstance(content, str) or not content:
        raise _StageFailure(GateStage.INPUT, index)
    if len(content) > MAX_MESSAGE_LENGTH:
        raise _StageFailure(GateStage.LENGTH, index)
    readings = _run(GateStage.NORMALIZATION, index, _readings, content)
    if not readings[0].text.strip():
        raise _StageFailure(GateStage.EMPTY, index)
    findings: list[Finding] = []
    for reading in readings:
        found = _reading_findings(
            index, reading, message.role == "system", originals, topics
        )
        findings += [finding for finding in found if finding not in findings]
    return findings


def _has_expected_shape(payload: OutboundPayload) -> bool:
    messages = payload.messages
    return tuple(message.role for message in messages) == _EXPECTED_ROLES


def _check(payload: object, context: object) -> list[Finding]:
    if not isinstance(payload, OutboundPayload) or not isinstance(context, GateContext):
        raise _StageFailure(GateStage.INPUT, -1)
    if not _has_expected_shape(payload):
        raise _StageFailure(GateStage.INPUT, -1)
    if len(context.topics_text) > MAX_TOPICS_LENGTH:
        raise _StageFailure(GateStage.LENGTH, -1)
    originals, topics = _run(GateStage.NORMALIZATION, -1, _normalized_texts, context)
    findings: list[Finding] = []
    for index, message in enumerate(payload.messages):
        findings += _message_findings(index, message, originals, topics)
    return findings


def _error(stage: GateStage, index: int) -> GateResult:
    return GateResult((Finding(GateCategory.GATE_ERROR, index, 0, 0, stage),))


def check_outbound_payload(payload: object, context: object) -> GateResult:
    try:
        return GateResult(tuple(_check(payload, context)))
    except _StageFailure as failure:
        return _error(failure.stage, failure.message_index)
    except Exception:
        return _error(GateStage.UNKNOWN, -1)
