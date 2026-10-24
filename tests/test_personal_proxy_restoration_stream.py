import asyncio
import time

import pytest
from _backend_fakes import FakeBackend

from jarvis.core.config import PersonalProxySettings
from jarvis.personal_proxy import restoration
from jarvis.personal_proxy.restoration import restore_answer
from jarvis.personal_proxy.restoration_result import (
    RestorationMethod,
    RestoredSentence,
)

SETTINGS = PersonalProxySettings()
MAPPING = {"<PERSON_1>": "Марина Крылова"}
SENTENCE = "Передайте <PERSON_1>, что документы готовы."
RESTORED = "Передайте Марине Крыловой, что документы готовы."
SUBSTITUTED = "Передайте Марина Крылова, что документы готовы."


class HangingBackend:
    def __init__(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        self.entered.set()
        await self.release.wait()
        return RESTORED


class Deltas:
    def __init__(self, chunks, error=None):
        self._chunks = list(chunks)
        self._error = error
        self.pulled = 0
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._chunks:
            self.pulled += 1
            return self._chunks.pop(0)
        if self._error is not None:
            raise self._error
        raise StopAsyncIteration

    async def aclose(self):
        self.closed = True


async def _collect(deltas, backend=None, mapping=MAPPING):
    backend = backend or FakeBackend()
    return [s async for s in restore_answer(deltas, mapping, backend, SETTINGS)]


async def _let_the_loop_run():
    for _ in range(30):
        await asyncio.sleep(0)


def _other_tasks():
    return [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]


def _first_sentence(deltas, backend):
    return asyncio.ensure_future(
        restore_answer(deltas, MAPPING, backend, SETTINGS).__anext__()
    )


async def test_reading_the_input_does_not_wait_for_the_model():
    deltas = Deltas([f"{SENTENCE} "] * 5)
    backend = HangingBackend()
    first = _first_sentence(deltas, backend)

    await backend.entered.wait()
    await _let_the_loop_run()

    assert deltas.pulled == 5
    backend.release.set()
    await first


async def test_queued_sentences_are_restored_and_yielded_before_the_error():
    error = ValueError("answer stream broke")
    backend = FakeBackend(RESTORED, RESTORED, RESTORED)
    emitted = []

    with pytest.raises(ValueError) as raised:
        async for sentence in restore_answer(
            Deltas([f"{SENTENCE} {SENTENCE} {SENTENCE} Хвост без"], error),
            MAPPING,
            backend,
            SETTINGS,
        ):
            emitted.append(sentence)

    assert raised.value is error
    assert [s.method for s in emitted] == [RestorationMethod.MODEL] * 3
    assert len(backend.requests) == 3


async def test_the_input_read_ahead_is_bounded_by_characters(monkeypatch):
    monkeypatch.setattr(restoration, "MAX_QUEUED_CHARS", 100)
    deltas = Deltas(["Двадцать знаков тут. "] * 200)
    first = _first_sentence(deltas, HangingBackend())

    await _let_the_loop_run()

    assert deltas.pulled < 20
    first.cancel()
    await asyncio.gather(first, return_exceptions=True)


async def test_cancelling_the_consumer_cancels_the_reader_and_closes_the_input():
    deltas = Deltas([f"{SENTENCE} "] * 3)
    backend = HangingBackend()
    consumer = _first_sentence(deltas, backend)
    await backend.entered.wait()

    consumer.cancel()
    await asyncio.gather(consumer, return_exceptions=True)
    await _let_the_loop_run()

    assert deltas.closed
    assert _other_tasks() == []


async def test_leaving_early_and_closing_leaks_no_task():
    deltas = Deltas(["Первое. Второе. Третье. "] * 50)

    stage = restore_answer(deltas, MAPPING, FakeBackend(), SETTINGS)
    async for _ in stage:
        break
    await stage.aclose()
    await _let_the_loop_run()

    assert deltas.closed
    assert _other_tasks() == []


async def test_a_finished_stage_leaks_no_task():
    await _collect(Deltas(["Первое. Второе."]))
    await _let_the_loop_run()

    assert _other_tasks() == []


async def test_a_backend_that_exceeds_the_time_limit_falls_back(monkeypatch):
    monkeypatch.setattr(restoration, "BACKEND_TIMEOUT_SECONDS", 0.05)

    sentences = await _collect(Deltas([SENTENCE]), HangingBackend())

    assert sentences == [
        RestoredSentence(SUBSTITUTED, RestorationMethod.SUBSTITUTED, False)
    ]


def test_the_default_time_limit_is_fifteen_seconds():
    assert restoration.BACKEND_TIMEOUT_SECONDS == 15


async def test_a_cancellation_inside_the_backend_is_not_swallowed():
    backend = FakeBackend(asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await _collect(Deltas([SENTENCE]), backend)


async def test_a_sentence_with_more_than_eight_placeholders_is_only_substituted():
    backend = FakeBackend()
    mapping = {"<PERSON_1>": "Анна"}

    sentences = await _collect(Deltas(["<PERSON_1> " * 9 + "конец."]), backend, mapping)

    assert [s.method for s in sentences] == [RestorationMethod.SUBSTITUTED]
    assert sentences[0].text == "Анна " * 9 + "конец."
    assert backend.requests == []


async def test_a_sentence_over_a_thousand_characters_is_only_substituted():
    backend = FakeBackend()

    sentences = await _collect(Deltas(["слово " * 200 + "<PERSON_1> конец."]), backend)

    assert [s.method for s in sentences] == [RestorationMethod.SUBSTITUTED]
    assert "Марина Крылова" in sentences[0].text
    assert backend.requests == []


async def test_gate_style_placeholders_outside_the_mapping_are_unresolved():
    backend = FakeBackend()

    sentences = await _collect(Deltas(["Позвоните <PERSON_01> и <FOO_1>."]), backend)

    assert sentences == [
        RestoredSentence(
            "Позвоните <PERSON_01> и <FOO_1>.", RestorationMethod.PASSTHROUGH, True
        )
    ]
    assert backend.requests == []


async def test_a_newline_ends_a_sentence_without_punctuation():
    backend = FakeBackend("пункт два Марина Крылова")

    sentences = await _collect(
        Deltas(["пункт один\nпункт два <PERSON_1>\nпункт три"]), backend
    )

    assert [s.text for s in sentences] == [
        "пункт один",
        "пункт два Марина Крылова",
        "пункт три",
    ]


async def test_text_without_punctuation_is_bounded_and_fast():
    text = "а" * 180_000
    pieces = [text[i : i + 50] for i in range(0, len(text), 50)]
    started = time.perf_counter()

    many = await _collect(Deltas(pieces))
    one = await _collect(Deltas([text]))
    elapsed = time.perf_counter() - started

    for sentences in (many, one):
        assert "".join(s.text for s in sentences) == text
        assert {s.method for s in sentences} == {RestorationMethod.PASSTHROUGH}
    assert max(len(s.text) for s in many) <= 4050
    assert elapsed < 2.0


class Fatal(BaseException):
    pass


class FailingDeltas(Deltas):
    def __init__(self, chunks, failure):
        super().__init__(chunks)
        self._failure = failure

    async def __anext__(self):
        if not self._chunks:
            raise self._failure
        return await super().__anext__()


class BlockedDeltas(Deltas):
    def __init__(self, chunks):
        super().__init__(chunks)
        self.blocked = asyncio.Event()

    async def __anext__(self):
        if not self._chunks:
            await self.blocked.wait()
        return await super().__anext__()


async def test_an_input_that_raises_cancelled_error_does_not_hang_the_consumer():
    backend = FakeBackend(RESTORED)
    emitted = []

    with pytest.raises(asyncio.CancelledError):
        async with asyncio.timeout(3):
            async for sentence in restore_answer(
                FailingDeltas([f"{SENTENCE} Хвост"], asyncio.CancelledError()),
                MAPPING,
                backend,
                SETTINGS,
            ):
                emitted.append(sentence)

    assert [s.method for s in emitted] == [RestorationMethod.MODEL]


async def test_an_input_base_exception_propagates_unchanged_after_queued_sentences():
    failure = Fatal()
    emitted = []

    with pytest.raises(Fatal) as raised:
        async with asyncio.timeout(3):
            async for sentence in restore_answer(
                FailingDeltas(["Первое. Второе. Хвост"], failure),
                MAPPING,
                FakeBackend(),
                SETTINGS,
            ):
                emitted.append(sentence)

    assert raised.value is failure
    assert [s.text for s in emitted] == ["Первое.", "Второе."]


async def test_closing_the_stage_leaves_no_reader_task_at_once():
    deltas = BlockedDeltas(["Первое. Второе. "])

    stage = restore_answer(deltas, MAPPING, FakeBackend(), SETTINGS)
    await stage.__anext__()
    await stage.aclose()

    assert deltas.closed
    assert _other_tasks() == []


async def test_cancelling_the_consumer_leaves_no_reader_task_at_once():
    deltas = BlockedDeltas([])
    consumer = _first_sentence(deltas, FakeBackend())
    await _let_the_loop_run()

    consumer.cancel()
    await asyncio.gather(consumer, return_exceptions=True)

    assert deltas.closed
    assert _other_tasks() == []
