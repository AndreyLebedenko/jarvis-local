#!/usr/bin/env python3
"""Manual handoff for task-spike-thinking-mode: Ollama thinking stream shape.

This is not an automated test. It talks to the live local Ollama endpoint
and the configured model, so the human runs it and reports the output.

Usage:
  python manual/manual_check_thinking_mode.py text
  python manual/manual_check_thinking_mode.py media
  python manual/manual_check_thinking_mode.py both
"""

import argparse
import asyncio
import base64
import json
import sys
import struct
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jarvis.core.config import BackendSettings, load_settings

ThinkingMode = Literal["off", "on"]
Variant = Literal["text", "media"]

THINKING_PARAM = "think"
TEXT_PROMPT = "Answer in one short sentence only: which is larger, 9.9 or 9.11?"
MEDIA_PROMPT = (
    "Look at the attached image and answer in one short sentence only: "
    "what two colors are visible?"
)


@dataclass(frozen=True)
class ProbeRequest:
    variant: Variant
    thinking_mode: ThinkingMode
    payload: dict[str, object]


@dataclass
class ProbeResult:
    variant: Variant
    thinking_mode: ThinkingMode
    wall_seconds: float
    chunk_count: int = 0
    content_chunks: int = 0
    thinking_chunks: int = 0
    content_text: str = ""
    thinking_text: str = ""
    chunk_shapes: list[str] = field(default_factory=list)
    done_chunk: dict[str, object] | None = None


def create_probe_png_b64() -> str:
    """Returns a tiny deterministic red/blue PNG, generated with stdlib only."""
    width = 64
    height = 64
    rows = []
    for _y in range(height):
        row = bytearray([0])  # PNG filter type 0
        for x in range(width):
            row.extend((255, 0, 0) if x < width // 2 else (0, 0, 255))
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
    settings: BackendSettings,
    variant: Variant,
    mode: ThinkingMode,
) -> ProbeRequest:
    message: dict[str, object] = {
        "role": "user",
        "content": MEDIA_PROMPT if variant == "media" else TEXT_PROMPT,
    }
    if variant == "media":
        message["images"] = [create_probe_png_b64()]

    payload: dict[str, object] = {
        "model": settings.model,
        "messages": [message],
        "stream": True,
        "options": {"num_ctx": settings.num_ctx},
        THINKING_PARAM: mode == "on",
    }
    return ProbeRequest(variant=variant, thinking_mode=mode, payload=payload)


def summarize_chunk_shape(chunk: dict[str, object]) -> str:
    message = chunk.get("message")
    message_keys = sorted(message.keys()) if isinstance(message, dict) else []
    top_keys = sorted(chunk.keys())
    return f"top={top_keys}; message={message_keys}"


def content_has_inline_reasoning(content: str) -> bool:
    lowered = content.lower()
    return "<think" in lowered or "</think" in lowered or "<thinking" in lowered


async def ollama_version(client: httpx.AsyncClient) -> str:
    try:
        response = await client.get("/api/version")
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return f"unavailable ({exc})"
    data = response.json()
    return str(data.get("version", "unknown"))


async def run_probe(client: httpx.AsyncClient, request: ProbeRequest) -> ProbeResult:
    result = ProbeResult(
        variant=request.variant,
        thinking_mode=request.thinking_mode,
        wall_seconds=0.0,
    )
    seen_shapes = set()
    t0 = time.perf_counter()
    async with client.stream("POST", "/api/chat", json=request.payload) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.strip():
                continue
            chunk = json.loads(line)
            result.chunk_count += 1
            shape = summarize_chunk_shape(chunk)
            if shape not in seen_shapes:
                seen_shapes.add(shape)
                result.chunk_shapes.append(shape)

            message = chunk.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                thinking = message.get("thinking")
                if isinstance(content, str) and content:
                    result.content_chunks += 1
                    result.content_text += content
                if isinstance(thinking, str) and thinking:
                    result.thinking_chunks += 1
                    result.thinking_text += thinking

            if chunk.get("done"):
                result.done_chunk = chunk
    result.wall_seconds = time.perf_counter() - t0
    return result


def print_request(request: ProbeRequest) -> None:
    payload = dict(request.payload)
    messages = payload.get("messages")
    if isinstance(messages, list) and messages:
        message = dict(messages[0])
        if "images" in message:
            images = message["images"]
            image_count = len(images) if isinstance(images, list) else 1
            message["images"] = [f"<base64 image omitted; count={image_count}>"]
        payload["messages"] = [message]
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def print_result(result: ProbeResult) -> None:
    print(f"\n=== {result.variant} / thinking {result.thinking_mode} ===")
    print(f"wall_seconds: {result.wall_seconds:.2f}")
    print(f"chunks: {result.chunk_count}")
    print(f"content_chunks: {result.content_chunks}")
    print(f"thinking_chunks: {result.thinking_chunks}")
    print("chunk_shapes:")
    for shape in result.chunk_shapes:
        print(f"  - {shape}")
    inline_reasoning = content_has_inline_reasoning(result.content_text)
    print(f"inline_reasoning_markers_in_content: {inline_reasoning}")
    print(f"content_preview: {result.content_text[:500]!r}")
    print(f"thinking_preview: {result.thinking_text[:500]!r}")
    if result.done_chunk is not None:
        done_summary = {
            key: result.done_chunk.get(key)
            for key in (
                "done",
                "done_reason",
                "load_duration",
                "prompt_eval_duration",
                "eval_duration",
                "eval_count",
            )
            if key in result.done_chunk
        }
        print(f"done_summary: {json.dumps(done_summary, ensure_ascii=False)}")


def variants_for(selection: str) -> list[Variant]:
    if selection == "text":
        return ["text"]
    if selection == "media":
        return ["media"]
    return ["text", "media"]


async def run(selection: str) -> None:
    settings = load_settings()
    timeout = httpx.Timeout(10.0, read=settings.backend.read_timeout_seconds)
    async with httpx.AsyncClient(
        base_url=settings.backend.endpoint,
        timeout=timeout,
    ) as client:
        print(f"Ollama endpoint: {settings.backend.endpoint}")
        print(f"Ollama version: {await ollama_version(client)}")
        print(f"Model: {settings.backend.model}")
        print(f"Thinking API parameter: {THINKING_PARAM}")

        for variant in variants_for(selection):
            for mode in ("off", "on"):
                request = build_probe_request(settings.backend, variant, mode)
                print(f"\n--- request: {variant} / thinking {mode} ---")
                print_request(request)
                result = await run_probe(client, request)
                print_result(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("variant", choices=["text", "media", "both"])
    args = parser.parse_args()
    asyncio.run(run(args.variant))
