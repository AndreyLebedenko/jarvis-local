"""Interrupt, close, cancellation and privacy of PersonalProxyService."""

import asyncio
import logging
import threading
from contextlib import asynccontextmanager

import pytest
from _confirmation_fakes import FakeMicrophone, FakeSpeaker
from _service_fakes import (
    CHECKED_WITH_DOUBT,
    HEARD,
    RecordingSink,
    Rig,
    closed,
    make_wav,
    settled,
    until,
)

from jarvis.personal_proxy.confirmation.confirmation_blocks import HeardBlock, SentBlock
from jarvis.personal_proxy.confirmation.confirmation_outcome import ExchangeOutcome
from jarvis.personal_proxy.confirmation.confirmation_ports import SpeechResult
from jarvis.personal_proxy.confirmation.confirmation_texts import shown_question
from jarvis.personal_proxy.reporting.service_blocks import (
    AnswerBlock,
    DryRunBlock,
    NoticeBlock,
    NoticeKind,
)
from jarvis.personal_proxy.request.proxy_inbox import TypedText, Utterance
from jarvis.ui.contract import DataLocality

UTTERANCE = Utterance(make_wav())
SECRET = "SECRET Марина marina@example.org"


@asynccontextmanager
async def running(rig):
    rig.service.start()
    try:
        yield rig
    finally:
        await closed(rig.service)


async def spin(turns=30):
    for _ in range(turns):
        await asyncio.sleep(0)


def audio_log(rig):
    return [entry for entry in rig.log if entry in ("pause", "speak", "resume")]


def asking_rig(**kwargs):
    rig = Rig(**kwargs)
    rig.stages.checked = CHECKED_WITH_DOUBT
    return rig


async def until_window_open(rig):
    await until(
        lambda: rig.settings.confirmation_timeout_seconds in rig.sleep.requested
    )


# --- interrupt ---------------------------------------------------------------


async def test_an_interrupt_before_the_stream_opens_sends_nothing():
    rig = Rig()
    rig.stages.holds["sanitize"] = asyncio.Event()
    async with running(rig):
        rig.service.submit(TypedText("один"))
        await until(lambda: len(rig.stages.calls["sanitize"]) == 1)

        rig.service.interrupt()
        await settled(rig)

    assert rig.stages.calls["open_stream"] == []
    assert rig.sink.notices() == [NoticeKind.INTERRUPTED]
    assert rig.locality.history == []


async def test_an_interrupt_after_the_stream_opened_closes_it_and_stops_the_speech():
    rig = Rig(speaker=FakeSpeaker([], hold=True))
    rig.speaker.log = rig.log
    async with running(rig):
        rig.service.submit(TypedText("один"))
        await until(lambda: "speak" in rig.log)
        assert rig.stages.calls["open_stream"]

        rig.service.interrupt()
        await settled(rig)

    assert rig.stages.streams[0].closed
    assert "stop" in rig.log
    assert rig.locality.current is DataLocality.LOCAL
    assert audio_log(rig)[-1] == "resume"
    assert rig.sink.notices() == [NoticeKind.INTERRUPTED]


async def test_an_interrupt_during_the_stream_ends_the_external_scope():
    rig = Rig()
    rig.stages.stream_gate = asyncio.Event()
    async with running(rig):
        rig.service.submit(TypedText("один"))
        await until(lambda: rig.locality.history == [DataLocality.EXTERNAL])

        rig.service.interrupt()
        await settled(rig)

    assert rig.locality.history == [DataLocality.EXTERNAL, DataLocality.LOCAL]
    assert rig.stages.streams[0].closed
    assert rig.sink.of(AnswerBlock) == []


async def test_the_worker_goes_on_with_the_next_request_after_an_interrupt():
    rig = Rig()
    rig.stages.holds["sanitize"] = asyncio.Event()
    async with running(rig):
        rig.service.submit(TypedText("один"))
        rig.service.submit(TypedText("два"))
        await until(lambda: len(rig.stages.calls["sanitize"]) == 1)
        rig.service.interrupt()
        await until(lambda: len(rig.stages.calls["sanitize"]) == 2)
        rig.stages.holds["sanitize"].set()
        await settled(rig)

    assert len(rig.payloads_sent) == 1


