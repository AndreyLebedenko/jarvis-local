"""The /force command through PersonalProxyService end to end, with a fake for
every stage and port. A forced request skips the local model stages and keeps
the deterministic gate; every other request goes the normal way."""

import dataclasses
import logging
from contextlib import asynccontextmanager

import pytest
from _service_fakes import (
    CHECKED_WITH_DOUBT,
    SANITIZED,
    TOPICS,
    Rig,
    closed,
    make_wav,
    settled,
    until,
)

from jarvis.personal_proxy.check.check_result import CheckedTranscript, CheckSource
from jarvis.personal_proxy.common.findings import GateCategory
from jarvis.personal_proxy.common.payload import DEFAULT_SYSTEM_PROMPT
from jarvis.personal_proxy.confirmation.confirmation_blocks import (
    HeardBlock,
    HeardDecision,
    SentBlock,
)
from jarvis.personal_proxy.reporting.service_blocks import (
    AnswerBlock,
    AnswerCompleteBlock,
    DryRunBlock,
    NoticeBlock,
    NoticeKind,
    RequestSourceBlock,
)
from jarvis.personal_proxy.reporting.service_texts import notice_text
from jarvis.personal_proxy.request.proxy_inbox import TypedText, Utterance
from jarvis.personal_proxy.restoration.restoration_result import RestorationMethod
from jarvis.personal_proxy.sanitize.sanitize_result import (
    SanitizeFailure,
    SanitizeFailureClass,
    SanitizeResult,
    SanitizeVerdict,
)
from jarvis.personal_proxy.stt.stt_result import Transcription

UTTERANCE = Utterance(make_wav())
HARMLESS = "What is a relay?"
WITH_NAME = "Tell Marina Krylova that the documents are ready"
LOCAL_STAGES = ("transcribe", "check", "sanitize")


@asynccontextmanager
async def running(rig):
    rig.service.start()
    try:
        yield rig
    finally:
        await closed(rig.service)


async def request(rig, *items):
    async with running(rig):
        for item in items:
            rig.service.submit(item)
        await settled(rig)


def local_stage_calls(rig):
    return {name: rig.stages.calls[name] for name in LOCAL_STAGES}


def no_local_stage_was_called(rig):
    return all(calls == [] for calls in local_stage_calls(rig).values())


# --- a forced request skips the local model stages ---------------------------


