"""The Text+Voice mode of the personal proxy: the answer is shown as it arrives,
and spoken only after the whole answer and the local pass; a failed pass falls
back to the cleaned sentences."""

import asyncio
import dataclasses
from contextlib import asynccontextmanager

import pytest
from _service_fakes import Rig, closed, make_wav, settled, until

from jarvis.core.config import GenerationOptions
from jarvis.personal_proxy.answer.spoken_derivative import SpokenDerivativeRenderer
from jarvis.personal_proxy.check.check_backend import ChatRequest
from jarvis.personal_proxy.reporting.journal_writer import ProxyJournalWriter
from jarvis.personal_proxy.reporting.service_blocks import (
    AnswerBlock,
    AnswerCompleteBlock,
    NoticeKind,
    answer_block_of,
)
from jarvis.personal_proxy.request.proxy_inbox import Utterance
from jarvis.personal_proxy.restoration.restoration_result import (
    RestorationMethod,
    RestoredSentence,
)
from jarvis.personal_proxy.service.proxy_service import PersonalProxyService

UTTERANCE = Utterance(make_wav())
CANVAS_DELTAS = ("**Армия** потеряла 130 тыс. ", "Это было до зимы. ")
CANVAS_SENTENCES = ["**Армия** потеряла 130 тыс.", "Это было до зимы."]
CLEANED_SENTENCES = ["Армия потеряла 130 тысяч.", "Это было до зимы."]
SPOKEN = "Армия потеряла сто тридцать тысяч человек. Это было до зимы."


def _service(rig, mode, render):
    stages = dataclasses.replace(rig.stages.as_stages(), render_spoken=render)
    return PersonalProxyService(
        stages=stages,
        sink=rig.sink,
        speaker=rig.speaker,
        microphone=rig.microphone,
        locality=rig.locality,
        language=lambda: rig.language,
        settings=rig.settings,
        topics_text="",
        sleep=rig.sleep,
        resume_limit_seconds=0.05,
        response_mode=lambda: mode,
    )


@asynccontextmanager
async def running(rig):
    rig.service.start()
    try:
        yield rig
    finally:
        await closed(rig.service)


async def ask(rig, mode, render):
    rig.stages.deltas = CANVAS_DELTAS
    rig.service = _service(rig, mode, render)
    async with running(rig):
        rig.service.submit(UTTERANCE)
        await settled(rig)


def _derivatives(rig):
    return [
        block.spoken_derivative
        for block in rig.sink.persistence_blocks
        if isinstance(block, AnswerCompleteBlock)
    ]


async def test_the_spoken_version_is_spoken_and_the_canvas_is_shown():
    rig = Rig()

    async def render(canvas):
        return SPOKEN

    await ask(rig, "text_voice", render)

    assert [b.text for b in rig.sink.of(AnswerBlock)] == CANVAS_SENTENCES
    assert rig.spoken_texts == [
        "Армия потеряла сто тридцать тысяч человек.",
        "Это было до зимы.",
    ]


async def test_the_whole_answer_goes_to_the_local_pass_once():
    rig = Rig()
    canvases = []

    async def render(canvas):
        canvases.append(canvas)
        return SPOKEN

    await ask(rig, "text_voice", render)

    assert canvases == [" ".join(CANVAS_SENTENCES)]


async def test_nothing_is_spoken_before_the_pass_ends_and_the_microphone_is_paused():
    rig = Rig()
    seen = {}

    async def render(canvas):
        seen["spoken_so_far"] = list(rig.spoken_texts)
        seen["log"] = list(rig.log)
        return SPOKEN

    await ask(rig, "text_voice", render)

    assert seen["spoken_so_far"] == []
    assert "pause" in seen["log"]
    assert "speak" not in seen["log"]


async def test_the_spoken_version_is_cleaned_like_the_voice_mode_cleans():
    rig = Rig()

    async def render(canvas):
        return "**Армия** потеряла 130 тыс. человек."

    await ask(rig, "text_voice", render)

    assert rig.spoken_texts == ["Армия потеряла 130 тысяч человек."]


async def test_the_answer_is_closed_after_the_pass_with_the_spoken_version():
    rig = Rig()

    async def render(canvas):
        return SPOKEN

    await ask(rig, "text_voice", render)

    assert _derivatives(rig) == [SPOKEN]


