"""Builds the two requests of the check: the corrected sample and the judge."""

from __future__ import annotations

from jarvis.core.config import GenerationOptions
from jarvis.personal_proxy.check_backend import ChatRequest
from jarvis.personal_proxy.check_prompts import (
    JUDGE_SCHEMA,
    judge_prompt,
    sample_prompt,
)

NUM_PREDICT = 2048
JUDGE_TEMPERATURE = 0.0
JUDGE_SEED = 1


def build_sample_request(
    marked_transcript: str, audio_base64: str, temperature: float
) -> ChatRequest:
    return ChatRequest(
        prompt=sample_prompt(marked_transcript),
        audio_base64=audio_base64,
        options=GenerationOptions(temperature=temperature, num_predict=NUM_PREDICT),
    )


def build_judge_request(
    whisper_text: str, candidate_text: str, audio_base64: str
) -> ChatRequest:
    return ChatRequest(
        prompt=judge_prompt(whisper_text, candidate_text),
        audio_base64=audio_base64,
        options=GenerationOptions(
            temperature=JUDGE_TEMPERATURE, seed=JUDGE_SEED, num_predict=NUM_PREDICT
        ),
        response_format=JUDGE_SCHEMA,
    )
