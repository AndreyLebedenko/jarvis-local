import asyncio

import pytest
from _confirmation_fakes import (
    FakeMicrophone,
    FakeSink,
    FakeSpeaker,
    FakeTranscriber,
    ManualSleep,
)

from jarvis.personal_proxy.check_result import (
    CheckedTranscript,
    CheckSource,
    Doubt,
    DoubtKind,
)
from jarvis.personal_proxy.confirmation_blocks import HeardBlock, HeardDecision
from jarvis.personal_proxy.confirmation_exchange import (
    SPEECH_PHASE_TIMEOUT_SECONDS,
    ConfirmationExchange,
    ExchangeBusyError,
    WrongLoopError,
)
from jarvis.personal_proxy.confirmation_outcome import (
    Delivery,
    ExchangeOutcome,
    ExchangeState,
    FailureStage,
)
from jarvis.personal_proxy.confirmation_ports import SpeechResult
from jarvis.personal_proxy.confirmation_texts import spoken_question

HEARD = "Отправь Марине Крыловой письмо на marina@example.org"
DOUBTS = (Doubt(DoubtKind.FRAGMENT, "marina@example.org"),)
CHECKED = CheckedTranscript(
    text=HEARD, doubts=DOUBTS, source=CheckSource.CHECKED, would_ask=True
)
TIMEOUT = 20.0
PHASE = 7.0


class Rig:
    """An exchange wired to fakes that share one call log. Each override is a
    factory taking the log."""

    def __init__(self, *, speaker_hold=False, **overrides):
        self.log = []
        factories = {
            "sink": FakeSink,
            "speaker": lambda log: FakeSpeaker(log, hold=speaker_hold),
            "microphone": FakeMicrophone,
        }
        factories.update(overrides)
        self.sink = factories["sink"](self.log)
        self.speaker = factories["speaker"](self.log)
        self.microphone = factories["microphone"](self.log)
        self.transcriber = overrides.get("transcriber", FakeTranscriber())
        if callable(self.transcriber):
            self.transcriber = self.transcriber(self.log)
        self.sleep = ManualSleep()
        self.exchange = ConfirmationExchange(
            sink=self.sink,
            speaker=self.speaker,
            microphone=self.microphone,
            transcriber=self.transcriber,
            language="ru",
            timeout_seconds=TIMEOUT,
            sleep=self.sleep,
            speech_phase_timeout_seconds=PHASE,
        )

    def start(self):
        return asyncio.ensure_future(self.exchange.run(CHECKED))

    async def start_until_window_opens(self):
        task = self.start()
        await until(lambda: self.exchange.state is ExchangeState.AWAITING)
        return task


async def until(condition, seconds=1.0):
    async with asyncio.timeout(seconds):
        while not condition():
            await asyncio.sleep(0)


async def finished(task, seconds=1.0):
    async with asyncio.timeout(seconds):
        return await task


def transcribing(text):
    return lambda log: FakeTranscriber(text)


# --- the answers -------------------------------------------------------------


async def test_a_typed_yes_confirms():
    r = Rig()
    task = await r.start_until_window_opens()

    assert r.exchange.submit_typed("Да!") is Delivery.ACCEPTED

    assert await finished(task) is ExchangeOutcome.CONFIRMED


async def test_a_spoken_yes_confirms_through_the_transcriber():
    r = Rig(transcriber=transcribing("Да, отправляй."))
    task = await r.start_until_window_opens()

    assert r.exchange.submit_spoken(b"wav") is Delivery.ACCEPTED

    assert await finished(task) is ExchangeOutcome.CONFIRMED
    assert r.transcriber.received == [b"wav"]


async def test_a_typed_no_declines():
    r = Rig()
    task = await r.start_until_window_opens()

    r.exchange.submit_typed("нет")

    assert await finished(task) is ExchangeOutcome.DECLINED


async def test_a_spoken_no_declines():
    r = Rig(transcriber=transcribing("стоп"))
    task = await r.start_until_window_opens()

    r.exchange.submit_spoken(b"wav")

    assert await finished(task) is ExchangeOutcome.DECLINED


