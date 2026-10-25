"""Review findings on PersonalProxyService: dry run with a question, a resume
that survives cancellation, interrupts from other threads, a deltas stream that
is always closed, a router that a hung sink cannot freeze, and pinned order."""

import asyncio
import threading
from contextlib import asynccontextmanager

import pytest
from _confirmation_fakes import (
    FakeSink,
    FakeSpeaker,
    FakeTranscriber,
    ManualSleep,
)
from _service_fakes import (
    CHECKED_WITH_DOUBT,
    SANITIZED,
    RecordingSink,
    Rig,
    closed,
    make_wav,
    settled,
    until,
    within,
)

from jarvis.personal_proxy.answer.answer_voice import AnswerVoice
from jarvis.personal_proxy.common.findings import GateCategory, GateStage
from jarvis.personal_proxy.confirmation.confirmation_exchange import (
    ConfirmationExchange,
)
from jarvis.personal_proxy.confirmation.confirmation_outcome import ExchangeOutcome
from jarvis.personal_proxy.confirmation.confirmation_texts import spoken_question
from jarvis.personal_proxy.reporting.service_blocks import (
    DryRunBlock,
    NoticeBlock,
    NoticeKind,
)
from jarvis.personal_proxy.request.proxy_inbox import TypedText, Utterance
from jarvis.personal_proxy.sanitize.sanitize_result import (
    SanitizeFailure,
    SanitizeFailureClass,
)
from jarvis.personal_proxy.service import proxy_service
from jarvis.ui.contract import DataLocality

UTTERANCE = Utterance(make_wav())


@asynccontextmanager
async def asking(rig):
    rig.stages.checked = CHECKED_WITH_DOUBT
    rig.service.start()
    try:
        rig.service.submit(UTTERANCE)
        await until(
            lambda: rig.settings.confirmation_timeout_seconds in rig.sleep.requested
        )
        yield
    finally:
        await closed(rig.service)


# --- 1. a dry run never asks -------------------------------------------------


async def test_a_dry_run_with_a_doubt_asks_nothing_and_posts_the_state():
    rig = Rig(dry_run=True)
    rig.stages.checked = CHECKED_WITH_DOUBT
    rig.service.start()
    rig.service.submit(UTTERANCE)
    await settled(rig)
    await closed(rig.service)

    assert [type(block) for block in rig.sink.blocks] == [DryRunBlock]
    (dry,) = rig.sink.of(DryRunBlock)
    assert dry.would_ask is True
    assert dry.doubts == CHECKED_WITH_DOUBT.doubts
    assert dry.sanitized_text == SANITIZED
    assert rig.speaker.spoken == []
    assert [e for e in rig.log if e in ("pause", "resume", "speak")] == []
    assert rig.sleep.requested == []
    assert rig.stages.calls["open_stream"] == []


async def test_a_dry_run_without_a_doubt_posts_the_full_state():
    rig = Rig(dry_run=True)
    rig.service.start()
    rig.service.submit(UTTERANCE)
    await settled(rig)
    await closed(rig.service)

    (dry,) = rig.sink.of(DryRunBlock)
    assert dry.would_ask is False
    assert dry.messages[1] == ("user", SANITIZED)


async def test_a_typed_text_dry_run_posts_the_state_without_asking():
    rig = Rig(dry_run=True)
    rig.service.start()
    rig.service.submit(TypedText("Привет"))
    await settled(rig)
    await closed(rig.service)

    assert [type(block) for block in rig.sink.blocks] == [DryRunBlock]


async def test_a_dry_run_still_stops_at_a_refusal_and_a_gate_block():
    rig = Rig(dry_run=True)
    rig.stages.checked = CHECKED_WITH_DOUBT
    rig.stages.sanitized = SanitizeFailure(SanitizeFailureClass.NO_JSON)
    rig.service.start()
    rig.service.submit(UTTERANCE)
    await settled(rig)
    await closed(rig.service)

    assert rig.sink.of(DryRunBlock) == []
    assert rig.sink.notices() == [NoticeKind.SANITIZE_FAILED]


# --- 2. the microphone resume is finished even when the caller is cancelled --


class SlowResumeMicrophone:
    def __init__(self):
        self.pauses = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.completed = 0

    async def pause(self):
        self.pauses += 1

    async def resume(self):
        self.started.set()
        await self.release.wait()
        self.completed += 1


async def test_a_session_finishes_the_resume_when_cancelled_during_it_then_raises():
    log = []
    microphone = SlowResumeMicrophone()
    voice = AnswerVoice(
        speaker=FakeSpeaker(log),
        microphone=microphone,
        language=lambda: "en",
        resume_limit_seconds=5.0,
    )

    async def speaking():
        async with voice.session() as session:
            await session.say("One.")

    task = asyncio.ensure_future(speaking())
    await within(microphone.started.wait())
    task.cancel()
    await asyncio.sleep(0)
    microphone.release.set()
    with pytest.raises(asyncio.CancelledError):
        await within(task)

    assert microphone.completed == microphone.pauses == 1


