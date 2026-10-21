"""The check stage's chat backend on the project's Ollama backend.

The streaming, the media path (`images`), the load options, and the debug
transcript are the existing `OllamaBackend`; this adds the model and context
the check uses, and the JSON-constrained output the judge needs."""

from __future__ import annotations

from contextlib import aclosing
from dataclasses import replace
from typing import Any

import httpx

from jarvis.core.bus import EventBus
from jarvis.core.config import (
    BackendSettings,
    GenerationOptions,
    PersonalProxySettings,
)
from jarvis.dialog.backend import OllamaBackend
from jarvis.personal_proxy.check_backend import BackendReplyError, ChatRequest


class _ConstrainedOllamaBackend(OllamaBackend):
    def __init__(
        self,
        settings: BackendSettings,
        client: httpx.AsyncClient,
        response_format: dict[str, Any] | None,
    ) -> None:
        super().__init__(EventBus(), settings, client)
        self._response_format = response_format

    def build_payload(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        payload = super().build_payload(*args, **kwargs)
        if self._response_format is not None:
            payload["format"] = self._response_format
        return payload


_LENGTH_CAP = "length"


class OllamaCheckBackend:
    """The check's sampling is `[personal_proxy].check_top_p` and its siblings,
    never the dialog's [generation] table; the request keeps its own
    temperature, seed, and length cap."""

    def __init__(
        self,
        backend_settings: BackendSettings,
        proxy_settings: PersonalProxySettings,
        client: httpx.AsyncClient,
    ) -> None:
        self._settings = replace(
            backend_settings,
            model=proxy_settings.check_model,
            num_ctx=proxy_settings.check_num_ctx,
        )
        self._client = client
        self._sampling = GenerationOptions(
            top_p=proxy_settings.check_top_p,
            top_k=proxy_settings.check_top_k,
            min_p=proxy_settings.check_min_p,
            repeat_penalty=proxy_settings.check_repeat_penalty,
        )

    async def complete(self, request: ChatRequest) -> str:
        backend = _ConstrainedOllamaBackend(
            self._settings, self._client, request.response_format
        )
        parts: list[str] = []
        finished = False
        stream = backend.iter_chat(
            [{"role": "user", "content": request.prompt}],
            [request.audio_base64],
            options=self._sampling.overridden_by(request.options),
        )
        try:
            async with aclosing(stream):
                async for chunk in stream:
                    if "error" in chunk:
                        raise BackendReplyError
                    parts.append(chunk.get("message", {}).get("content", ""))
                    if chunk.get("done"):
                        finished = chunk.get("done_reason") != _LENGTH_CAP
        except ValueError:
            # from None: the decoder's message quotes the body it could not read.
            raise BackendReplyError from None
        if not finished:
            raise BackendReplyError
        return "".join(parts)
