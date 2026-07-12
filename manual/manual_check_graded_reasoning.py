#!/usr/bin/env python3
"""Manual handoff for story-v1.3.1 task 1: graded Ollama reasoning spike.

Verifies the four product `think` request values (`false`, `"low"`,
`"medium"`, `"high"`) against the configured local Ollama endpoint and
model, across three prompt categories. This is not an automated test: it
talks to the live local Ollama endpoint, so the human runs it and reports
the output. Makes no runtime or UI changes - see
tasks/story-v1.3.1-task-1-graded-reasoning-spike.md.

Usage:
  python -m manual.manual_check_graded_reasoning
"""

import asyncio
import base64
import json
import struct
import time
import zlib
from dataclasses import dataclass
from typing import Literal

import httpx

from jarvis.core.bus import EventBus
from jarvis.core.config import load_settings
from jarvis.dialog.backend import OllamaBackend

Level = Literal["off", "low", "medium", "high"]
Category = Literal["calculation", "multi_step", "image"]

LEVELS: tuple[Level, ...] = ("off", "low", "medium", "high")
TEXT_CATEGORIES: tuple[Category, ...] = ("calculation", "multi_step")
TEXT_RUNS_PER_LEVEL = 3

THINK_VALUES: dict[Level, bool | str] = {
    "off": False,
    "low": "low",
    "medium": "medium",
    "high": "high",
}

PROMPTS: dict[Category, str] = {
    "calculation": (
        "Answer with only the final integer, no explanation: what is 47 * 63 - 129?"
    ),
    "multi_step": (
        "A train leaves station A at 60 km/h. Two hours later a second "
        "train leaves the same station on the same track at 90 km/h, "
        "chasing the first. Answer with only the final number of hours "
        "after the second train's departure until it catches the first, "
        "no explanation."
    ),
    "image": (
        "Look at the attached image and answer in one short sentence "
        "only: how many distinct colored quadrants are visible and what "
        "are their colors?"
    ),
}


@dataclass(frozen=True)
class ProbeRequest:
    category: Category
    level: Level
    run_index: int
    payload: dict[str, object]


@dataclass
class ProbeResult:
    category: Category
    level: Level
    run_index: int
    wall_seconds: float = 0.0
    success: bool = False
    error: str | None = None
    eval_count: int | None = None
    thinking_char_count: int = 0
    content_text: str = ""
    thinking_text: str = ""
    reasoning_leaked_into_content: bool = False
    done_chunk: dict[str, object] | None = None


def create_probe_png_b64() -> str:
    """Returns a tiny deterministic four-color (2x2 quadrant) PNG, stdlib
    only - richer than a two-color split so the image prompt's "how many
    colors" answer is not a one-glance guess."""
    width = 64
    height = 64
    colors = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0))
    rows = []
    for y in range(height):
        row = bytearray([0])  # PNG filter type 0
        top = y < height // 2
        for x in range(width):
            left = x < width // 2
            index = (0 if top else 2) + (0 if left else 1)
            row.extend(colors[index])
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    png = b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            chunk(b"IDAT", zlib.compress(raw)),
            chunk(b"IEND", b""),
        ]
    )
    return base64.b64encode(png).decode()


def build_probe_request(
    backend: OllamaBackend,
    category: Category,
    level: Level,
    run_index: int,
) -> ProbeRequest:
    """Reuses OllamaBackend.build_payload() for model/messages/options so
    the spike sends the exact same shape production turns send, then
    overrides "think" with the graded value under test - build_payload()
    itself only accepts a bool, since typing it to the graded value is
    task 2's job, not this spike's."""
    message: dict[str, object] = {"role": "user", "content": PROMPTS[category]}
    images = [create_probe_png_b64()] if category == "image" else None
    payload = backend.build_payload([message], images, thinking_enabled=False)
    payload["think"] = THINK_VALUES[level]
    return ProbeRequest(
        category=category, level=level, run_index=run_index, payload=payload
    )


def content_has_inline_reasoning(content: str) -> bool:
    lowered = content.lower()
    return "<think" in lowered or "</think" in lowered or "<thinking" in lowered


