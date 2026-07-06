"""Ollama backend adapter.

Streams `/api/chat`, attaches media (audio and/or screenshot bytes alike)
via the `images` field, and publishes tokens plus latency metrics to the
bus as they arrive. Kept thin (one class, one obvious seam - the injected
httpx client) so the backend can be swapped later with one config change,
per PROJECT.md's Architecture v1.0 section.

Verified fact (PROJECT.md, day0_checks.py): Ollama silently drops a
dedicated `audio` field. Audio and images both go through `images`. This
is codified as a regression test, not a style preference.

build_payload() attaches new media only to the last message and passes
every other message through unchanged - it does not decide what history
policy callers use. Whether media on a non-final message is actually used
by the model (rather than ignored, or erroring) has never been verified
against live Ollama: day-0 only covers single-turn media. See PROJECT.md's
"Open questions" section; this is task-07's decision to make, not this
module's.

Verified live (task-07 manual handoff): httpx's default timeout (~5 s
total) is too short for a true cold Ollama start - PROJECT.md's "load
~0.3 s warm" / "4.2 s cold" day-0 numbers were themselves measured on an
already-touched model; a genuinely cold start (fresh boot, first request
ever) took longer than 5 s and hit httpx.ReadTimeout. settings.
read_timeout_seconds (default 120 s) gives real headroom; connect/write/
pool stay short since this is all localhost traffic.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from bus import EventBus
from config import BackendSettings


@dataclass(frozen=True)
class ResponseToken:
    text: str


@dataclass(frozen=True)
class LatencyMetrics:
    load_seconds: float
    prompt_eval_seconds: float
    eval_seconds: float
    eval_count: int


@dataclass(frozen=True)
class ResponseComplete:
    metrics: LatencyMetrics


class OllamaBackend:
    def __init__(
        self,
        bus: EventBus,
        settings: BackendSettings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._bus = bus
        self._settings = settings
        self._client = client or httpx.AsyncClient(
            base_url=settings.endpoint,
            timeout=httpx.Timeout(10.0, read=settings.read_timeout_seconds),
        )

    def build_payload(
        self,
        messages: Sequence[dict[str, Any]],
        images_b64: Sequence[str] | None = None,
        thinking_enabled: bool = False,
    ) -> dict[str, Any]:
        messages = [dict(message) for message in messages]
        if images_b64:
            messages[-1] = {**messages[-1], "images": list(images_b64)}
        return {
            "model": self._settings.model,
            "messages": messages,
            "stream": True,
            "think": thinking_enabled,
            "options": {"num_ctx": self._settings.num_ctx},
        }

    async def chat(
        self,
        messages: Sequence[dict[str, Any]],
        images_b64: Sequence[str] | None = None,
        thinking_enabled: bool = False,
    ) -> None:
        payload = self.build_payload(messages, images_b64, thinking_enabled)
        async with self._client.stream("POST", "/api/chat", json=payload) as response:
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                chunk = json.loads(line)
                # message.thinking (reasoning trace, present when think=true) is
                # deliberately never read here - PROJECT.md's isolation rule
                # requires it stay out of ResponseToken/TTS. Only message.content
                # is republished.
                content = chunk.get("message", {}).get("content", "")
                if content:
                    await self._bus.publish(ResponseToken, ResponseToken(text=content))
                if chunk.get("done"):
                    await self._bus.publish(
                        ResponseComplete,
                        ResponseComplete(metrics=_parse_metrics(chunk)),
                    )


def _parse_metrics(chunk: dict[str, Any]) -> LatencyMetrics:
    return LatencyMetrics(
        load_seconds=chunk.get("load_duration", 0) / 1e9,
        prompt_eval_seconds=chunk.get("prompt_eval_duration", 0) / 1e9,
        eval_seconds=chunk.get("eval_duration", 0) / 1e9,
        eval_count=chunk.get("eval_count", 0),
    )
