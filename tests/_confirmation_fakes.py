"""Fakes for the ports of the confirmation exchange, with one shared call log."""

from __future__ import annotations

import asyncio
from collections import defaultdict

from jarvis.personal_proxy.confirmation_ports import SpeechResult


class FakeSink:
    def __init__(self, log, *, fail=False, hold=None):
        self.log = log
        self.fail = fail
        self.hold = hold
        self.blocks = []

    async def post(self, block):
        self.log.append("post")
        self.blocks.append(block)
        if self.hold is not None:
            await self.hold.wait()
        if self.fail:
            raise RuntimeError("sink broke")


class FakeSpeaker:
    """Speaks until `release` is set; `stop()` releases it, like a real player."""

    def __init__(
        self,
        log,
        *,
        result=SpeechResult.SPOKEN,
        error=None,
        hold=False,
        ignore_stop=False,
    ):
        self.log = log
        self.ignore_stop = ignore_stop
        self.result = result
        self.error = error
        self.release = asyncio.Event()
        if not hold:
            self.release.set()
        self.spoken = []

    async def speak(self, text, language):
        self.log.append("speak")
        self.spoken.append((text, language))
        await self.release.wait()
        if self.error is not None:
            raise self.error
        return self.result

    def stop(self):
        self.log.append("stop")
        if not self.ignore_stop:
            self.release.set()


class FakeMicrophone:
    def __init__(
        self,
        log,
        *,
        pause_error=None,
        resume_error=None,
        resume_hold=None,
        pause_hold=None,
    ):
        self.log = log
        self.pause_hold = pause_hold
        self.pause_error = pause_error
        self.resume_error = resume_error
        self.resume_hold = resume_hold

    async def pause(self):
        self.log.append("pause")
        if self.pause_hold is not None:
            await self.pause_hold.wait()
        if self.pause_error is not None:
            raise self.pause_error

    async def resume(self):
        self.log.append("resume")
        if self.resume_hold is not None:
            await self.resume_hold.wait()
        if self.resume_error is not None:
            raise self.resume_error


class FakeTranscriber:
    def __init__(self, text="да", error=None, hang=False):
        self.text = text
        self.error = error
        self.hang = hang
        self.received = []
        self.cancelled = False

    async def transcribe(self, utterance):
        self.received.append(utterance)
        if self.hang:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        if self.error is not None:
            raise self.error
        return self.text


class ManualSleep:
    """The timeout seam: every sleep of a given length ends only when the test
    releases that length."""

    def __init__(self):
        self.requested = []
        self.events = defaultdict(asyncio.Event)

    async def __call__(self, seconds):
        self.requested.append(seconds)
        await self.events[seconds].wait()

    def release(self, seconds):
        self.events[seconds].set()
