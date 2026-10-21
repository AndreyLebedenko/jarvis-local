"""The seam between the check stage and the chat backend."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from jarvis.core.config import GenerationOptions


class BackendReplyError(Exception):
    """The backend answered with an error instead of a reply. Carries no text."""


@dataclass(frozen=True)
class ChatRequest:
    prompt: str = field(repr=False)
    audio_base64: str = field(repr=False)
    options: GenerationOptions
    response_format: dict[str, Any] | None = None


class CheckBackend(Protocol):
    async def complete(self, request: ChatRequest) -> str:
        """The reply text. Any exception means the call failed."""
        ...