@pytest.mark.parametrize("typed", ["да нет", "да но исправь", "", "может быть"])
async def test_a_typed_answer_outside_the_vocabulary_is_unclear(typed):
    r = Rig()
    task = await r.start_until_window_opens()

    r.exchange.submit_typed(typed)

    assert await finished(task) is ExchangeOutcome.UNCLEAR


async def test_a_spoken_answer_with_no_speech_is_unclear():
    r = Rig(transcriber=transcribing(None))
    task = await r.start_until_window_opens()

    r.exchange.submit_spoken(b"wav")

    assert await finished(task) is ExchangeOutcome.UNCLEAR


async def test_a_spoken_answer_with_extra_words_is_unclear():
    r = Rig(transcriber=transcribing("да но исправь адрес"))
    task = await r.start_until_window_opens()

    r.exchange.submit_spoken(b"wav")

    assert await finished(task) is ExchangeOutcome.UNCLEAR


# --- order, microphone and the window ---------------------------------------


async def test_the_calls_come_in_the_order_block_pause_speak_resume():
    r = Rig()
    task = await r.start_until_window_opens()

    assert r.log == ["post", "pause", "speak", "resume"]
    r.exchange.submit_typed("да")
    await finished(task)


async def test_the_heard_block_is_posted_with_the_whole_text_and_the_doubts():
    r = Rig()
    task = await r.start_until_window_opens()

    (block,) = r.sink.blocks
    assert block == HeardBlock(HEARD, DOUBTS, HeardDecision.ASK_CONFIRMATION)
    r.exchange.submit_typed("да")
    await finished(task)


async def test_the_question_spoken_names_the_doubts_in_the_given_language():
    r = Rig()
    task = await r.start_until_window_opens()

    assert r.speaker.spoken == [(spoken_question("ru", DOUBTS), "ru")]
    r.exchange.submit_typed("да")
    await finished(task)


async def test_the_window_does_not_open_before_resume_returns():
    resume_hold = asyncio.Event()
    r = Rig(microphone=lambda log: FakeMicrophone(log, resume_hold=resume_hold))
    task = r.start()
    await until(lambda: "resume" in r.log)

    assert r.exchange.state is ExchangeState.ASKING
    assert r.exchange.submit_spoken(b"wav") is Delivery.REJECTED
    assert TIMEOUT not in r.sleep.requested
    resume_hold.set()
    await until(lambda: r.exchange.state is ExchangeState.AWAITING)
    assert r.exchange.submit_spoken(b"wav") is Delivery.ACCEPTED
    await finished(task)


async def test_the_timeout_starts_when_the_window_opens_and_ends_with_timed_out():
    r = Rig()
    task = await r.start_until_window_opens()
    await until(lambda: TIMEOUT in r.sleep.requested)

    assert r.sleep.requested.count(TIMEOUT) == 1
    r.sleep.release(TIMEOUT)

    assert await finished(task) is ExchangeOutcome.TIMED_OUT


async def test_a_muted_speaker_opens_the_window_at_once_without_waiting_for_speech():
    r = Rig(speaker=lambda log: FakeSpeaker(log, result=SpeechResult.DISABLED))
    task = await r.start_until_window_opens()

    r.exchange.submit_typed("да")

    assert await finished(task) is ExchangeOutcome.CONFIRMED
    assert "stop" not in r.log


# --- answers while the question is spoken ------------------------------------


async def test_a_typed_answer_during_speech_stops_the_speech_and_decides():
    r = Rig(speaker_hold=True)
    task = r.start()
    await until(lambda: "speak" in r.log)

    assert r.exchange.submit_typed("нет") is Delivery.ACCEPTED

    assert await finished(task) is ExchangeOutcome.DECLINED
    assert "stop" in r.log
    assert r.log[-1] == "resume"
    assert TIMEOUT not in r.sleep.requested


async def test_a_spoken_answer_during_speech_is_not_accepted():
    r = Rig(speaker_hold=True)
    task = r.start()
    await until(lambda: "speak" in r.log)

    assert r.exchange.submit_spoken(b"wav") is Delivery.REJECTED

    r.speaker.release.set()
    await until(lambda: r.exchange.state is ExchangeState.AWAITING)
    r.exchange.submit_typed("да")
    await finished(task)
    assert r.transcriber.received == []


