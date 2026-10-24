"""Builds the restoration request: one sentence, text only, no format."""

from __future__ import annotations

import json
from collections.abc import Mapping

from jarvis.core.config import GenerationOptions
from jarvis.personal_proxy.check.check_backend import ChatRequest

NUM_PREDICT = 512

RESTORE_RULES = (
    "You restore personal details into a sentence that contains placeholders "
    "such as <PERSON_1>. The mapping gives each placeholder's original value "
    "in its base form. Replace every placeholder with its original value, put "
    "the value in the grammatical case and form the sentence requires (Russian "
    "declension), and keep every other word exactly as it is. Output only the "
    "restored sentence."
)


def build_restoration_request(
    sentence: str, entries: Mapping[str, str], temperature: float
) -> ChatRequest:
    mapping = json.dumps(dict(entries), ensure_ascii=False)
    return ChatRequest(
        prompt=f"Mapping: {mapping}\nSentence: {sentence}",
        audio_base64="",
        options=GenerationOptions(temperature=temperature, num_predict=NUM_PREDICT),
        system=RESTORE_RULES,
    )