async def test_an_interrupt_during_a_pending_question_cancels_the_exchange():
    rig = asking_rig()
    async with running(rig):
        rig.service.submit(UTTERANCE)
        await until_window_open(rig)

        rig.service.interrupt()
        await settled(rig)

    (notice,) = rig.sink.of(NoticeBlock)
    assert (notice.kind, notice.detail) == (
        NoticeKind.NOT_SENT,
        ExchangeOutcome.CANCELLED,
    )
    assert rig.stages.calls["open_stream"] == []


async def test_cancelling_the_pending_question_ends_it_as_declined_and_sends_nothing():
    rig = asking_rig()
    async with running(rig):
        rig.service.submit(UTTERANCE)
        await until_window_open(rig)

        rig.service.cancel_pending_question()
        await settled(rig)

    (notice,) = rig.sink.of(NoticeBlock)
    assert (notice.kind, notice.detail) == (
        NoticeKind.NOT_SENT,
        ExchangeOutcome.CANCELLED,
    )
    assert rig.stages.calls["open_stream"] == []


async def test_cancelling_the_pending_question_from_another_thread_works():
    rig = asking_rig()
    async with running(rig):
        rig.service.submit(UTTERANCE)
        await until_window_open(rig)

        await asyncio.to_thread(rig.service.cancel_pending_question)
        await settled(rig)

    assert rig.sink.of(NoticeBlock)[0].detail is ExchangeOutcome.CANCELLED


async def test_cancelling_the_pending_question_leaves_a_request_in_flight_alone():
    rig = Rig()
    rig.stages.holds["sanitize"] = asyncio.Event()
    async with running(rig):
        rig.service.submit(TypedText("один"))
        await until(lambda: len(rig.stages.calls["sanitize"]) == 1)

        rig.service.cancel_pending_question()
        rig.stages.holds["sanitize"].set()
        await settled(rig)

    assert NoticeKind.INTERRUPTED not in rig.sink.notices()
    assert rig.stages.calls["open_stream"]


async def test_cancelling_a_question_when_nothing_runs_never_raises():
    rig = Rig()
    rig.service.cancel_pending_question()
    async with running(rig):
        rig.service.cancel_pending_question()
        await spin()

    assert rig.sink.blocks == []


async def test_an_interrupt_while_the_question_is_spoken_cancels_it_too():
    rig = asking_rig(speaker=FakeSpeaker([], hold=True))
    rig.speaker.log = rig.log
    async with running(rig):
        rig.service.submit(UTTERANCE)
        await until(lambda: "speak" in rig.log)

        rig.service.interrupt()
        await settled(rig)

    assert rig.sink.of(NoticeBlock)[0].detail is ExchangeOutcome.CANCELLED
    assert rig.stages.calls["open_stream"] == []
    assert audio_log(rig)[-1] == "resume"


async def test_an_interrupt_when_nothing_runs_does_nothing_and_never_raises():
    rig = Rig()
    rig.service.interrupt()
    async with running(rig):
        rig.service.interrupt()
        await spin()
        rig.service.interrupt()

    assert rig.sink.blocks == []


async def test_an_interrupt_from_another_thread_never_raises():
    rig = asking_rig()
    errors = []

    def from_thread():
        try:
            rig.service.interrupt()
        except BaseException as error:
            errors.append(error)

    async with running(rig):
        rig.service.submit(UTTERANCE)
        await until_window_open(rig)
        worker = threading.Thread(target=from_thread)
        worker.start()
        await asyncio.to_thread(worker.join)

        assert errors == []
        rig.service.interrupt()
        await settled(rig)


# --- close -------------------------------------------------------------------


async def test_close_is_idempotent_and_works_before_start():
    rig = Rig()

    await closed(rig.service)
    await closed(rig.service)
    await asyncio.gather(rig.service.close(), rig.service.close())