async def test_a_typed_answer_is_refused_until_the_heard_block_is_posted():
    hold = asyncio.Event()
    r = Rig(sink=lambda log: FakeSink(log, hold=hold))
    task = r.start()
    await until(lambda: "post" in r.log)

    assert r.exchange.submit_typed("да") is Delivery.REJECTED
    hold.set()
    await until(lambda: r.exchange.state is ExchangeState.AWAITING)
    assert r.exchange.submit_typed("да") is Delivery.ACCEPTED
    assert await finished(task) is ExchangeOutcome.CONFIRMED


async def test_only_the_first_answer_counts():
    r = Rig()
    task = await r.start_until_window_opens()

    assert r.exchange.submit_typed("нет") is Delivery.ACCEPTED
    assert r.exchange.submit_typed("да") is Delivery.REJECTED
    assert r.exchange.submit_spoken(b"wav") is Delivery.REJECTED

    assert await finished(task) is ExchangeOutcome.DECLINED


async def test_nothing_is_accepted_when_no_exchange_is_pending():
    r = Rig()

    assert r.exchange.submit_typed("да") is Delivery.REJECTED
    assert r.exchange.submit_spoken(b"wav") is Delivery.REJECTED


# --- interrupt ---------------------------------------------------------------


async def test_cancel_in_the_window_ends_the_exchange_as_cancelled():
    r = Rig()
    task = await r.start_until_window_opens()

    r.exchange.cancel()

    assert await finished(task) is ExchangeOutcome.CANCELLED


async def test_cancel_during_speech_stops_it_and_resumes_the_microphone():
    r = Rig(speaker_hold=True)
    task = r.start()
    await until(lambda: "speak" in r.log)

    r.exchange.cancel()

    assert await finished(task) is ExchangeOutcome.CANCELLED
    assert "stop" in r.log
    assert r.log[-1] == "resume"


async def test_cancel_while_the_answer_is_being_transcribed_wins_over_a_yes():
    class SlowTranscriber(FakeTranscriber):
        def __init__(self):
            super().__init__("да")
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def transcribe(self, utterance):
            self.entered.set()
            await self.release.wait()
            return self.text

    transcriber = SlowTranscriber()
    r = Rig(transcriber=transcriber)
    task = await r.start_until_window_opens()
    r.exchange.submit_spoken(b"wav")
    await transcriber.entered.wait()

    r.exchange.cancel()
    transcriber.release.set()

    assert await finished(task) is ExchangeOutcome.CANCELLED


async def test_cancel_with_nothing_pending_does_not_poison_the_next_exchange():
    r = Rig()

    r.exchange.cancel()

    task = await r.start_until_window_opens()
    r.exchange.submit_typed("да")
    assert await finished(task) is ExchangeOutcome.CONFIRMED


# --- failures and task cancellation ------------------------------------------


async def test_a_failing_sink_fails_the_exchange_and_the_user_is_never_asked():
    r = Rig(sink=lambda log: FakeSink(log, fail=True))

    assert await finished(r.start()) is ExchangeOutcome.FAILED
    assert r.log == ["post"]


async def test_a_failing_speaker_fails_the_exchange_and_resumes_the_microphone():
    r = Rig(speaker=lambda log: FakeSpeaker(log, error=RuntimeError("tts")))

    assert await finished(r.start()) is ExchangeOutcome.FAILED
    assert r.log == ["post", "pause", "speak", "resume"]


async def test_a_failing_pause_fails_the_exchange_and_still_resumes():
    r = Rig(microphone=lambda log: FakeMicrophone(log, pause_error=OSError("x")))

    assert await finished(r.start()) is ExchangeOutcome.FAILED
    assert r.log[-1] == "resume"


async def test_a_failing_resume_fails_the_exchange():
    r = Rig(microphone=lambda log: FakeMicrophone(log, resume_error=OSError("x")))

    assert await finished(r.start()) is ExchangeOutcome.FAILED