@pytest.mark.parametrize("command", ["/force", "/f"])
async def test_a_forced_request_sends_the_system_prompt_and_the_verbatim_text(command):
    rig = Rig()

    await request(rig, TypedText(f"{command}   {WITH_NAME}  "))

    (payload,) = rig.payloads_sent
    assert payload.to_chat_messages() == [
        {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
        {"role": "user", "content": WITH_NAME},
    ]


async def test_a_forced_request_calls_no_local_model_stage():
    rig = Rig()

    await request(rig, TypedText(f"/force {WITH_NAME}"))

    assert no_local_stage_was_called(rig)


async def test_a_forced_request_ignores_a_sanitize_stage_that_would_refuse_or_fail():
    for refusing in (
        SanitizeResult(SanitizeVerdict.REFUSE, "a sensitive topic", "", {}),
        SanitizeFailure(SanitizeFailureClass.BAD_PLACEHOLDER),
    ):
        rig = Rig()
        rig.stages.sanitized = refusing

        await request(rig, TypedText(f"/force {HARMLESS}"))

        assert len(rig.payloads_sent) == 1
        assert rig.sink.notices() == []


@pytest.fixture
def typed_text_that_would_ask(monkeypatch):
    def doubtful(text):
        return CheckedTranscript(text, (), CheckSource.TYPED, True)

    monkeypatch.setattr(
        "jarvis.personal_proxy.request.request_intake.typed_checked_transcript",
        doubtful,
    )


async def test_the_control_a_normal_request_that_would_ask_does_ask(
    typed_text_that_would_ask,
):
    rig = Rig()
    async with running(rig):
        rig.service.submit(TypedText(HARMLESS))
        await until(
            lambda: rig.sleep.requested.count(rig.settings.confirmation_timeout_seconds)
            >= 1
        )

    assert rig.payloads_sent == []


async def test_a_forced_request_never_starts_the_confirmation_exchange(
    typed_text_that_would_ask,
):
    rig = Rig()

    await request(rig, TypedText(f"/force {WITH_NAME}"))

    assert rig.sleep.requested == []
    (heard,) = rig.sink.of(HeardBlock)
    assert heard.decision is HeardDecision.SEND_WITHOUT_QUESTION
    assert len(rig.payloads_sent) == 1


async def test_a_forced_request_posts_the_heard_block_without_a_question():
    rig = Rig()

    await request(rig, TypedText(f"/force {WITH_NAME}"))

    (heard,) = rig.sink.of(HeardBlock)
    assert heard.heard_text == WITH_NAME
    assert heard.decision is HeardDecision.SEND_WITHOUT_QUESTION
    assert heard.doubts == ()
    (source,) = [
        block
        for block in rig.sink.persistence_blocks
        if isinstance(block, RequestSourceBlock)
    ]
    assert (source.voice_wav, source.raw_transcript) == (None, None)


async def test_the_order_is_heard_then_gate_then_sent_then_stream():
    rig = Rig()

    await request(rig, TypedText(f"/force {HARMLESS}"))

    order = [
        entry
        for entry in rig.log
        if entry in ("post:HeardBlock", "gate", "post:SentBlock", "open_stream")
    ]
    assert order == ["post:HeardBlock", "gate", "post:SentBlock", "open_stream"]


# --- the gate stays ----------------------------------------------------------


async def test_the_gate_gets_an_empty_mapping_and_the_topics_text():
    rig = Rig()

    await request(rig, TypedText(f"/force {WITH_NAME}"))

    ((gated, context),) = rig.stages.calls["gate"]
    (streamed,) = rig.stages.calls["open_stream"][0]
    assert streamed is gated
    assert dict(context.mapping) == {}
    assert context.topics_text == TOPICS


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("Call me on +7 912 345-67-89 tomorrow", GateCategory.PHONE),
        ("My card is 4111 1111 1111 1111 ok", GateCategory.PAYMENT_CARD),
        ("Write to marina@example.org please", GateCategory.EMAIL),
    ],
)
async def test_the_gate_still_blocks_a_structured_identifier_in_a_forced_request(
    text, category
):
    rig = Rig()

    await request(rig, TypedText(f"/force {text}"))

    (notice,) = rig.sink.of(NoticeBlock)
    assert notice.kind is NoticeKind.GATE_BLOCKED
    assert category in {finding.category for finding in notice.detail}
    assert rig.stages.calls["open_stream"] == []
    assert rig.sink.of(SentBlock) == []
    assert rig.locality.history == []
    shown = notice_text(notice, "en")
    assert all(value not in shown for value in ("912", "4111", "marina"))


async def test_the_gate_still_blocks_a_topic_phrase_in_a_forced_request():
    rig = Rig()

    await request(rig, TypedText(f"/force Расскажи про {TOPICS} подробнее"))

    (notice,) = rig.sink.of(NoticeBlock)
    assert notice.kind is NoticeKind.GATE_BLOCKED
    assert GateCategory.TOPIC_TEXT in {finding.category for finding in notice.detail}
    assert rig.stages.calls["open_stream"] == []


async def test_a_gate_that_raises_stops_a_forced_request():
    rig = Rig()

    def raising(payload, context):
        raise RuntimeError("gate broke")

    rig.service = _service_over(
        rig, dataclasses.replace(rig.stages.as_stages(), gate=raising)
    )

    await request(rig, TypedText(f"/force {HARMLESS}"))

    assert rig.stages.calls["open_stream"] == []
    assert rig.sink.notices() == [NoticeKind.INTERNAL_ERROR]


def _service_over(rig, stages):
    from jarvis.personal_proxy.service.proxy_service import PersonalProxyService

    return PersonalProxyService(
        stages=stages,
        sink=rig.sink,
        speaker=rig.speaker,
        microphone=rig.microphone,
        locality=rig.locality,
        language=lambda: rig.language,
        settings=rig.settings,
        topics_text=TOPICS,
        sleep=rig.sleep,
        resume_limit_seconds=0.05,
    )