async def test_a_session_cancelled_twice_still_finishes_the_resume():
    log = []
    microphone = SlowResumeMicrophone()
    voice = AnswerVoice(
        speaker=FakeSpeaker(log, hold=True),
        microphone=microphone,
        language=lambda: "en",
        resume_limit_seconds=5.0,
    )

    async def speaking():
        async with voice.session() as session:
            await session.say("One.")

    task = asyncio.ensure_future(speaking())
    await until(lambda: "speak" in log)
    task.cancel()
    await within(microphone.started.wait())
    task.cancel()
    await asyncio.sleep(0)
    microphone.release.set()
    with pytest.raises(asyncio.CancelledError):
        await within(task)

    assert microphone.completed == 1


async def test_a_hung_resume_is_still_given_up_when_cancelled():
    log = []
    microphone = SlowResumeMicrophone()
    voice = AnswerVoice(
        speaker=FakeSpeaker(log),
        microphone=microphone,
        language=lambda: "en",
        resume_limit_seconds=0.05,
    )

    async def speaking():
        async with voice.session() as session:
            await session.say("One.")

    task = asyncio.ensure_future(speaking())
    await within(microphone.started.wait())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await within(task)

    assert microphone.completed == 0


async def test_the_exchange_finishes_the_resume_when_cancelled_during_it():
    log = []
    microphone = SlowResumeMicrophone()
    sleep = ManualSleep()
    exchange = ConfirmationExchange(
        sink=FakeSink(log),
        speaker=FakeSpeaker(log, hold=True),
        microphone=microphone,
        transcriber=FakeTranscriber(),
        language="en",
        timeout_seconds=20.0,
        sleep=sleep,
        speech_phase_timeout_seconds=7.0,
    )
    task = asyncio.ensure_future(exchange.run(CHECKED_WITH_DOUBT))
    await until(lambda: "speak" in log)
    task.cancel()
    await within(microphone.started.wait())
    task.cancel()
    await asyncio.sleep(0)
    microphone.release.set()
    with pytest.raises(asyncio.CancelledError):
        await within(task)

    assert microphone.completed == microphone.pauses == 1


# --- 3. interrupt from another thread ----------------------------------------


class NotifyingSink(RecordingSink):
    def __init__(self, log):
        super().__init__(log)
        self.arrived = asyncio.Event()

    async def post(self, block):
        await super().post(block)
        if isinstance(block, NoticeBlock):
            self.arrived.set()


async def test_a_timer_thread_interrupt_wakes_an_idle_loop_and_cancels_the_request():
    rig = Rig(sink=NotifyingSink([]))
    rig.sink.log = rig.log
    rig.stages.holds["sanitize"] = asyncio.Event()
    rig.service.start()
    try:
        rig.service.submit(TypedText("один"))
        await until(lambda: len(rig.stages.calls["sanitize"]) == 1)

        timer = threading.Timer(0.05, rig.service.interrupt)
        timer.start()
        await asyncio.wait_for(rig.sink.arrived.wait(), 0.5)
        timer.join()
    finally:
        await closed(rig.service)

    assert rig.sink.notices() == [NoticeKind.INTERRUPTED]
    assert rig.stages.calls["open_stream"] == []


async def test_a_pending_exchange_is_cancelled_from_another_thread():
    rig = Rig(sink=NotifyingSink([]))
    rig.sink.log = rig.log
    rig.stages.checked = CHECKED_WITH_DOUBT
    rig.service.start()
    try:
        rig.service.submit(UTTERANCE)
        await until(
            lambda: rig.settings.confirmation_timeout_seconds in rig.sleep.requested
        )

        timer = threading.Timer(0.05, rig.service.interrupt)
        timer.start()
        await asyncio.wait_for(rig.sink.arrived.wait(), 0.5)
        timer.join()
    finally:
        await closed(rig.service)

    (notice,) = rig.sink.of(NoticeBlock)
    assert notice.detail is ExchangeOutcome.CANCELLED


async def test_an_interrupt_before_start_is_a_no_op():
    rig = Rig()

    rig.service.interrupt()
    await asyncio.to_thread(rig.service.interrupt)

    assert rig.sink.blocks == []


# --- 4. the external deltas are closed by the pipeline itself ----------------