async def test_a_failing_transcriber_fails_the_exchange():
    r = Rig(transcriber=FakeTranscriber(error=RuntimeError("stt")))
    task = await r.start_until_window_opens()

    r.exchange.submit_spoken(b"wav")

    assert await finished(task) is ExchangeOutcome.FAILED


async def test_a_failing_timer_fails_the_exchange():
    class BrokenSleep:
        async def __call__(self, seconds):
            raise RuntimeError("clock")

    r = Rig()
    r.exchange = ConfirmationExchange(
        sink=r.sink,
        speaker=r.speaker,
        microphone=r.microphone,
        transcriber=r.transcriber,
        language="ru",
        timeout_seconds=TIMEOUT,
        sleep=BrokenSleep(),
    )

    assert await finished(r.start()) is ExchangeOutcome.FAILED


async def test_task_cancellation_during_speech_propagates_and_resumes_the_microphone():
    r = Rig(speaker_hold=True)
    task = r.start()
    await until(lambda: "speak" in r.log)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await finished(task)
    assert r.log[-1] == "resume"
    assert r.exchange.state is ExchangeState.DONE


async def test_task_cancellation_in_the_window_propagates_unchanged():
    r = Rig()
    task = await r.start_until_window_opens()

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await finished(task)
    assert r.exchange.state is ExchangeState.DONE


async def test_task_cancellation_is_not_swallowed_by_a_failing_resume():
    r = Rig(
        speaker_hold=True,
        microphone=lambda log: FakeMicrophone(log, resume_error=OSError("x")),
    )
    task = r.start()
    await until(lambda: "speak" in r.log)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await finished(task)


# --- one at a time and state -------------------------------------------------


async def test_a_second_run_while_one_is_pending_raises():
    r = Rig()
    task = await r.start_until_window_opens()

    with pytest.raises(ExchangeBusyError):
        await r.exchange.run(CHECKED)

    r.exchange.submit_typed("да")
    await finished(task)


async def test_the_exchange_can_run_again_after_it_ended():
    r = Rig()
    for typed, expected in (
        ("да", ExchangeOutcome.CONFIRMED),
        ("нет", ExchangeOutcome.DECLINED),
    ):
        task = await r.start_until_window_opens()
        r.exchange.submit_typed(typed)

        assert await finished(task) is expected
        assert r.exchange.state is ExchangeState.DONE


async def test_the_states_go_asking_awaiting_done():
    r = Rig(speaker_hold=True)
    assert r.exchange.state is ExchangeState.DONE
    task = r.start()
    await until(lambda: "speak" in r.log)
    assert r.exchange.state is ExchangeState.ASKING
    r.speaker.release.set()
    await until(lambda: r.exchange.state is ExchangeState.AWAITING)
    r.exchange.submit_typed("да")
    await finished(task)

    assert r.exchange.state is ExchangeState.DONE


# --- privacy -----------------------------------------------------------------


async def test_the_exchange_repr_shows_nothing_heard_or_answered_at_any_time():
    typed = "ответ-пользователя"
    r = Rig()
    task = await r.start_until_window_opens()
    r.exchange.submit_typed(typed)
    with pytest.raises(ExchangeBusyError) as busy:
        await r.exchange.run(CHECKED)

    during = repr(r.exchange)
    await finished(task)
    for shown in (during, repr(r.exchange), str(busy.value), repr(busy.value)):
        for secret in ("marina", "Марин", "Крылов", typed):
            assert secret not in shown


async def test_the_answer_text_is_not_kept_after_the_exchange():
    secret_answer = "ответ-который-нельзя-хранить"
    r = Rig()
    task = await r.start_until_window_opens()
    r.exchange.submit_typed(secret_answer)
    await finished(task)

    assert secret_answer not in repr(vars(r.exchange))
    assert HEARD not in repr(vars(r.exchange))


# --- bounded waits -------------------------------------------------------------


def _all_other_tasks_done():
    others = asyncio.all_tasks() - {asyncio.current_task()}
    return all(task.done() for task in others)


def test_the_speech_phase_limit_is_thirty_seconds_by_default():
    assert SPEECH_PHASE_TIMEOUT_SECONDS == 30


