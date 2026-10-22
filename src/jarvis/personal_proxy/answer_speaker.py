"""The speaker of the proxy over the shared `ReplayPlayer`.

The player runs one thing at a time and answers BUSY while another run plays;
the port has no BUSY, so this waits for the other run to end. Each call is its
own run, so the speech layer parses every sentence on its own."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Protocol

from jarvis.audio.replay import PlayItem, ReplayOutcome, ReplayRun, TextReply
from jarvis.personal_proxy.confirmation_ports import SpeechResult


class SpeechPlayer(Protocol):
    def start_run(self, items: list[PlayItem]) -> ReplayRun | ReplayOutcome: ...

    async def wait_for_pending(self) -> None: ...

    def cancel(self) -> bool: ...


def _consume(task: asyncio.Future[None]) -> None:
    if not task.cancelled():
        task.exception()


class ReplayAnswerSpeaker:
    def __init__(self, player: SpeechPlayer) -> None:
        self._player = player

    async def speak(self, text: str, language: str | None) -> SpeechResult:
        del language
        started = await self._start(TextReply(text))
        if started is ReplayOutcome.DISABLED:
            return SpeechResult.DISABLED
        if isinstance(started, ReplayRun):
            await started.wait()
        return SpeechResult.SPOKEN

    def stop(self) -> None:
        self._player.cancel()

    async def _start(self, reply: TextReply) -> ReplayRun | ReplayOutcome:
        while True:
            started = self._player.start_run([reply])
            if started is not ReplayOutcome.BUSY:
                return started
            await self._other_run_ended()

    async def _other_run_ended(self) -> None:
        # Awaiting the player's own task would let our cancellation cancel a run
        # we do not own; the shield keeps it alive.
        pending = asyncio.ensure_future(self._player.wait_for_pending())
        pending.add_done_callback(_consume)
        with suppress(Exception):
            await asyncio.shield(pending)
