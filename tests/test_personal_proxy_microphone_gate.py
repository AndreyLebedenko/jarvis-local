import asyncio

import pytest

from jarvis.personal_proxy.microphone_gate import AudioMicrophoneGate


class _FakeAudioInput:
    def __init__(self, log):
        self._log = log

    async def auto_pause_for_speech(self):
        self._log.append("paused")

    async def auto_resume_after_speech(self):
        self._log.append("resumed")


def _gate(log, cooldown=1.5):
    async def sleep(seconds):
        log.append(("sleep", seconds))

    return AudioMicrophoneGate(_FakeAudioInput(log), cooldown, sleep)


async def test_pause_pauses_the_capture_loop_at_once():
    log = []

    await _gate(log).pause()

    assert log == ["paused"]


async def test_resume_waits_the_cooldown_before_giving_the_microphone_back():
    log = []

    await _gate(log, cooldown=1.5).resume()

    assert log == [("sleep", 1.5), "resumed"]


async def test_a_resume_cancelled_during_the_cooldown_still_gives_the_microphone_back():
    log = []
    release = asyncio.Event()

    async def hanging_sleep(seconds):
        await release.wait()

    gate = AudioMicrophoneGate(_FakeAudioInput(log), 1.0, hanging_sleep)
    task = asyncio.ensure_future(gate.resume())
    await asyncio.sleep(0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert log == ["resumed"]
