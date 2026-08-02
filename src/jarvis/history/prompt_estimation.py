"""Shared prompt-message estimation helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from jarvis.history.context_budget import PromptEstimateMaterial, PromptTokenEstimator


def canonical_prompt_message(message: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in message.items() if key != "images"}


def estimate_prompt_tokens(
    messages: Sequence[Mapping[str, object]],
    estimator: PromptTokenEstimator,
) -> int:
    estimation_messages = tuple(
        canonical_prompt_message(message) for message in messages
    )
    payload = json.dumps(
        list(estimation_messages),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return estimator.estimate_tokens(
        PromptEstimateMaterial(
            canonical_utf8_bytes=len(payload.encode("utf-8")),
            message_count=len(estimation_messages),
            tool_count=0,
        )
    )