def classify_chunks(
    category: Category,
    level: Level,
    run_index: int,
    chunks: list[dict[str, object]],
    wall_seconds: float,
    error: str | None = None,
) -> ProbeResult:
    """Pure classification of an already-received chunk list into a
    ProbeResult. Kept separate from run_probe()'s network I/O so this half
    is unit-testable without contacting Ollama."""
    result = ProbeResult(
        category=category,
        level=level,
        run_index=run_index,
        wall_seconds=wall_seconds,
        error=error,
    )
    saw_done = False
    for chunk in chunks:
        message = chunk.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            thinking = message.get("thinking")
            if isinstance(content, str) and content:
                result.content_text += content
            if isinstance(thinking, str) and thinking:
                result.thinking_text += thinking
        if chunk.get("done"):
            saw_done = True
            result.done_chunk = chunk
            result.eval_count = chunk.get("eval_count")
    result.success = saw_done and error is None
    result.thinking_char_count = len(result.thinking_text)
    result.reasoning_leaked_into_content = content_has_inline_reasoning(
        result.content_text
    )
    return result


async def ollama_version(client: httpx.AsyncClient) -> str:
    try:
        response = await client.get("/api/version")
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return f"unavailable ({exc})"
    return str(response.json().get("version", "unknown"))


async def run_probe(client: httpx.AsyncClient, request: ProbeRequest) -> ProbeResult:
    chunks: list[dict[str, object]] = []
    error: str | None = None
    t0 = time.perf_counter()
    try:
        async with client.stream("POST", "/api/chat", json=request.payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                chunks.append(json.loads(line))
    except httpx.HTTPError as exc:
        error = str(exc)
    wall_seconds = time.perf_counter() - t0
    return classify_chunks(
        request.category, request.level, request.run_index, chunks, wall_seconds, error
    )


def print_request(request: ProbeRequest) -> None:
    payload = dict(request.payload)
    messages = payload.get("messages")
    if isinstance(messages, list) and messages:
        message = dict(messages[0])
        if "images" in message:
            images = message["images"]
            count = len(images) if isinstance(images, list) else 1
            message["images"] = [f"<base64 image omitted; count={count}>"]
        payload["messages"] = [message]
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def print_result(result: ProbeResult) -> None:
    header = f"{result.category} / think={result.level!r} / run {result.run_index}"
    print(f"\n=== {header} ===")
    print(f"wall_seconds: {result.wall_seconds:.2f}")
    print(f"success: {result.success}")
    if result.error:
        print(f"error: {result.error}")
    print(f"eval_count: {result.eval_count}")
    print(f"thinking_char_count: {result.thinking_char_count}")
    print(f"reasoning_leaked_into_content: {result.reasoning_leaked_into_content}")
    print(f"content: {result.content_text!r}")
    print(f"thinking_preview: {result.thinking_text[:300]!r}")


async def run() -> None:
    settings = load_settings()
    timeout = httpx.Timeout(10.0, read=settings.backend.read_timeout_seconds)
    async with httpx.AsyncClient(
        base_url=settings.backend.endpoint, timeout=timeout
    ) as client:
        backend = OllamaBackend(EventBus(), settings.backend, client=client)
        print(f"Ollama endpoint: {settings.backend.endpoint}")
        print(f"Ollama version: {await ollama_version(client)}")
        print(f"Model: {settings.backend.model}")

        for level in LEVELS:
            for category in TEXT_CATEGORIES:
                for run_index in range(1, TEXT_RUNS_PER_LEVEL + 1):
                    request = build_probe_request(backend, category, level, run_index)
                    print(
                        f"\n--- request: {request.category} / "
                        f"think={request.level!r} / run {run_index} ---"
                    )
                    print_request(request)
                    print_result(await run_probe(client, request))

            image_request = build_probe_request(backend, "image", level, 1)
            print(f"\n--- request: image / think={level!r} / run 1 ---")
            print_request(image_request)
            print_result(await run_probe(client, image_request))


if __name__ == "__main__":
    asyncio.run(run())
