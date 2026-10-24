"""The microphone gate of the proxy over the capture loop's automatic pause.

The pause is the loop's own `auto_pause_for_speech`, which is independent of
the user's sleep toggle: a resume never wakes a microphone the user put to
sleep. The resume waits out the same cooldown the dialog path uses, so the tail
of the speaker is not heard as a new utterance."""

from __future__ import annotations

import asyncio
from typing import Protocol

from jarvis.personal_proxy.confirmation.confirmation_ports import Sleep


class AutoPausable(Protocol):
    async def auto_pause_for_speech(self) -> None: ...

    async def auto_resume_after_speech(self) -> None: ...


class AudioMicrophoneGate:
    def __init__(
        self,
        audio_input: AutoPausable,
        cooldown_seconds: float,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._audio_input = audio_input
        self._cooldown_seconds = cooldown_seconds
        self._sleep = sleep

    async def pause(self) -> None:
        await self._audio_input.auto_pause_for_speech()

    async def resume(self) -> None:
        try:
            await self._sleep(self._cooldown_seconds)
        finally:
            await self._audio_input.auto_resume_after_speech()
