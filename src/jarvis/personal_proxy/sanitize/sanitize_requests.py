"""Builds the sanitize request: text only, constrained to the sanitize schema."""

from __future__ import annotations

from jarvis.core.config import GenerationOptions
from jarvis.personal_proxy.check.check_backend import ChatRequest
from jarvis.personal_proxy.sanitize.sanitize_prompts import (
    TEXT_SCHEMA,
    sanitize_system_prompt,
    sanitize_user_prompt,
)

NUM_PREDICT = 2048


def build_sanitize_request(
    transcript: str, topics: str, temperature: float
) -> ChatRequest:
    return ChatRequest(
        prompt=sanitize_user_prompt(transcript),
        audio_base64="",
        options=GenerationOptions(temperature=temperature, num_predict=NUM_PREDICT),
        response_format=TEXT_SCHEMA,
        system=sanitize_system_prompt(topics),
    )