async def test_submit_after_close_is_refused_without_content():
    rig = Rig()
    rig.service.start()
    await closed(rig.service)

    with pytest.raises(Exception) as raised:
        rig.service.submit(TypedText(SECRET))

    assert "SECRET" not in repr(raised.value) + str(raised.value)


async def test_close_during_the_stream_closes_it_and_leaves_the_locality_local():
    rig = Rig()
    rig.stages.stream_gate = asyncio.Event()
    rig.service.start()
    rig.service.submit(TypedText("один"))
    await until(lambda: rig.locality.history == [DataLocality.EXTERNAL])

    await closed(rig.service)

    assert rig.stages.streams[0].closed
    assert rig.locality.current is DataLocality.LOCAL
    assert rig.sink.notices() == []
    assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]


async def test_close_during_the_answer_speech_stops_the_speaker_and_resumes_the_mic():
    rig = Rig(speaker=FakeSpeaker([], hold=True))
    rig.speaker.log = rig.log
    rig.service.start()
    rig.service.submit(TypedText("один"))
    await until(lambda: "speak" in rig.log)

    await closed(rig.service)

    assert "stop" in rig.log
    assert audio_log(rig)[-1] == "resume"
    assert rig.locality.current is DataLocality.LOCAL


async def test_close_during_a_pending_question_cancels_it_without_an_offer():
    rig = asking_rig()
    rig.service.start()
    rig.service.submit(UTTERANCE)
    await until_window_open(rig)

    await closed(rig.service)

    assert rig.sink.of(NoticeBlock) == []
    assert rig.stages.calls["open_stream"] == []
    assert audio_log(rig).count("pause") == audio_log(rig).count("resume")
    assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]


async def test_close_while_the_question_is_spoken_stops_the_speaker_and_resumes():
    rig = asking_rig(speaker=FakeSpeaker([], hold=True))
    rig.speaker.log = rig.log
    rig.service.start()
    rig.service.submit(UTTERANCE)
    await until(lambda: "speak" in rig.log)

    await closed(rig.service)

    assert audio_log(rig)[-1] == "resume"
    assert rig.stages.calls["open_stream"] == []


async def test_close_while_a_stage_is_hung_does_not_wait_for_it():
    rig = Rig()
    rig.stages.holds["sanitize"] = asyncio.Event()
    rig.service.start()
    rig.service.submit(TypedText("один"))
    await until(lambda: len(rig.stages.calls["sanitize"]) == 1)

    async with asyncio.timeout(1):
        await closed(rig.service)

    assert rig.stages.calls["open_stream"] == []


async def test_close_stops_the_speaker_even_when_it_was_idle():
    rig = Rig()
    rig.service.start()

    await closed(rig.service)

    assert "stop" in rig.log


# --- privacy ----------------------------------------------------------------


async def test_the_service_writes_no_log_line_on_any_path(caplog):
    caplog.set_level(logging.DEBUG)
    for configure in (
        lambda rig: None,
        lambda rig: rig.stages.errors.update(sanitize=RuntimeError(SECRET)),
        lambda rig: setattr(rig.stages, "stream_error", RuntimeError(SECRET)),
        lambda rig: setattr(rig.stages, "open_error", RuntimeError(SECRET)),
    ):
        rig = Rig()
        configure(rig)
        rig.service.start()
        rig.service.submit(UTTERANCE)
        await settled(rig)
        await closed(rig.service)
    dry = Rig(dry_run=True)
    dry.service.start()
    dry.service.submit(UTTERANCE)
    await settled(dry)
    await closed(dry.service)
    asking = asking_rig()
    asking.service.start()
    asking.service.submit(UTTERANCE)
    await until_window_open(asking)
    asking.service.interrupt()
    await settled(asking)
    await closed(asking.service)

    assert caplog.records == []


