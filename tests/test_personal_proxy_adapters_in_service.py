"""The real microphone gate and speaker adapters inside the real service, over
fake stages: the microphone must be given back on every path."""

import asyncio

import pytest
from _service_fakes import Rig, closed, make_wav, settled, until, within

from jarvis.audio.replay import ReplayOutcome, ReplayRun
from jarvis.personal_proxy.answer_speaker import ReplayAnswerSpeaker
from jarvis.personal_proxy.microphone_gate import AudioMicrophoneGate
from jarvis.personal_proxy.proxy_inbox import Utterance
from jarvis.personal_proxy.service_blocks import AnswerBlock, NoticeKind


class _Audio:
    def __init__(self):
        self.calls = []

    async def auto_pause_for_speech(self):
        self.calls.append("pause")

    async def auto_resume_after_speech(self):
        self.calls.append("resume")

    @property
    def paused(self):
        return self.calls.count("pause") > self.calls.count("resume")


class _Player:
    """Every run holds until released or cancelled, like real playback."""

    def __init__(self, *, mute=False, fail=False):
        self.mute = mute
        self.fail = fail
        self.release = asyncio.Event()
        self.runs = []
        self.task = None

    def start_run(self, items):
        if self.mute:
            return ReplayOutcome.DISABLED
        self.runs.append(items)
        self.task = asyncio.ensure_future(self._play())
        return ReplayRun(self.task, self)

    async def _play(self):
        if self.fail:
            raise RuntimeError("synthesis failed")
        await self.release.wait()

    async def wait_for_pending(self):
        if self.task is not None:
            await asyncio.wait({self.task})

    def cancel(self):
        if self.task is not None and not self.task.done():
            self.task.cancel()
            return True
        return False

    def _cancel_run(self, task):
        if task.done():
            return False
        task.cancel()
        return True


async def _instant(seconds):
    return None


def _rig(player, audio, **kwargs):
    return Rig(
        speaker=ReplayAnswerSpeaker(player),
        microphone=AudioMicrophoneGate(audio, 1.0, _instant),
        **kwargs,
    )


async def _request(rig):
    rig.service.start()
    rig.service.submit(Utterance(make_wav()))


async def test_the_microphone_is_paused_around_the_answer_and_given_back():
    player, audio = _Player(), _Audio()
    player.release.set()
    rig = _rig(player, audio)

    await _request(rig)
    await within(settled(rig))
    await closed(rig.service)

    assert rig.sink.of(AnswerBlock)
    assert audio.calls.count("pause") == 1
    assert not audio.paused


async def test_a_synthesis_failure_degrades_to_text_and_gives_the_microphone_back():
    player, audio = _Player(fail=True), _Audio()
    rig = _rig(player, audio)

    await _request(rig)
    await within(settled(rig))
    await closed(rig.service)

    assert rig.sink.of(AnswerBlock)
    assert NoticeKind.SPEECH_FAILED in rig.sink.notices()
    assert not audio.paused


async def test_a_muted_speech_switch_shows_text_only_and_gives_the_microphone_back():
    player, audio = _Player(mute=True), _Audio()
    rig = _rig(player, audio)

    await _request(rig)
    await within(settled(rig))
    await closed(rig.service)

    assert rig.sink.of(AnswerBlock)
    assert player.runs == []
    assert not audio.paused


async def test_an_interrupt_while_speaking_stops_the_run_and_returns_the_microphone():
    player, audio = _Player(), _Audio()
    rig = _rig(player, audio)

    await _request(rig)
    await until(lambda: player.task is not None and "pause" in audio.calls)
    rig.service.interrupt()
    player.cancel()
    await within(settled(rig))
    await closed(rig.service)

    assert NoticeKind.INTERRUPTED in rig.sink.notices()
    assert not audio.paused


async def test_closing_during_speech_gives_the_microphone_back():
    player, audio = _Player(), _Audio()
    rig = _rig(player, audio)

    await _request(rig)
    await until(lambda: player.task is not None and "pause" in audio.calls)
    await closed(rig.service)

    assert not audio.paused


async def test_a_failing_stage_after_speech_started_still_balances_the_microphone():
    player, audio = _Player(), _Audio()
    player.release.set()
    rig = _rig(player, audio)
    rig.stages.stream_error = RuntimeError("external failure")

    await _request(rig)
    await within(settled(rig))
    await closed(rig.service)

    assert NoticeKind.ANSWER_INCOMPLETE in rig.sink.notices()
    assert not audio.paused


@pytest.mark.parametrize("doubt_answer", ["yes", "no"])
async def test_a_question_pauses_and_resumes_once_per_speech(doubt_answer):
    from _service_fakes import CHECKED_WITH_DOUBT

    player, audio = _Player(), _Audio()
    player.release.set()
    rig = _rig(player, audio)
    rig.stages.checked = CHECKED_WITH_DOUBT

    await _request(rig)
    await until(
        lambda: rig.stages.calls["sanitize"] and audio.calls.count("resume") >= 1
    )
    await until(lambda: not audio.paused)
    from jarvis.personal_proxy.proxy_inbox import TypedText

    rig.service.submit(TypedText("да" if doubt_answer == "yes" else "нет"))
    await within(settled(rig))
    await closed(rig.service)

    assert audio.calls.count("pause") == audio.calls.count("resume")
    assert not audio.paused