async def test_a_hung_speaker_is_stopped_the_microphone_resumed_and_the_window_opens():
    r = Rig(speaker=lambda log: FakeSpeaker(log, hold=True, ignore_stop=True))
    task = r.start()
    await until(lambda: "speak" in r.log)

    r.sleep.release(PHASE)

    await until(lambda: r.exchange.state is ExchangeState.AWAITING)
    assert r.log == ["post", "pause", "speak", "stop", "resume"]
    r.exchange.submit_typed("да")
    assert await finished(task) is ExchangeOutcome.CONFIRMED


async def test_a_hung_sink_fails_the_exchange_without_asking():
    r = Rig(sink=lambda log: FakeSink(log, hold=asyncio.Event()))
    task = r.start()
    await until(lambda: "post" in r.log)

    r.sleep.release(PHASE)

    assert await finished(task) is ExchangeOutcome.FAILED
    assert r.exchange.last_failure is FailureStage.SINK
    assert r.log == ["post"]


async def test_a_hung_pause_fails_the_exchange_and_still_resumes():
    r = Rig(microphone=lambda log: FakeMicrophone(log, pause_hold=asyncio.Event()))
    task = r.start()
    await until(lambda: "pause" in r.log)

    r.sleep.release(PHASE)

    assert await finished(task) is ExchangeOutcome.FAILED
    assert r.exchange.last_failure is FailureStage.MICROPHONE
    assert r.log[-1] == "resume"


async def test_a_hung_resume_fails_the_exchange():
    r = Rig(microphone=lambda log: FakeMicrophone(log, resume_hold=asyncio.Event()))
    task = r.start()
    await until(lambda: "resume" in r.log)

    r.sleep.release(PHASE)

    assert await finished(task) is ExchangeOutcome.FAILED
    assert r.exchange.last_failure is FailureStage.MICROPHONE


async def test_cancel_ends_the_exchange_even_if_the_transcriber_never_returns():
    transcriber = FakeTranscriber(hang=True)
    r = Rig(transcriber=transcriber)
    task = await r.start_until_window_opens()
    r.exchange.submit_spoken(b"wav")
    await until(lambda: transcriber.received)

    r.exchange.cancel()

    assert await finished(task) is ExchangeOutcome.CANCELLED
    assert transcriber.cancelled is True
    await until(_all_other_tasks_done)


async def test_a_transcriber_that_never_returns_fails_the_exchange_at_the_limit():
    transcriber = FakeTranscriber(hang=True)
    r = Rig(transcriber=transcriber)
    task = await r.start_until_window_opens()
    r.exchange.submit_spoken(b"wav")
    await until(lambda: transcriber.received)

    r.sleep.release(PHASE)

    assert await finished(task) is ExchangeOutcome.FAILED
    assert r.exchange.last_failure is FailureStage.TRANSCRIBER
    assert transcriber.cancelled is True


# --- the loop contract ---------------------------------------------------------


async def test_answers_and_cancel_from_another_thread_are_refused_loudly():
    r = Rig()
    task = await r.start_until_window_opens()

    with pytest.raises(WrongLoopError):
        await asyncio.to_thread(r.exchange.submit_typed, "да")
    with pytest.raises(WrongLoopError):
        await asyncio.to_thread(r.exchange.submit_spoken, b"wav")
    with pytest.raises(WrongLoopError):
        await asyncio.to_thread(r.exchange.cancel)

    r.exchange.submit_typed("да")
    assert await finished(task) is ExchangeOutcome.CONFIRMED


async def test_another_thread_offering_an_answer_when_nothing_is_pending_is_harmless():
    r = Rig()

    assert await asyncio.to_thread(r.exchange.submit_typed, "да") is Delivery.REJECTED


# --- edges ---------------------------------------------------------------------


async def test_a_non_text_typed_answer_is_rejected_and_does_not_decide():
    r = Rig()
    task = await r.start_until_window_opens()

    assert r.exchange.submit_typed(None) is Delivery.REJECTED
    assert r.exchange.submit_typed(b"da") is Delivery.REJECTED
    assert r.exchange.submit_spoken("not bytes") is Delivery.REJECTED

    assert not task.done()
    r.exchange.submit_typed("да")
    assert await finished(task) is ExchangeOutcome.CONFIRMED


