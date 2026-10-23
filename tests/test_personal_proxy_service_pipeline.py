"""The request flow of PersonalProxyService end to end, with a fake for every
stage and port. Every test names what must reach the network (or must not)."""

import asyncio
import dataclasses
from contextlib import asynccontextmanager

import numpy as np
import pytest
from _confirmation_fakes import FakeMicrophone, FakeSpeaker
from _service_fakes import (
    CHECKED,
    CHECKED_WITH_DOUBT,
    HEARD,
    MAPPING,
    SANITIZED,
    TOPICS,
    TRANSCRIPTION,
    RecordingSink,
    Rig,
    closed,
    make_wav,
    settled,
    until,
)

from jarvis.personal_proxy.check_result import (
    CheckedTranscript,
    CheckSource,
    FallbackReason,
)
from jarvis.personal_proxy.confirmation_blocks import (
    HeardBlock,
    HeardDecision,
    SentBlock,
)
from jarvis.personal_proxy.confirmation_ports import SpeechResult
from jarvis.personal_proxy.confirmation_texts import offer_text
from jarvis.personal_proxy.external_error import (
    ExternalClientError,
    ExternalErrorKind,
)
from jarvis.personal_proxy.findings import Finding, GateCategory, GateResult
from jarvis.personal_proxy.gate_context import GateContext
from jarvis.personal_proxy.payload import DEFAULT_SYSTEM_PROMPT, OutboundPayload
from jarvis.personal_proxy.proxy_inbox import InboxFullError, TypedText, Utterance
from jarvis.personal_proxy.restoration_result import RestorationMethod
from jarvis.personal_proxy.sanitize_result import (
    SanitizeFailure,
    SanitizeFailureClass,
    SanitizeResult,
    SanitizeVerdict,
)
from jarvis.personal_proxy.service_blocks import (
    AnswerBlock,
    AnswerCompleteBlock,
    DryRunBlock,
    NoticeBlock,
    NoticeKind,
    RequestSourceBlock,
)
from jarvis.personal_proxy.service_texts import notice_text
from jarvis.personal_proxy.speech_guard import NoSpeech
from jarvis.personal_proxy.stt_result import Transcription
from jarvis.ui.contract import DataLocality

UTTERANCE = Utterance(make_wav())
FIRST_ANSWER = "Хорошо, передаю Марине Крыловой."
SECOND_ANSWER = "Это займёт минуту."


@asynccontextmanager
async def running(rig):
    rig.service.start()
    try:
        yield rig
    finally:
        await closed(rig.service)


async def request(rig, item):
    async with running(rig):
        rig.service.submit(item)
        await settled(rig)


async def spin(turns=30):
    for _ in range(turns):
        await asyncio.sleep(0)


def audio_log(rig):
    return [entry for entry in rig.log if entry in ("pause", "speak", "resume")]


# --- a complete run ----------------------------------------------------------


async def test_a_voice_request_without_a_doubt_is_sent_and_answered():
    rig = Rig()

    await request(rig, UTTERANCE)

    blocks = rig.sink.blocks
    assert [type(block) for block in blocks] == [
        HeardBlock,
        SentBlock,
        AnswerBlock,
        AnswerBlock,
    ]
    assert blocks[0].decision is HeardDecision.SEND_WITHOUT_QUESTION
    assert blocks[0].heard_text == HEARD
    assert [block.text for block in blocks[2:]] == [FIRST_ANSWER, SECOND_ANSWER]
    assert blocks[2].method is RestorationMethod.SUBSTITUTED
    assert blocks[3].method is RestorationMethod.PASSTHROUGH
    assert rig.spoken_texts == [FIRST_ANSWER, SECOND_ANSWER]
    assert len(rig.payloads_sent) == 1


async def test_the_stages_get_the_clip_the_transcription_and_the_checked_text():
    rig = Rig()

    await request(rig, UTTERANCE)

    (clip,) = rig.stages.calls["transcribe"][0]
    assert clip.dtype == np.float32
    assert clip.ndim == 1
    assert rig.stages.calls["check"][0][0] is TRANSCRIPTION
    assert rig.stages.calls["check"][0][1] is clip
    assert rig.stages.calls["sanitize"][0] == (CHECKED,)