@pytest.mark.parametrize(
    "outcome", [RuntimeError("backend"), TimeoutError(), "", "  \n", "<speak></speak>"]
)
async def test_a_failed_or_empty_pass_speaks_the_cleaned_sentences(outcome):
    rig = Rig()

    async def render(canvas):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    await ask(rig, "text_voice", render)

    assert rig.spoken_texts == CLEANED_SENTENCES
    assert _derivatives(rig) == [None]


async def test_without_a_render_stage_the_cleaned_sentences_are_spoken():
    rig = Rig()

    await ask(rig, "text_voice", None)

    assert rig.spoken_texts == CLEANED_SENTENCES
    assert _derivatives(rig) == [None]


async def test_an_interrupt_during_the_pass_speaks_nothing_and_closes_the_answer():
    rig = Rig()
    started = asyncio.Event()

    async def render(canvas):
        started.set()
        await asyncio.Event().wait()

    rig.stages.deltas = CANVAS_DELTAS
    rig.service = _service(rig, "text_voice", render)
    async with running(rig):
        rig.service.submit(UTTERANCE)
        await until(started.is_set)
        rig.service.interrupt()
        await settled(rig)

    assert rig.spoken_texts == []
    assert _derivatives(rig) == [None]
    assert rig.log.count("resume") == 1


async def test_a_failed_stream_skips_the_pass_and_speaks_the_shown_sentences():
    rig = Rig()
    calls = []

    async def render(canvas):
        calls.append(canvas)
        return SPOKEN

    original = rig.stages.restore

    def failing_restore(deltas, mapping):
        async def run():
            async for sentence in original(deltas, mapping):
                yield sentence
                raise RuntimeError("stream broke")

        return run()

    rig.stages.restore = failing_restore
    await ask(rig, "text_voice", render)

    assert calls == []
    assert NoticeKind.ANSWER_INCOMPLETE in rig.sink.notices()
    assert rig.spoken_texts[0] == CLEANED_SENTENCES[0]


@pytest.mark.parametrize("mode", ["text", "voice"])
async def test_the_other_modes_never_call_the_local_pass(mode):
    rig = Rig()
    calls = []

    async def render(canvas):
        calls.append(canvas)
        return SPOKEN

    await ask(rig, mode, render)

    assert calls == []
    assert _derivatives(rig) == [None]


class RecordingBackend:
    def __init__(self, reply="Пересказ.", delay=0.0):
        self.requests: list[ChatRequest] = []
        self._reply = reply
        self._delay = delay

    async def complete(self, request):
        self.requests.append(request)
        await asyncio.sleep(self._delay)
        return self._reply


async def test_the_renderer_sends_the_contract_as_system_and_the_answer_as_user():
    backend = RecordingBackend()
    renderer = SpokenDerivativeRenderer(backend, "CONTRACT", GenerationOptions(), 5)

    spoken = await renderer.render("ответ")

    [request] = backend.requests
    assert spoken == "Пересказ."
    assert (request.system, request.prompt, request.audio_base64) == (
        "CONTRACT",
        "ответ",
        "",
    )


async def test_the_renderer_fails_with_a_timeout_when_the_pass_runs_over():
    renderer = SpokenDerivativeRenderer(
        RecordingBackend(delay=1), "CONTRACT", GenerationOptions(), 0.01
    )

    with pytest.raises(TimeoutError):
        await renderer.render("ответ")


class _Recorder:
    def __init__(self):
        self.answers = []

    async def record_proxy_answer(self, text, **fields):
        self.answers.append((text, fields))

    def end_session(self):
        pass


class _Chat:
    async def post(self, block):
        pass


async def test_the_writer_stores_the_spoken_version_on_the_complete_answer():
    recorder = _Recorder()
    writer = ProxyJournalWriter(_Chat(), recorder, dry_run=False)

    await writer.post(
        answer_block_of(
            RestoredSentence("Ответ.", RestorationMethod.PASSTHROUGH, False)
        )
    )
    await writer.post(AnswerCompleteBlock("Пересказ."))

    [(text, fields)] = recorder.answers
    assert (text, fields["spoken_derivative"], fields["incomplete"]) == (
        "Ответ.",
        "Пересказ.",
        False,
    )