async def test_a_request_with_no_doubts_is_still_asked_when_run_is_called():
    no_doubts = CheckedTranscript(
        text=HEARD, doubts=(), source=CheckSource.CHECKED, would_ask=True
    )
    r = Rig()
    task = asyncio.ensure_future(r.exchange.run(no_doubts))
    await until(lambda: r.exchange.state is ExchangeState.AWAITING)

    assert r.log == ["post", "pause", "speak", "resume"]
    r.exchange.submit_typed("да")
    assert await finished(task) is ExchangeOutcome.CONFIRMED


# --- why it failed ---------------------------------------------------------------


async def test_the_failure_stage_is_none_until_a_failure_and_after_a_good_run():
    r = Rig()
    assert r.exchange.last_failure is None
    task = await r.start_until_window_opens()
    r.exchange.submit_typed("да")
    await finished(task)

    assert r.exchange.last_failure is None


@pytest.mark.parametrize(
    "factories, stage",
    [
        ({"sink": lambda log: FakeSink(log, fail=True)}, FailureStage.SINK),
        (
            {"speaker": lambda log: FakeSpeaker(log, error=RuntimeError("x"))},
            FailureStage.SPEAKER,
        ),
        (
            {"microphone": lambda log: FakeMicrophone(log, pause_error=OSError("x"))},
            FailureStage.MICROPHONE,
        ),
        (
            {"microphone": lambda log: FakeMicrophone(log, resume_error=OSError("x"))},
            FailureStage.MICROPHONE,
        ),
    ],
)
async def test_each_failing_port_is_named_as_the_stage_of_the_failure(factories, stage):
    r = Rig(**factories)

    assert await finished(r.start()) is ExchangeOutcome.FAILED
    assert r.exchange.last_failure is stage


async def test_a_failing_transcriber_is_named_as_the_transcriber_stage():
    r = Rig(transcriber=FakeTranscriber(error=RuntimeError("stt")))
    task = await r.start_until_window_opens()
    r.exchange.submit_spoken(b"wav")

    assert await finished(task) is ExchangeOutcome.FAILED
    assert r.exchange.last_failure is FailureStage.TRANSCRIBER


async def test_a_failing_speaker_is_named_even_when_the_resume_failed_too():
    r = Rig(
        speaker=lambda log: FakeSpeaker(log, error=RuntimeError("x")),
        microphone=lambda log: FakeMicrophone(log, resume_error=OSError("x")),
    )

    assert await finished(r.start()) is ExchangeOutcome.FAILED
    assert r.exchange.last_failure is FailureStage.SPEAKER


async def test_the_failure_stage_is_reset_on_the_next_run():
    class OneBadSink(FakeSink):
        async def post(self, block):
            self.fail = not self.blocks
            await super().post(block)

    r = Rig(sink=lambda log: OneBadSink(log))
    assert await finished(r.start()) is ExchangeOutcome.FAILED
    assert r.exchange.last_failure is FailureStage.SINK

    task = await r.start_until_window_opens()

    assert r.exchange.last_failure is None
    r.exchange.submit_typed("да")
    await finished(task)


async def test_a_timer_that_fails_is_an_internal_failure():
    class BrokenSleep:
        async def __call__(self, seconds):
            raise RuntimeError("clock")

    r = Rig()
    r.exchange = ConfirmationExchange(
        sink=r.sink,
        speaker=r.speaker,
        microphone=r.microphone,
        transcriber=r.transcriber,
        language="ru",
        timeout_seconds=TIMEOUT,
        sleep=BrokenSleep(),
    )

    assert await finished(r.start()) is ExchangeOutcome.FAILED
    assert r.exchange.last_failure is FailureStage.INTERNAL


def test_the_exchange_docstring_states_the_loop_contract():
    doc = ConfirmationExchange.__doc__
    assert "event loop" in doc
    assert "run_coroutine_threadsafe" in doc