# --- dry run -----------------------------------------------------------------


async def test_a_forced_request_in_dry_run_is_not_sent_and_posts_the_state():
    rig = Rig(dry_run=True)

    await request(rig, TypedText(f"/force {WITH_NAME}"))

    (block,) = rig.sink.of(DryRunBlock)
    assert block.forced is True
    assert block.checked_text == WITH_NAME
    assert block.sanitized_text == WITH_NAME
    assert dict(block.mapping) == {}
    assert block.messages == (("system", DEFAULT_SYSTEM_PROMPT), ("user", WITH_NAME))
    assert rig.stages.calls["open_stream"] == []
    assert rig.sink.of(SentBlock) == []
    assert no_local_stage_was_called(rig)
    assert rig.locality.history == []


async def test_a_forced_request_in_dry_run_posts_nothing_else_and_nothing_to_persist():
    rig = Rig(dry_run=True)

    await request(rig, TypedText(f"/force {HARMLESS}"))

    assert [type(block) for block in rig.sink.blocks] == [DryRunBlock]
    assert rig.sink.persistence_blocks == []
    assert rig.speaker.spoken == []


async def test_a_forced_request_in_dry_run_still_stops_at_the_gate():
    rig = Rig(dry_run=True)

    await request(rig, TypedText("/force Call +7 912 345-67-89"))

    assert rig.sink.of(DryRunBlock) == []
    assert rig.sink.notices() == [NoticeKind.GATE_BLOCKED]


# --- the marker --------------------------------------------------------------


async def test_the_sent_block_of_a_forced_request_is_marked():
    rig = Rig()

    await request(rig, TypedText(f"/force {HARMLESS}"))

    (sent,) = rig.sink.of(SentBlock)
    assert sent.forced is True
    assert sent.messages == (("system", DEFAULT_SYSTEM_PROMPT), ("user", HARMLESS))


async def test_a_request_that_is_not_forced_has_an_unmarked_sent_block():
    rig = Rig()

    await request(rig, TypedText(HARMLESS))

    (sent,) = rig.sink.of(SentBlock)
    assert sent.forced is False


# --- the answer --------------------------------------------------------------


async def test_the_answer_of_a_forced_request_is_presented_as_usual():
    rig = Rig()
    rig.stages.deltas = ("A relay passes ", "a signal on. ", "It is simple.")

    await request(rig, TypedText(f"/force {HARMLESS}"))

    answers = rig.sink.of(AnswerBlock)
    assert [block.text for block in answers] == [
        "A relay passes a signal on.",
        "It is simple.",
    ]
    assert {block.method for block in answers} == {RestorationMethod.PASSTHROUGH}
    assert rig.spoken_texts == [block.text for block in answers]
    assert any(isinstance(b, AnswerCompleteBlock) for b in rig.sink.persistence_blocks)
    assert "restore" in rig.log


# --- one message, once, typed text only --------------------------------------


async def test_the_request_after_a_forced_one_goes_the_normal_way():
    rig = Rig()

    await request(rig, TypedText(f"/force {WITH_NAME}"), TypedText(HARMLESS))

    assert [block.forced for block in rig.sink.of(SentBlock)] == [True, False]
    assert len(rig.stages.calls["sanitize"]) == 1
    assert rig.stages.calls["sanitize"][0][0].text == HARMLESS
    payloads = [p.to_chat_messages()[1]["content"] for p in rig.payloads_sent]
    assert payloads == [WITH_NAME, SANITIZED]


async def test_a_spoken_request_is_never_forced_even_when_it_says_the_command():
    rig = Rig()
    rig.stages.checked = CheckedTranscript(
        "/force what is a relay", (), CheckSource.CHECKED, False
    )
    rig.stages.transcription = Transcription("/force what is a relay", (), ())

    await request(rig, UTTERANCE)

    assert len(rig.stages.calls["sanitize"]) == 1
    assert rig.stages.calls["sanitize"][0][0].text == "/force what is a relay"
    (sent,) = rig.sink.of(SentBlock)
    assert sent.forced is False
    (payload,) = rig.payloads_sent
    assert payload.to_chat_messages()[1]["content"] == SANITIZED