async def test_the_locality_returns_to_local_when_restore_does_not_close_its_input():
    rig = Rig()
    kept = []

    def reads_one_and_returns(deltas, mapping):
        kept.append(deltas)

        async def sentences():
            async for _ in deltas:
                break
            return
            yield

        return sentences()

    rig.stages.restore_override = reads_one_and_returns
    rig.service.start()
    rig.service.submit(TypedText("один"))
    await settled(rig)
    await closed(rig.service)

    assert rig.locality.history == [DataLocality.EXTERNAL, DataLocality.LOCAL]
    assert rig.stages.streams[0].closed


# --- 5. the router cannot be frozen by a hung sink ---------------------------


class HangingBusySink(RecordingSink):
    async def post(self, block):
        if isinstance(block, NoticeBlock) and block.kind is NoticeKind.BUSY:
            self.log.append("busy_post")
            await asyncio.Event().wait()
        await super().post(block)


async def test_a_busy_notice_that_never_returns_does_not_freeze_the_router(
    monkeypatch,
):
    monkeypatch.setattr(proxy_service, "BUSY_POST_LIMIT_SECONDS", 0.1)
    rig = Rig(sink=HangingBusySink([]), queue_capacity=1)
    rig.sink.log = rig.log
    rig.stages.checked = CHECKED_WITH_DOUBT
    rig.stages.holds["sanitize"] = asyncio.Event()
    rig.service.start()
    try:
        rig.service.submit(UTTERANCE)
        await until(lambda: len(rig.stages.calls["sanitize"]) == 1)
        rig.service.submit(TypedText("второй"))
        rig.service.submit(TypedText("третий"))
        await until(lambda: "busy_post" in rig.log)
        rig.stages.holds["sanitize"].set()
        await until(
            lambda: rig.settings.confirmation_timeout_seconds in rig.sleep.requested
        )

        rig.service.submit(TypedText("да"))
        await until(lambda: len(rig.payloads_sent) >= 1)
    finally:
        await closed(rig.service)

    assert rig.payloads_sent[0].to_chat_messages()[1]["content"] == SANITIZED


# --- 9. pins ----------------------------------------------------------------


async def test_the_sentence_stream_is_closed_when_cancelled_while_speaking():
    rig = Rig(speaker=FakeSpeaker([], hold=True))
    rig.speaker.log = rig.log
    state = {"closed": False}
    kept = []

    def one_sentence_then_wait(deltas, mapping):
        from jarvis.personal_proxy.restoration.restoration_result import (
            RestorationMethod,
            RestoredSentence,
        )

        async def sentences():
            try:
                yield RestoredSentence("Первое.", RestorationMethod.PASSTHROUGH, False)
                await asyncio.Event().wait()
            finally:
                state["closed"] = True

        generator = sentences()
        kept.append(generator)
        return generator

    rig.stages.restore_override = one_sentence_then_wait
    rig.service.start()
    rig.service.submit(TypedText("один"))
    await until(lambda: "speak" in rig.log)

    rig.service.interrupt()
    await settled(rig)

    assert state["closed"] is True
    await closed(rig.service)


async def test_an_answer_block_is_posted_before_its_sentence_is_spoken():
    rig = Rig()
    rig.service.start()
    rig.service.submit(TypedText("один"))
    await settled(rig)
    await closed(rig.service)

    posts = [i for i, entry in enumerate(rig.log) if entry == "post:AnswerBlock"]
    speeches = [i for i, entry in enumerate(rig.log) if entry == "speak"]
    assert len(posts) == len(speeches) == 2
    assert all(post < speech for post, speech in zip(posts, speeches, strict=True))


@pytest.mark.parametrize("language", ["ru", "en"])
async def test_the_question_is_spoken_in_the_language_of_the_provider(language):
    rig = Rig(language=language)

    async with asking(rig):
        pass

    expected = spoken_question(language, CHECKED_WITH_DOUBT.doubts)
    assert rig.speaker.spoken[0] == (expected, language)


@pytest.mark.parametrize("verdict", [None, "allowed", object()])
async def test_a_gate_result_that_is_not_a_gate_result_blocks_with_a_gate_error(
    verdict,
):
    from dataclasses import replace

    from jarvis.personal_proxy.service.proxy_service import PersonalProxyService

    rig = Rig()
    stages = replace(rig.stages.as_stages(), gate=lambda payload, context: verdict)
    service = PersonalProxyService(
        stages=stages,
        sink=rig.sink,
        speaker=rig.speaker,
        microphone=rig.microphone,
        locality=rig.locality,
        language=lambda: "en",
        settings=rig.settings,
        topics_text="",
        sleep=rig.sleep,
    )
    service.start()
    service.submit(TypedText("один"))
    await until(lambda: service.idle)
    await closed(service)

    (notice,) = rig.sink.of(NoticeBlock)
    (finding,) = notice.detail
    assert finding.category is GateCategory.GATE_ERROR
    assert finding.stage is GateStage.UNKNOWN
