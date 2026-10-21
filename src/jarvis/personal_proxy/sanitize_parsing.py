"""Strict parser and validator of the sanitize output. No salvage: anything
that is not exactly one JSON object with the required fields, or that breaks a
rule below, is a typed failure and the request is not sent."""

from __future__ import annotations

import json
import re

from jarvis.personal_proxy.sanitize_prompts import PLACEHOLDER_TYPES
from jarvis.personal_proxy.sanitize_result import (
    MAX_REASON_LENGTH,
    SanitizeFailure,
    SanitizeFailureClass,
    SanitizeResult,
    SanitizeVerdict,
)
from jarvis.personal_proxy.visible_text import has_visible_text

LENGTH_DONE_REASON = "length"
_BYTE_ORDER_MARK = "﻿"
_REQUIRED_FIELDS = ("verdict", "reason", "sanitized_text", "mapping")
_PLACEHOLDER = re.compile(rf"<(?:{'|'.join(PLACEHOLDER_TYPES)})_[1-9][0-9]*>")


def parse_sanitize_output(
    text: str, done_reason: str | None = None
) -> SanitizeResult | SanitizeFailure:
    if done_reason == LENGTH_DONE_REASON:
        return SanitizeFailure(SanitizeFailureClass.TRUNCATED)
    stripped = text.strip().removeprefix(_BYTE_ORDER_MARK).strip()
    if not stripped:
        return SanitizeFailure(SanitizeFailureClass.EMPTY)
    document = _load_object(stripped)
    if isinstance(document, SanitizeFailure):
        return document
    return _validate(document)


class _DuplicateKeyError(Exception):
    pass


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict:
    document = dict(pairs)
    if len(document) != len(pairs):
        raise _DuplicateKeyError
    return document


def _decode(text: str) -> object:
    return json.loads(text, object_pairs_hook=_object_without_duplicates)


def _load_object(stripped: str) -> dict | SanitizeFailure:
    try:
        document = _decode(stripped)
    except _DuplicateKeyError:
        return SanitizeFailure(SanitizeFailureClass.WRONG_TYPE)
    except (ValueError, RecursionError):
        return _failure_for_non_json(stripped)
    if not isinstance(document, dict):
        return SanitizeFailure(SanitizeFailureClass.WRONG_TYPE)
    return document


def _failure_for_non_json(stripped: str) -> SanitizeFailure:
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        try:
            _decode(stripped[start : end + 1])
        except _DuplicateKeyError:
            return SanitizeFailure(SanitizeFailureClass.EXTRA_PROSE)
        except (ValueError, RecursionError):
            return SanitizeFailure(SanitizeFailureClass.NO_JSON)
        return SanitizeFailure(SanitizeFailureClass.EXTRA_PROSE)
    return SanitizeFailure(SanitizeFailureClass.NO_JSON)


def _validate(document: dict) -> SanitizeResult | SanitizeFailure:
    if any(name not in document for name in _REQUIRED_FIELDS):
        return SanitizeFailure(SanitizeFailureClass.MISSING_FIELD)
    verdict_value = document["verdict"]
    if not isinstance(verdict_value, str):
        return SanitizeFailure(SanitizeFailureClass.WRONG_TYPE)
    try:
        verdict = SanitizeVerdict(verdict_value)
    except ValueError:
        return SanitizeFailure(SanitizeFailureClass.BAD_VERDICT)
    reason = document["reason"]
    sanitized_text = document["sanitized_text"]
    mapping = document["mapping"]
    if not (isinstance(reason, str) and isinstance(sanitized_text, str)):
        return SanitizeFailure(SanitizeFailureClass.WRONG_TYPE)
    if not isinstance(mapping, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in mapping.items()
    ):
        return SanitizeFailure(SanitizeFailureClass.WRONG_TYPE)
    if verdict is SanitizeVerdict.REFUSE:
        return SanitizeResult(verdict, reason[:MAX_REASON_LENGTH], "", {})
    return _validated_send(sanitized_text, mapping)


def _validated_send(
    sanitized_text: str, mapping: dict[str, str]
) -> SanitizeResult | SanitizeFailure:
    if not has_visible_text(sanitized_text):
        return SanitizeFailure(SanitizeFailureClass.EMPTY_SANITIZED_TEXT)
    if not all(_PLACEHOLDER.fullmatch(key) for key in mapping):
        return SanitizeFailure(SanitizeFailureClass.BAD_PLACEHOLDER)
    if not all(value.strip() for value in mapping.values()):
        return SanitizeFailure(SanitizeFailureClass.EMPTY_MAPPING_VALUE)
    return SanitizeResult(SanitizeVerdict.SEND, "", sanitized_text, mapping)