async def test_nothing_derived_from_a_failure_reaches_a_block_or_a_repr():
    rig = Rig()
    rig.stages.errors["sanitize"] = RuntimeError(SECRET)

    rig.service.start()
    rig.service.submit(UTTERANCE)
    await settled(rig)
    await closed(rig.service)

    shown = repr(rig.sink.blocks) + repr(rig.service) + str(rig.service)
    assert "SECRET" not in shown
    assert HEARD not in shown
    assert "Марина" not in shown


async def test_blocks_with_personal_text_hide_it_in_repr():
    rig = Rig(dry_run=True)

    rig.service.start()
    rig.service.submit(UTTERANCE)
    await settled(rig)
    await closed(rig.service)

    shown = repr(rig.sink.blocks) + str(rig.sink.blocks)
    assert HEARD not in shown
    assert "Марине" not in shown
    assert rig.sink.of(DryRunBlock)
    assert not rig.sink.of(SentBlock)


async def test_the_microphone_is_resumed_whatever_ends_the_answer():
    for error in ("speaker", "stream", "sink"):
        rig = Rig()
        if error == "speaker":
            rig.speaker = FakeSpeaker(rig.log, error=RuntimeError(SECRET))
            rig.service = _rebuilt(rig)
        if error == "stream":
            rig.stages.stream_error = RuntimeError(SECRET)
        if error == "sink":
            rig.sink.fail_on = AnswerBlock
        rig.service.start()
        rig.service.submit(TypedText("один"))
        await settled(rig)
        await closed(rig.service)

        assert audio_log(rig).count("pause") == audio_log(rig).count("resume"), error


def _rebuilt(rig):
    from jarvis.personal_proxy.service.proxy_service import PersonalProxyService

    return PersonalProxyService(
        stages=rig.stages.as_stages(),
        sink=rig.sink,
        speaker=rig.speaker,
        microphone=FakeMicrophone(rig.log),
        locality=rig.locality,
        language=lambda: rig.language,
        settings=rig.settings,
        topics_text="",
        sleep=rig.sleep,
        resume_limit_seconds=0.05,
    )


def test_the_internal_records_of_a_request_hide_its_text():
    from _service_fakes import CHECKED, TOPICS

    from jarvis.personal_proxy.request.request_intake import Heard
    from jarvis.personal_proxy.request.request_pipeline import PipelineParts

    rig = Rig()
    parts = PipelineParts(
        stages=rig.stages.as_stages(),
        reporter=None,
        presenter=None,
        confirm=None,
        locality=rig.locality,
        topics_text=TOPICS,
        dry_run=False,
    )

    shown = repr(Heard(CHECKED, HEARD)) + repr(parts)

    assert HEARD not in shown
    assert TOPICS not in shown


async def test_a_failed_exchange_sends_nothing_and_offers_a_correction():
    rig = asking_rig(sink=RecordingSink([], fail_on=HeardBlock))
    rig.sink.log = rig.log

    rig.service.start()
    rig.service.submit(UTTERANCE)
    await settled(rig)
    await closed(rig.service)

    assert rig.stages.calls["gate"] == []
    assert rig.stages.calls["open_stream"] == []
    (notice,) = rig.sink.of(NoticeBlock)
    assert (notice.kind, notice.detail) == (
        NoticeKind.NOT_SENT,
        ExchangeOutcome.FAILED,
    )


async def test_with_a_muted_tts_the_question_is_still_rendered_from_the_block():
    speaker = FakeSpeaker([], result=SpeechResult.DISABLED)
    rig = asking_rig(speaker=speaker, language="en")
    speaker.log = rig.log
    rig.service.start()
    rig.service.submit(UTTERANCE)
    await until_window_open(rig)

    (heard,) = rig.sink.of(HeardBlock)
    rendered = shown_question("en", heard.heard_text, heard.doubts)
    rig.service.submit(TypedText("yes"))
    await settled(rig)
    await closed(rig.service)

    assert HEARD in rendered
    assert "Марине Крыловой" in rendered
    assert "Send it?" in rendered
    assert len(rig.payloads_sent) == 1
