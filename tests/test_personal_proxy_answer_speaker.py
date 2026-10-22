import asyncio

import pytest

from jarvis.audio.replay import ReplayOutcome, ReplayRun, TextReply
from jarvis.personal_proxy.answer_speaker import ReplayAnswerSpeaker
from jarvis.personal_proxy.confirmation_ports import SpeechResult


class _FakePlayer:
    """Answers start_run from a script; a run is a real task so that
    ReplayRun.wait behaves as in production."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.started = []
        self.cancelled = 0
        self.other_run_ended = asyncio.Event()
        self.waits = 0

    def start_run(self, items):
        self.started.append(items)
        outcome = self.outcomes.pop(0)
        if outcome == "run":
            return ReplayRun(asyncio.ensure_future(asyncio.sleep(0)), self)
        return outcome

    async def wait_for_pending(self):
        self.waits += 1
        await self.other_run_ended.wait()

    def cancel(self):
        self.cancelled += 1
        return True

    def _cancel_run(self, task):
        return False


async def test_a_sentence_is_one_run_of_exactly_its_text():
    player = _FakePlayer(["run"])

    result = await ReplayAnswerSpeaker(player).speak("Готово.", "ru")

    assert result is SpeechResult.SPOKEN
    assert player.started == [[TextReply("Готово.")]]


async def test_a_muted_player_reports_disabled_without_waiting():
    player = _FakePlayer([ReplayOutcome.DISABLED])

    result = await ReplayAnswerSpeaker(player).speak("Готово.", None)

    assert result is SpeechResult.DISABLED


async def test_text_with_nothing_speakable_is_not_an_error():
    player = _FakePlayer([ReplayOutcome.EMPTY])

    assert await ReplayAnswerSpeaker(player).speak("...", None) is SpeechResult.SPOKEN


async def test_a_busy_player_is_waited_for_and_the_sentence_is_then_spoken():
    player = _FakePlayer([ReplayOutcome.BUSY, "run"])
    speaking = asyncio.ensure_future(ReplayAnswerSpeaker(player).speak("Готово.", None))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert len(player.started) == 1 and not speaking.done()

    player.other_run_ended.set()
    result = await asyncio.wait_for(speaking, 1)

    assert result is SpeechResult.SPOKEN
    assert len(player.started) == 2


async def test_cancelling_while_waiting_for_another_run_leaves_that_run_alone():
    player = _FakePlayer([ReplayOutcome.BUSY])
    speaking = asyncio.ensure_future(ReplayAnswerSpeaker(player).speak("Готово.", None))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    speaking.cancel()
    with pytest.raises(asyncio.CancelledError):
        await speaking

    assert player.cancelled == 0


async def test_a_failed_run_raises_so_that_the_service_degrades_to_text():
    class _Failing(_FakePlayer):
        def start_run(self, items):
            async def fail():
                raise RuntimeError("synthesis failed")

            return ReplayRun(asyncio.ensure_future(fail()), self)

    with pytest.raises(RuntimeError):
        await ReplayAnswerSpeaker(_Failing([])).speak("Готово.", None)


def test_stop_cancels_the_players_run():
    player = _FakePlayer([])

    ReplayAnswerSpeaker(player).stop()

    assert player.cancelled == 1