async def test_a_spoken_request_in_dry_run_is_never_forced_either():
    rig = Rig(dry_run=True)
    rig.stages.checked = CheckedTranscript("/f hi", (), CheckSource.CHECKED, False)

    await request(rig, UTTERANCE)

    (block,) = rig.sink.of(DryRunBlock)
    assert block.forced is False
    assert len(rig.stages.calls["sanitize"]) == 1


async def test_a_typed_answer_to_a_pending_question_is_never_a_forced_request():
    rig = Rig()
    rig.stages.checked = CHECKED_WITH_DOUBT
    async with running(rig):
        rig.service.submit(UTTERANCE)
        await until(
            lambda: rig.sleep.requested.count(rig.settings.confirmation_timeout_seconds)
            >= 1
        )
        rig.service.submit(TypedText("/force yes"))
        await settled(rig)

    assert rig.payloads_sent == []
    assert rig.sink.of(SentBlock) == []
    assert [n.kind for n in rig.sink.of(NoticeBlock)] == [NoticeKind.NOT_SENT]


# --- a command that sends nothing --------------------------------------------


@pytest.mark.parametrize("typed", ["/forse hello", "/FORCE hello", "/help", "/forcex"])
async def test_an_unknown_command_posts_a_fixed_notice_and_sends_nothing(typed):
    rig = Rig()

    await request(rig, TypedText(typed))

    assert rig.sink.blocks == [NoticeBlock(NoticeKind.UNKNOWN_COMMAND)]
    assert rig.sink.persistence_blocks == []
    assert no_local_stage_was_called(rig)
    assert rig.stages.calls["open_stream"] == []
    assert rig.speaker.spoken == []


@pytest.mark.parametrize(
    "typed", ["/force", "/f", "/force    ", "  /f \n", "/force ​", "/f ​​"]
)
async def test_a_command_without_text_posts_a_fixed_notice_and_sends_nothing(typed):
    rig = Rig()

    await request(rig, TypedText(typed))

    assert rig.sink.blocks == [NoticeBlock(NoticeKind.EMPTY_COMMAND)]
    assert rig.sink.persistence_blocks == []
    assert no_local_stage_was_called(rig)
    assert rig.stages.calls["open_stream"] == []


@pytest.mark.parametrize(
    "typed", ["/etc/hosts is a file", "/", "what is /force", "force hello"]
)
async def test_other_text_with_a_slash_or_the_word_force_is_an_ordinary_request(typed):
    rig = Rig()

    await request(rig, TypedText(typed))

    assert rig.stages.calls["sanitize"][0][0].text == typed
    (sent,) = rig.sink.of(SentBlock)
    assert sent.forced is False


async def test_a_command_notice_in_dry_run_is_still_posted():
    rig = Rig(dry_run=True)

    await request(rig, TypedText("/forse hello"))

    assert rig.sink.blocks == [NoticeBlock(NoticeKind.UNKNOWN_COMMAND)]


# --- no text in logs or exceptions -------------------------------------------


@pytest.mark.parametrize(
    "typed",
    [
        "/force " + WITH_NAME,
        "/force Call +7 912 345-67-89 Marina Krylova",
        "/forse " + WITH_NAME,
    ],
)
@pytest.mark.parametrize("dry_run", [False, True])
async def test_no_text_of_a_forced_or_refused_command_reaches_the_log(
    typed, dry_run, caplog
):
    rig = Rig(dry_run=dry_run)
    caplog.set_level(logging.DEBUG)

    await request(rig, TypedText(typed))

    logged = caplog.text + " ".join(str(r.exc_info) for r in caplog.records)
    for word in ("Marina", "Krylova", "912", "documents"):
        assert word not in logged


async def test_a_forced_request_text_is_not_in_the_repr_of_what_the_service_holds():
    rig = Rig()

    await request(rig, TypedText(f"/force {WITH_NAME}"))

    assert "Marina" not in repr(rig.service)
    assert "Marina" not in repr(rig.sink.of(SentBlock)[0])
    assert "Marina" not in repr(rig.sink.of(HeardBlock)[0])
