"""Strict parser of the sanitize pass output for the personal-proxy spike.

The card counts anything that is not exactly one JSON object with the
required fields as a validity failure, classified so the report can say how
each arm failed. A salvage parser would hide the very thing being measured.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

from manual.personal_proxy_corpus import Verdict

LENGTH_DONE_REASON = "length"


class FailureClass(StrEnum):
    EMPTY = "empty"
    TRUNCATED = "truncated"
    NO_JSON = "no_json"
    EXTRA_PROSE = "extra_prose"
    MISSING_FIELD = "missing_field"
    WRONG_TYPE = "wrong_type"
    BAD_VERDICT = "bad_verdict"


@dataclass(frozen=True)
class ParsedOutput:
    verdict: Verdict
    reason: str
    raw_transcript: str | None
    sanitized_text: str
    mapping: dict[str, str]


@dataclass(frozen=True)
class ParseFailure:
    failure: FailureClass
    detail: str = ""


def parse_sanitize_output(
    text: str, done_reason: str | None, *, require_raw_transcript: bool
) -> ParsedOutput | ParseFailure:
    if done_reason == LENGTH_DONE_REASON:
        return ParseFailure(FailureClass.TRUNCATED)
    stripped = text.strip()
    if not stripped:
        return ParseFailure(FailureClass.EMPTY)
    document = _load_object(stripped)
    if isinstance(document, ParseFailure):
        return document
    return _validate(document, require_raw_transcript)


def _load_object(stripped: str) -> dict | ParseFailure:
    try:
        document = json.loads(stripped)
    except json.JSONDecodeError:
        return _failure_for_non_json(stripped)
    if not isinstance(document, dict):
        return ParseFailure(FailureClass.WRONG_TYPE, "top level is not an object")
    return document


def _failure_for_non_json(stripped: str) -> ParseFailure:
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        try:
            json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return ParseFailure(FailureClass.NO_JSON)
        return ParseFailure(FailureClass.EXTRA_PROSE)
    return ParseFailure(FailureClass.NO_JSON)


def _validate(
    document: dict, require_raw_transcript: bool
) -> ParsedOutput | ParseFailure:
    required = ["verdict", "reason", "sanitized_text", "mapping"]
    if require_raw_transcript:
        required.append("raw_transcript")
    for name in required:
        if name not in document:
            return ParseFailure(FailureClass.MISSING_FIELD, name)
    verdict_value = document["verdict"]
    if not isinstance(verdict_value, str):
        return ParseFailure(FailureClass.WRONG_TYPE, "verdict")
    try:
        verdict = Verdict(verdict_value)
    except ValueError:
        return ParseFailure(FailureClass.BAD_VERDICT, verdict_value)
    for name in ("reason", "sanitized_text"):
        if not isinstance(document[name], str):
            return ParseFailure(FailureClass.WRONG_TYPE, name)
    raw_transcript = document.get("raw_transcript") if require_raw_transcript else None
    if require_raw_transcript and not isinstance(raw_transcript, str):
        return ParseFailure(FailureClass.WRONG_TYPE, "raw_transcript")
    mapping = document["mapping"]
    if not isinstance(mapping, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in mapping.items()
    ):
        return ParseFailure(FailureClass.WRONG_TYPE, "mapping")
    return ParsedOutput(
        verdict=verdict,
        reason=document["reason"],
        raw_transcript=raw_transcript,
        sanitized_text=document["sanitized_text"],
        mapping=dict(mapping),
    )