async def test_the_order_is_gate_then_sent_block_then_stream_then_restore():
    rig = Rig()

    await request(rig, UTTERANCE)

    order = [
        entry
        for entry in rig.log
        if entry in ("sanitize", "gate", "post:SentBlock", "open_stream", "restore")
    ]
    assert order == ["sanitize", "gate", "post:SentBlock", "open_stream", "restore"]


async def test_a_typed_request_skips_the_speech_stage_and_the_check():
    rig = Rig()

    await request(rig, TypedText("Привет, как дела?"))

    assert rig.stages.calls["transcribe"] == []
    assert rig.stages.calls["check"] == []
    (typed,) = rig.stages.calls["sanitize"][0]
    assert typed.text == "Привет, как дела?"
    assert typed.source is CheckSource.TYPED
    assert typed.doubts == ()
    assert len(rig.payloads_sent) == 1


# --- the payload invariants --------------------------------------------------


async def test_the_stream_gets_the_very_payload_object_the_gate_allowed():
    rig = Rig()

    await request(rig, UTTERANCE)

    ((gated, context),) = rig.stages.calls["gate"]
    (streamed,) = rig.stages.calls["open_stream"][0]
    assert streamed is gated
    assert type(gated) is OutboundPayload
    assert rig.stages.gate_results[0].allowed
    assert isinstance(context, GateContext)
    assert dict(context.mapping) == MAPPING
    assert context.topics_text == TOPICS


