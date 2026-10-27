"""The spoken version of a restored answer, rendered by the local model with
the project's `text_voice` contract: a retelling of the form, no new facts. The
answer is the user message and the contract is the system message, so the answer
text cannot steer the pass."""

from __future__ import annotations

import asyncio

from jarvis.core.config import GenerationOptions
from jarvis.dialog.canvas_speech import compose_canvas_speech_messages
from jarvis.personal_proxy.check.check_backend import ChatRequest, CheckBackend


class SpokenDerivativeRenderer:
    def __init__(
        self,
        backend: CheckBackend,
        contract: str,
        options: GenerationOptions,
        timeout_seconds: float,
    ) -> None:
        self._backend = backend
        self._contract = contract
        self._options = options
        self._timeout = timeout_seconds

    async def render(self, canvas: str) -> str:
        """The spoken text, or an exception: a failed backend call, a reply cut
        by its length cap, or the timeout."""
        system = str(
            compose_canvas_speech_messages(self._contract, None, canvas)[0]["content"]
        )
        async with asyncio.timeout(self._timeout):
            return await self._backend.complete(
                ChatRequest(
                    prompt=canvas,
                    audio_base64="",
                    options=self._options,
                    system=system,
                )
            )
