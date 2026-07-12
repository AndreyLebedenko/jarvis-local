#!/usr/bin/env python3
"""Manual handoff for story-v1.2.8-task-4: live plain-text language routing.

Not an automated test. It talks to the live local Ollama endpoint and the
configured model, so the human runs it and records the output.

Usage:
  python -m manual.manual_check_speech_markup_contract
"""

import asyncio
import json
import time
from dataclasses import asdict, dataclass

import httpx

from jarvis.app import SYSTEM_PROMPT
from jarvis.audio.language_segments import LanguageSegment, segment_by_charset
from jarvis.core.config import BackendSettings, load_settings

SYSTEM_PROMPT_UNDER_TEST = SYSTEM_PROMPT


@dataclass(frozen=True)
class PromptCase:
    label: str
    prompt: str
    expected_note: str


@dataclass(frozen=True)
class PlainTextObservation:
    no_language_tags: bool
    no_markdown_fences: bool
    has_speakable_text: bool


PROMPTS = [
    PromptCase(
        label="russian_only",
        prompt=(
            "Ответь одним коротким абзацем по-русски: почему локальный "
            "голосовой ассистент должен отвечать кратко?"
        ),
        expected_note="Plain Russian prose should route as ru.",
    ),
    PromptCase(
        label="english_only",
        prompt=(
            "The next spoken answer must be in English. In one short paragraph, "
            "explain what a WebSocket is."
        ),
        expected_note="Plain English prose should route as en.",
    ),
    PromptCase(
        label="mixed_identifiers",
        prompt=(
            "По-русски объясни, что делает функция parse_user_id в классе "
            "APIClient, и упомяни JSONDecoder. Ответ короткий."
        ),
        expected_note="Russian prose should route as ru; Latin identifiers as en.",
    ),
    PromptCase(
        label="quotes_and_slashes",
        prompt=(
            "По-русски сравни варианты 'pull/push' и 'request/response', "
            "оставляя английские пары как английские цитаты."
        ),
        expected_note="Slash-separated Latin examples should route as en.",
    ),
    PromptCase(
        label="punctuation_heavy",
        prompt=(
            "Коротко объясни фразу HTTP/2, WebSocket, REST: когда что выбрать? "
            "Сохрани двоеточия, запятые и вопросительный знак."
        ),
        expected_note="Latin protocol names with punctuation should route as en.",
    ),
    PromptCase(
        label="long_nuanced_pressure",
        prompt=(
            "Дай более нюансированный, но всё ещё компактный ответ: как выбирать "
            "между latency, reliability, observability, developer experience "
            "и cost в локальном ассистенте? Упомяни trade-off и failure mode."
        ),
        expected_note="Mixed plain text should segment deterministically.",
    ),
]


def generation_options(settings: BackendSettings) -> dict[str, object]:
    return {
        "num_ctx": settings.num_ctx,
        "flash_attention": settings.flash_attention,
        "kv_cache_type": settings.kv_cache_type,
        "temperature": settings.temperature,
        "top_p": settings.top_p,
        "top_k": settings.top_k,
        "min_p": settings.min_p,
        "repeat_penalty": settings.repeat_penalty,
        "repeat_last_n": settings.repeat_last_n,
        "seed": settings.seed,
        "num_predict": settings.num_predict,
        "stop": settings.stop,
        "draft_num_predict": settings.draft_num_predict,
    }


def build_payload(settings: BackendSettings, prompt: str) -> dict[str, object]:
    options = {
        key: value
        for key, value in generation_options(settings).items()
        if value is not None
    }
    return {
        "model": settings.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_UNDER_TEST},
            {"role": "user", "content": prompt},
        ],
        "stream": True,
        "think": False,
        "options": options,
    }


def observe_plain_text(text: str) -> PlainTextObservation:
    return PlainTextObservation(
        no_language_tags="<speak" not in text.lower() and "<lang" not in text.lower(),
        no_markdown_fences="```" not in text,
        has_speakable_text=bool(text.strip()),
    )


def segment_text(text: str) -> list[LanguageSegment]:
    return segment_by_charset(text)


async def ollama_version(client: httpx.AsyncClient) -> str:
    try:
        response = await client.get("/api/version")
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return f"unavailable ({exc})"
    data = response.json()
    return str(data.get("version", "unknown"))


async def run_case(
    client: httpx.AsyncClient, settings: BackendSettings, case: PromptCase
) -> str:
    payload = build_payload(settings, case.prompt)
    text = ""
    start = time.perf_counter()
    async with client.stream("POST", "/api/chat", json=payload) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.strip():
                continue
            chunk = json.loads(line)
            message = chunk.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    text += content
    elapsed = time.perf_counter() - start
    print(f"\n=== {case.label} ({elapsed:.2f}s) ===")
    print(f"Prompt: {case.prompt}")
    print(f"Expected: {case.expected_note}")
    print("\nRaw response:")
    print(text)
    print("\nObservations:")
    for key, value in asdict(observe_plain_text(text)).items():
        print(f"  {key}: {value}")
    print("\nCharset language segments:")
    for segment in segment_text(text):
        print(f"  [{segment.language}] {segment.text}")
    return text


async def main() -> None:
    settings = load_settings()
    timeout = httpx.Timeout(10.0, read=settings.backend.read_timeout_seconds)
    async with httpx.AsyncClient(
        base_url=settings.backend.endpoint,
        timeout=timeout,
    ) as client:
        print(f"Ollama endpoint: {settings.backend.endpoint}")
        print(f"Ollama version: {await ollama_version(client)}")
        print(f"Model: {settings.backend.model}")
        print("Thinking: false")
        print("Generation options:")
        for key, value in generation_options(settings.backend).items():
            print(f"  {key}: {value}")
        print("\nSystem prompt under test:")
        print(SYSTEM_PROMPT_UNDER_TEST)

        for case in PROMPTS:
            await run_case(client, settings.backend, case)

    print("\nRecord pass/fail in the task card and PROJECT.md:")
    print("  - model emits plain speakable text, not language tags")
    print("  - no Markdown fences unless explicitly requested")
    print("  - charset segmentation routes Cyrillic text as ru")
    print("  - charset segmentation routes Latin identifiers/terms as en")
    print("  - punctuation and numbers attach to usable neighboring segments")


if __name__ == "__main__":
    asyncio.run(main())