async def test_the_payload_is_the_fixed_system_prompt_and_the_sanitized_text_only():
    rig = Rig()

    await request(rig, UTTERANCE)

    (payload,) = rig.payloads_sent
    assert payload.to_chat_messages() == [
        {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
        {"role": "user", "content": SANITIZED},
    ]
    sent_text = " ".join(m["content"] for m in payload.to_chat_messages())
    assert HEARD not in sent_text
    assert all(original not in sent_text for original in MAPPING.values())


async def test_the_sent_block_equals_the_payload():
    rig = Rig()

    await request(rig, UTTERANCE)

    (payload,) = rig.payloads_sent
    (sent,) = rig.sink.of(SentBlock)
    assert sent.messages == tuple(
        (message.role, message.content) for message in payload.messages
    )


async def test_nothing_is_sent_when_the_sent_block_cannot_be_posted():
    rig = Rig(sink=RecordingSink([], fail_on=SentBlock))

    await request(rig, UTTERANCE)

    assert rig.stages.calls["open_stream"] == []
    assert NoticeKind.INTERNAL_ERROR in rig.sink.notices()


# --- speech and typed input that never go further ---------------------------


async def test_a_clip_without_speech_posts_a_notice_and_sends_nothing():
    rig = Rig()
    rig.stages.transcription = NoSpeech(0.0, 0.3)

    await request(rig, UTTERANCE)

    assert rig.sink.notices() == [NoticeKind.NO_SPEECH]
    assert rig.stages.calls["check"] == []
    assert rig.stages.calls["sanitize"] == []
    assert rig.stages.calls["open_stream"] == []
    assert rig.speaker.spoken == []


@pytest.mark.parametrize("text", ["", "   ", "​\n"])
async def test_an_empty_transcription_is_never_sent(text):
    rig = Rig()
    rig.stages.transcription = Transcription(text, (), ())

    await request(rig, UTTERANCE)

    assert rig.sink.notices() == [NoticeKind.NO_SPEECH]
    assert rig.stages.calls["check"] == []
    assert rig.stages.calls["open_stream"] == []


async def test_an_empty_transcript_verdict_of_the_check_is_never_sent():
    rig = Rig()
    rig.stages.checked = CheckedTranscript(
        "",
        (),
        CheckSource.WHISPER_FALLBACK,
        False,
        FallbackReason.EMPTY_TRANSCRIPT,
    )

    await request(rig, UTTERANCE)

    assert rig.sink.notices() == [NoticeKind.NO_SPEECH]
    assert rig.stages.calls["sanitize"] == []
    assert rig.stages.calls["open_stream"] == []


@pytest.mark.parametrize("text", ["", "  \n ", "​"])
async def test_an_empty_typed_message_is_never_sent(text):
    rig = Rig()

    await request(rig, TypedText(text))

    assert rig.sink.notices() == [NoticeKind.NO_SPEECH]
    assert rig.stages.calls["sanitize"] == []
    assert rig.stages.calls["open_stream"] == []


async def test_an_unreadable_recording_posts_a_notice_and_sends_nothing():
    rig = Rig()

    await request(rig, Utterance(b"not a wav"))

    assert rig.sink.notices() == [NoticeKind.BAD_AUDIO]
    assert rig.stages.calls["transcribe"] == []


# --- the sanitize stage ------------------------------------------------------


async def test_a_topics_refusal_posts_the_reason_and_sends_nothing():
    rig = Rig()
    rig.stages.sanitized = SanitizeResult(
        SanitizeVerdict.REFUSE, "a sensitive topic", "", {}
    )

    await request(rig, UTTERANCE)

    (notice,) = rig.sink.of(NoticeBlock)
    assert notice.kind is NoticeKind.REFUSED
    assert notice.reason == "a sensitive topic"
    assert rig.sink.of(HeardBlock) == []
    assert rig.stages.calls["gate"] == []
    assert rig.stages.calls["open_stream"] == []
    assert all("a sensitive topic" not in text for text in rig.spoken_texts)
    assert rig.spoken_texts


@pytest.mark.parametrize("failure", list(SanitizeFailureClass))
async def test_a_sanitize_failure_posts_its_class_and_sends_nothing(failure):
    rig = Rig()
    rig.stages.sanitized = SanitizeFailure(failure)

    await request(rig, UTTERANCE)

    (notice,) = rig.sink.of(NoticeBlock)
    assert (notice.kind, notice.detail) == (NoticeKind.SANITIZE_FAILED, failure)
    assert rig.stages.calls["gate"] == []
    assert rig.stages.calls["open_stream"] == []


@pytest.mark.parametrize(
    "result",
    [
        None,
        "send it",
        SanitizeResult(SanitizeVerdict.SEND, "", "   ", {}),
        SanitizeResult(SanitizeVerdict.SEND, "", "", {}),
    ],
)
async def test_a_sanitize_result_that_cannot_be_sent_is_a_failure(result):
    rig = Rig()
    rig.stages.sanitized = result

    await request(rig, UTTERANCE)

    assert rig.sink.notices() == [NoticeKind.SANITIZE_FAILED]
    assert rig.stages.calls["open_stream"] == []


# --- the gate ----------------------------------------------------------------


async def test_a_gate_block_posts_categories_and_positions_and_sends_nothing():
    rig = Rig()
    rig.stages.sanitized = SanitizeResult(
        SanitizeVerdict.SEND, "", "Позвони по телефону +7 912 345-67-89 завтра", {}
    )

    await request(rig, UTTERANCE)

    (notice,) = rig.sink.of(NoticeBlock)
    assert notice.kind is NoticeKind.GATE_BLOCKED
    assert GateCategory.PHONE in {finding.category for finding in notice.detail}
    assert rig.sink.of(SentBlock) == []
    assert rig.stages.calls["open_stream"] == []
    shown = notice_text(notice, "en")
    assert "912" not in shown
    assert rig.spoken_texts
    assert all(not any(ch.isdigit() for ch in text) for text in rig.spoken_texts)


async def test_a_mapping_original_in_the_sanitized_text_is_blocked():
    rig = Rig()
    rig.stages.sanitized = SanitizeResult(
        SanitizeVerdict.SEND, "", "Передай Марине Крыловой привет", MAPPING
    )

    await request(rig, UTTERANCE)

    (notice,) = rig.sink.of(NoticeBlock)
    assert notice.kind is NoticeKind.GATE_BLOCKED
    assert rig.stages.calls["open_stream"] == []


async def test_a_topics_text_in_the_sanitized_text_is_blocked():
    rig = Rig()
    rig.stages.sanitized = SanitizeResult(
        SanitizeVerdict.SEND, "", f"Расскажи про {TOPICS} подробно", {}
    )

    await request(rig, UTTERANCE)

    assert rig.sink.notices() == [NoticeKind.GATE_BLOCKED]
    assert rig.stages.calls["open_stream"] == []


@pytest.mark.parametrize("verdict", [None, "allowed", object(), True])
async def test_a_gate_result_that_is_not_a_gate_result_is_a_block(verdict):
    rig = Rig()
    rig.service = _service_with(rig, gate=lambda payload, context: verdict)

    await request(rig, UTTERANCE)

    assert rig.sink.notices() == [NoticeKind.GATE_BLOCKED]
    assert rig.stages.calls["open_stream"] == []


async def test_a_gate_result_with_findings_is_a_block_whatever_else_it_says():
    rig = Rig()
    finding = Finding(GateCategory.EMAIL, 1, 3, 9)
    rig.service = _service_with(rig, gate=lambda p, c: GateResult((finding,)))

    await request(rig, UTTERANCE)

    (notice,) = rig.sink.of(NoticeBlock)
    assert notice.detail == (finding,)
    assert rig.stages.calls["open_stream"] == []


def _service_with(rig, **replacements):
    from jarvis.personal_proxy.proxy_service import PersonalProxyService

    stages = dataclasses.replace(rig.stages.as_stages(), **replacements)
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


async def test_a_dry_run_posts_the_whole_state_and_sends_nothing():
    rig = Rig(dry_run=True)

    await request(rig, UTTERANCE)

    (block,) = rig.sink.of(DryRunBlock)
    assert block.whisper_text == HEARD
    assert block.checked_text == HEARD
    assert block.doubts == ()
    assert block.would_ask is False
    assert block.sanitized_text == SANITIZED
    assert dict(block.mapping) == MAPPING
    assert block.verdict is SanitizeVerdict.SEND
    assert block.gate_findings == ()
    assert block.messages == (("system", DEFAULT_SYSTEM_PROMPT), ("user", SANITIZED))
    assert rig.stages.calls["open_stream"] == []
    assert rig.sink.of(SentBlock) == []
    assert rig.locality.history == []


async def test_a_dry_run_speaks_nothing_and_leaves_the_microphone_alone():
    rig = Rig(dry_run=True, language="en")

    await request(rig, UTTERANCE)

    assert rig.speaker.spoken == []
    assert audio_log(rig) == []


async def test_a_dry_run_posts_the_state_block_only_and_no_heard_block():
    rig = Rig(dry_run=True)

    await request(rig, UTTERANCE)

    assert [type(block) for block in rig.sink.blocks] == [DryRunBlock]


async def test_a_typed_dry_run_has_no_whisper_text():
    rig = Rig(dry_run=True)

    await request(rig, TypedText("Привет"))

    assert rig.sink.of(DryRunBlock)[0].whisper_text is None


async def test_a_dry_run_still_stops_at_a_gate_block():
    rig = Rig(dry_run=True)
    rig.stages.sanitized = SanitizeResult(
        SanitizeVerdict.SEND, "", "Позвони +7 912 345-67-89", {}
    )

    await request(rig, UTTERANCE)

    assert rig.sink.of(DryRunBlock) == []
    assert rig.sink.notices() == [NoticeKind.GATE_BLOCKED]


# --- the answer --------------------------------------------------------------


async def test_the_locality_is_external_around_the_stream_only():
    rig = Rig()

    await request(rig, UTTERANCE)

    assert rig.locality.history == [DataLocality.EXTERNAL, DataLocality.LOCAL]
    (stream,) = rig.stages.streams
    assert set(stream.seen_locality) == {DataLocality.EXTERNAL}
    assert stream.closed
    assert rig.locality.current is DataLocality.LOCAL


async def test_the_locality_is_not_touched_when_nothing_is_sent():
    rig = Rig()
    rig.stages.sanitized = SanitizeFailure(SanitizeFailureClass.NO_JSON)

    await request(rig, UTTERANCE)

    assert rig.locality.history == []


async def test_an_unresolved_placeholder_is_marked_and_shown_as_it_is():
    rig = Rig()
    rig.stages.deltas = ("Привет, <PERSON_9>. ", "Пока.")

    await request(rig, UTTERANCE)

    first, second = rig.sink.of(AnswerBlock)
    assert (first.text, first.unresolved_placeholders) == ("Привет, <PERSON_9>.", True)
    assert first.method is RestorationMethod.PASSTHROUGH
    assert second.unresolved_placeholders is False


async def test_control_tags_are_stripped_from_the_speech_but_not_from_the_chat():
    rig = Rig()
    tagged = '<speak>Привет</speak> <lang xml:lang="en">there</lang>.'
    rig.stages.deltas = (tagged + " ",)

    await request(rig, UTTERANCE)

    assert rig.sink.of(AnswerBlock)[0].text == tagged
    assert rig.spoken_texts == ["Привет there."]


async def test_markdown_in_the_answer_is_spoken_as_written():
    rig = Rig()
    rig.stages.deltas = ("- **один** и `два`. ",)

    await request(rig, UTTERANCE)

    assert rig.spoken_texts == ["- **один** и `два`."]


async def test_the_microphone_is_paused_for_the_whole_answer_speech():
    rig = Rig()

    await request(rig, UTTERANCE)

    assert audio_log(rig) == ["pause", "speak", "speak", "resume"]


async def test_a_muted_tts_gives_text_only_and_the_microphone_back():
    rig = Rig(speaker=FakeSpeaker([], result=SpeechResult.DISABLED))
    rig.speaker.log = rig.log

    await request(rig, UTTERANCE)

    assert len(rig.sink.of(AnswerBlock)) == 2
    assert audio_log(rig) == ["pause", "speak", "resume"]


async def test_a_speaker_failure_leaves_the_text_and_the_microphone_resumed():
    speaker = FakeSpeaker([], error=RuntimeError("tts broke"))
    rig = Rig(speaker=speaker)
    speaker.log = rig.log

    await request(rig, UTTERANCE)

    assert len(rig.sink.of(AnswerBlock)) == 2
    assert NoticeKind.SPEECH_FAILED in rig.sink.notices()
    assert audio_log(rig)[-1] == "resume"


async def test_a_microphone_that_cannot_resume_is_reported():
    microphone = FakeMicrophone([], resume_error=RuntimeError("mic broke"))
    rig = Rig(microphone=microphone)
    microphone.log = rig.log

    await request(rig, UTTERANCE)

    assert NoticeKind.MICROPHONE_FAILED in rig.sink.notices()


async def test_an_error_before_the_stream_opens_posts_a_notice_with_its_kind():
    rig = Rig()
    rig.stages.open_error = ExternalClientError(ExternalErrorKind.KEY_MISSING)

    await request(rig, UTTERANCE)

    (notice,) = rig.sink.of(NoticeBlock)
    assert notice.kind is NoticeKind.ANSWER_INCOMPLETE
    assert notice.detail is ExternalErrorKind.KEY_MISSING
    assert len(rig.sink.of(SentBlock)) == 1
    assert rig.locality.history == []
    assert audio_log(rig).count("pause") == audio_log(rig).count("resume")


async def test_an_error_during_the_stream_keeps_the_shown_sentences():
    rig = Rig()
    rig.stages.deltas = ("Первое предложение. Второе",)
    rig.stages.stream_error = ExternalClientError(ExternalErrorKind.BAD_STREAM)

    await request(rig, UTTERANCE)

    assert [block.text for block in rig.sink.of(AnswerBlock)] == ["Первое предложение."]
    (notice,) = rig.sink.of(NoticeBlock)
    assert (notice.kind, notice.detail) == (
        NoticeKind.ANSWER_INCOMPLETE,
        ExternalErrorKind.BAD_STREAM,
    )
    assert rig.locality.history == [DataLocality.EXTERNAL, DataLocality.LOCAL]
    assert rig.stages.streams[0].closed
    assert audio_log(rig)[0] == "pause"
    assert audio_log(rig).count("resume") == audio_log(rig).count("pause")


async def test_an_unknown_error_during_the_stream_gives_a_content_free_notice():
    rig = Rig()
    rig.stages.stream_error = RuntimeError("SECRET Марина")

    await request(rig, UTTERANCE)

    (notice,) = rig.sink.of(NoticeBlock)
    assert notice == NoticeBlock(NoticeKind.ANSWER_INCOMPLETE)
    assert rig.locality.history == [DataLocality.EXTERNAL, DataLocality.LOCAL]


async def test_a_restoration_error_posts_the_incomplete_notice_and_closes_the_stream():
    rig = Rig()

    def broken(deltas, mapping):
        async def sentences():
            raise RuntimeError("restoration broke")
            yield

        return sentences()

    rig.stages.restore_override = broken

    await request(rig, UTTERANCE)

    assert rig.sink.notices() == [NoticeKind.ANSWER_INCOMPLETE]


# --- failures that are not a stage's verdict ---------------------------------


@pytest.mark.parametrize("stage", ["transcribe", "check", "sanitize"])
async def test_a_stage_exception_posts_a_content_free_notice_and_sends_nothing(stage):
    rig = Rig()
    rig.stages.errors[stage] = RuntimeError("SECRET Марина marina@example.org")

    await request(rig, UTTERANCE)

    (notice,) = rig.sink.of(NoticeBlock)
    assert notice == NoticeBlock(NoticeKind.INTERNAL_ERROR)
    assert rig.stages.calls["open_stream"] == []


async def test_the_worker_survives_an_internal_error():
    rig = Rig()
    rig.stages.errors["sanitize"] = RuntimeError("boom")
    async with running(rig):
        rig.service.submit(UTTERANCE)
        await settled(rig)
        del rig.stages.errors["sanitize"]
        rig.service.submit(UTTERANCE)
        await settled(rig)

    assert len(rig.payloads_sent) == 1
    assert rig.sink.notices() == [NoticeKind.INTERNAL_ERROR]


async def test_a_sink_failure_on_the_heard_block_sends_nothing():
    rig = Rig(sink=RecordingSink([], fail_on=HeardBlock))

    await request(rig, UTTERANCE)

    assert rig.stages.calls["open_stream"] == []


async def test_a_gate_that_raises_sends_nothing():
    rig = Rig()

    def raising(payload, context):
        raise RuntimeError("gate broke")

    rig.service = _service_with(rig, gate=raising)

    await request(rig, UTTERANCE)

    assert rig.sink.notices() == [NoticeKind.INTERNAL_ERROR]
    assert rig.stages.calls["open_stream"] == []


# --- the confirmation --------------------------------------------------------


@asynccontextmanager
async def asking(rig):
    rig.stages.checked = CHECKED_WITH_DOUBT
    async with running(rig):
        rig.service.submit(UTTERANCE)
        await until(
            lambda: rig.sleep.requested.count(rig.settings.confirmation_timeout_seconds)
            >= 1
        )
        yield


async def test_a_doubt_posts_the_heard_block_and_asks_before_anything_is_built():
    rig = Rig()

    async with asking(rig):
        assert rig.stages.calls["gate"] == []
        (heard,) = rig.sink.of(HeardBlock)
        assert heard.decision is HeardDecision.ASK_CONFIRMATION
        assert rig.spoken_texts


@pytest.mark.parametrize("answer", ["да", "Да, отправляй", "yes"])
async def test_a_typed_yes_leads_to_the_send(answer):
    rig = Rig()

    async with asking(rig):
        rig.service.submit(TypedText(answer))
        await settled(rig)

    assert len(rig.payloads_sent) == 1
    assert len(rig.sink.of(HeardBlock)) == 1


async def test_a_spoken_yes_leads_to_the_send():
    rig = Rig()

    async with asking(rig):
        rig.stages.transcription = Transcription("да", (), ())
        rig.service.submit(UTTERANCE)
        await settled(rig)

    assert len(rig.payloads_sent) == 1
    assert len(rig.stages.calls["transcribe"]) == 2
    assert len(rig.stages.calls["sanitize"]) == 1


@pytest.mark.parametrize(
    ("answer", "outcome"),
    [("нет", "declined"), ("может быть", "unclear"), ("да нет", "unclear")],
)
async def test_any_answer_but_a_clear_yes_sends_nothing_and_offers_a_correction(
    answer, outcome
):
    rig = Rig(language="ru")

    async with asking(rig):
        rig.service.submit(TypedText(answer))
        await settled(rig)

    assert rig.stages.calls["gate"] == []
    assert rig.stages.calls["open_stream"] == []
    (notice,) = rig.sink.of(NoticeBlock)
    assert (notice.kind, notice.detail.value) == (NoticeKind.NOT_SENT, outcome)
    assert rig.spoken_texts[-1] == offer_text("ru")
    assert notice_text(notice, "ru") == offer_text("ru")


async def test_a_timeout_sends_nothing_and_offers_a_correction():
    rig = Rig()

    async with asking(rig):
        rig.sleep.release(rig.settings.confirmation_timeout_seconds)
        await settled(rig)

    (notice,) = rig.sink.of(NoticeBlock)
    assert (notice.kind, notice.detail.value) == (NoticeKind.NOT_SENT, "timed_out")
    assert rig.stages.calls["open_stream"] == []


async def test_a_spoken_no_sends_nothing():
    rig = Rig()

    async with asking(rig):
        rig.stages.transcription = Transcription("нет", (), ())
        rig.service.submit(UTTERANCE)
        await settled(rig)

    assert rig.stages.calls["open_stream"] == []
    assert rig.sink.notices() == [NoticeKind.NOT_SENT]


async def test_an_answer_that_holds_no_speech_is_unclear():
    rig = Rig()

    async with asking(rig):
        rig.stages.transcription = NoSpeech(0.0, 0.3)
        rig.service.submit(UTTERANCE)
        await settled(rig)

    assert rig.stages.calls["open_stream"] == []
    assert rig.sink.of(NoticeBlock)[0].detail.value == "unclear"


async def test_a_second_answer_attempt_is_dropped_and_never_becomes_a_request():
    rig = Rig()

    async with asking(rig):
        rig.service.submit(TypedText("да"))
        rig.service.submit(TypedText("Расскажи анекдот"))
        await settled(rig)

    assert len(rig.stages.calls["sanitize"]) == 1
    assert len(rig.payloads_sent) == 1


async def test_a_spoken_item_before_the_window_opens_is_dropped_not_a_request():
    rig = Rig(speaker=FakeSpeaker([], hold=True))
    rig.speaker.log = rig.log
    rig.stages.checked = CHECKED_WITH_DOUBT
    async with running(rig):
        rig.service.submit(UTTERANCE)
        await until(lambda: "speak" in rig.log)
        rig.service.submit(UTTERANCE)
        await spin()
        rig.service.submit(TypedText("да"))
        await settled(rig)

    assert len(rig.stages.calls["transcribe"]) == 1
    assert len(rig.stages.calls["sanitize"]) == 1
    assert len(rig.payloads_sent) == 1


async def test_a_confirmed_request_sends_exactly_the_sanitized_text_of_that_request():
    rig = Rig()

    async with asking(rig):
        rig.service.submit(TypedText("да"))
        await settled(rig)

    (payload,) = rig.payloads_sent
    assert payload.to_chat_messages()[1]["content"] == SANITIZED


# --- one request at a time ---------------------------------------------------


async def test_queued_requests_run_in_order_and_never_overlap_externally():
    rig = Rig()
    rig.stages.stream_gate = asyncio.Event()
    typed = [TypedText(f"вопрос {n}") for n in range(3)]
    async with running(rig):
        for item in typed:
            rig.service.submit(item)
        await until(lambda: len(rig.stages.streams) == 1)
        await spin()
        assert len(rig.stages.streams) == 1
        assert rig.locality.history == [DataLocality.EXTERNAL]
        rig.stages.stream_gate.set()
        await settled(rig)

    assert [args[0].text for args in rig.stages.calls["sanitize"]] == [
        "вопрос 0",
        "вопрос 1",
        "вопрос 2",
    ]
    assert rig.locality.history == [DataLocality.EXTERNAL, DataLocality.LOCAL] * 3


async def test_a_full_queue_drops_the_item_with_a_busy_notice():
    rig = Rig(queue_capacity=1)
    rig.stages.holds["sanitize"] = asyncio.Event()
    async with running(rig):
        rig.service.submit(TypedText("один"))
        await until(lambda: len(rig.stages.calls["sanitize"]) == 1)
        rig.service.submit(TypedText("два"))
        rig.service.submit(TypedText("три"))
        await until(lambda: NoticeKind.BUSY in rig.sink.notices())
        rig.stages.holds["sanitize"].set()
        await settled(rig)

    assert [args[0].text for args in rig.stages.calls["sanitize"]] == ["один", "два"]
    assert rig.sink.notices().count(NoticeKind.BUSY) == 1
    assert len(rig.payloads_sent) == 2


async def test_submit_returns_at_once_and_a_full_inbox_raises_without_content():
    rig = Rig(inbox_capacity=2)

    rig.service.submit(TypedText("один"))
    rig.service.submit(TypedText("два"))
    with pytest.raises(InboxFullError):
        rig.service.submit(TypedText("три"))

    assert rig.stages.calls["sanitize"] == []
    await closed(rig.service)


# --- the warm-up -------------------------------------------------------------


async def test_the_warm_up_runs_once_before_the_first_request():
    rig = Rig()
    async with running(rig):
        rig.service.submit(TypedText("один"))
        await settled(rig)
        rig.service.submit(TypedText("два"))
        await settled(rig)

    assert len(rig.stages.calls["warm_up"]) == 1
    assert rig.log.index("warm_up") < rig.log.index("sanitize")


async def test_an_earlier_explicit_warm_up_is_not_repeated_by_the_first_request():
    rig = Rig()
    await rig.service.warm_up()
    await rig.service.warm_up()

    await request(rig, TypedText("один"))

    assert len(rig.stages.calls["warm_up"]) == 1


async def test_a_failed_warm_up_is_an_internal_error_and_is_tried_again():
    rig = Rig()
    rig.stages.errors["warm_up"] = RuntimeError("no model")
    async with running(rig):
        rig.service.submit(TypedText("один"))
        await settled(rig)
        del rig.stages.errors["warm_up"]
        rig.service.submit(TypedText("два"))
        await settled(rig)

    assert rig.sink.notices() == [NoticeKind.INTERNAL_ERROR]
    assert rig.stages.calls["sanitize"][0][0].text == "два"
    assert len(rig.stages.calls["warm_up"]) == 2


# --- language ----------------------------------------------------------------


@pytest.mark.parametrize(("language", "sentence"), [("ru", "Речь"), ("en", "speech")])
async def test_notices_follow_the_language_provider(language, sentence):
    rig = Rig(language=language)
    rig.stages.transcription = NoSpeech(0.0, 0.3)

    await request(rig, UTTERANCE)

    shown = notice_text(rig.sink.of(NoticeBlock)[0], language)
    assert sentence.casefold() in shown.casefold()


async def test_the_answer_is_spoken_in_the_language_of_the_provider():
    rig = Rig(language="ru")

    await request(rig, UTTERANCE)

    assert {language for _, language in rig.speaker.spoken} == {"ru"}


async def test_the_language_is_read_again_for_every_use():
    rig = Rig(language="ru")
    async with running(rig):
        rig.service.submit(TypedText("один"))
        await settled(rig)
        rig.language = "en"
        rig.service.submit(TypedText("два"))
        await settled(rig)

    languages = [language for _, language in rig.speaker.spoken]
    assert (languages[0], languages[-1]) == ("ru", "en")


# --- the blocks that only the persistence writer needs ----------------------


async def test_a_voice_request_posts_its_recording_and_raw_text_before_confirmation():
    rig = Rig()

    await request(rig, UTTERANCE)

    (source,) = [
        b for b in rig.sink.persistence_blocks if isinstance(b, RequestSourceBlock)
    ]
    assert source.voice_wav == UTTERANCE.wav
    assert source.raw_transcript == HEARD
    assert rig.log.index("sanitize") < rig.log.index("post:HeardBlock")


async def test_a_typed_request_posts_a_source_without_recording_or_raw_text():
    rig = Rig()

    await request(rig, TypedText("Привет, как дела?"))

    (source,) = [
        b for b in rig.sink.persistence_blocks if isinstance(b, RequestSourceBlock)
    ]
    assert (source.voice_wav, source.raw_transcript) == (None, None)


async def test_a_dry_run_posts_no_persistence_block():
    rig = Rig(dry_run=True)

    await request(rig, UTTERANCE)

    assert rig.sink.persistence_blocks == []


async def test_a_full_answer_ends_with_an_answer_complete_block():
    rig = Rig()

    await request(rig, UTTERANCE)

    assert [type(b) for b in rig.sink.persistence_blocks] == [
        RequestSourceBlock,
        AnswerCompleteBlock,
    ]


async def test_an_answer_that_failed_midway_posts_no_answer_complete_block():
    rig = Rig()
    rig.stages.stream_error = ExternalClientError(ExternalErrorKind.TIMEOUT)

    await request(rig, UTTERANCE)

    assert not any(
        isinstance(b, AnswerCompleteBlock) for b in rig.sink.persistence_blocks
    )
    assert NoticeKind.ANSWER_INCOMPLETE in rig.sink.notices()


async def test_a_request_that_is_blocked_posts_no_answer_complete_block():
    rig = Rig()
    rig.stages.sanitized = SanitizeResult(
        SanitizeVerdict.SEND, "", "Позвони на +7 912 345 67 89", {}
    )

    await request(rig, UTTERANCE)

    assert not any(
        isinstance(b, AnswerCompleteBlock) for b in rig.sink.persistence_blocks
    )
