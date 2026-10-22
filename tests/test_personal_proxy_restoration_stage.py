import logging

import pytest

from jarvis.core.config import GenerationOptions, PersonalProxySettings
from jarvis.personal_proxy.restoration import restore_answer
from jarvis.personal_proxy.restoration_result import (
    RestorationMethod,
    RestoredSentence,
)

SETTINGS = PersonalProxySettings()
MAPPING = {
    "<PERSON_1>": "Марина Крылова",
    "<PERSON_2>": "Игорь Мельников",
    "<PHONE_1>": "8 915 234 56 78",
}
SENTENCE = "Передайте <PERSON_1>, что документы готовы."
RESTORED = "Передайте Марине Крыловой, что документы готовы."
SUBSTITUTED = "Передайте Марина Крылова, что документы готовы."


class FakeBackend:
    def __init__(self, *replies):
        self._replies = list(replies)
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        reply = self._replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


class Deltas:
    def __init__(self, *chunks, error=None):
        self._chunks = list(chunks)
        self._error = error
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._chunks:
            return self._chunks.pop(0)
        if self._error is not None:
            raise self._error
        raise StopAsyncIteration

    async def aclose(self):
        self.closed = True


async def _restore(deltas, backend=None, mapping=MAPPING):
    backend = backend or FakeBackend()
    return [
        sentence
        async for sentence in restore_answer(deltas, mapping, backend, SETTINGS)
    ]


def _texts(sentences):
    return [sentence.text for sentence in sentences]


def _methods(sentences):
    return [sentence.method for sentence in sentences]


async def test_a_sentence_without_a_placeholder_passes_through_with_no_model_call():
    backend = FakeBackend()

    sentences = await _restore(Deltas("Это обычное предложение."), backend)

    assert sentences == [
        RestoredSentence(
            "Это обычное предложение.", RestorationMethod.PASSTHROUGH, False
        )
    ]
    assert backend.requests == []


async def test_a_placeholder_split_across_deltas_is_never_examined_half_formed():
    backend = FakeBackend(RESTORED)

    sentences = await _restore(
        Deltas("Передайте <PER", "SON_1>, что доку", "менты готовы. Конец"), backend
    )

    assert _texts(sentences) == [RESTORED, "Конец"]
    assert _methods(sentences) == [
        RestorationMethod.MODEL,
        RestorationMethod.PASSTHROUGH,
    ]
    assert len(backend.requests) == 1
    assert "<PERSON_1>" in backend.requests[0].prompt


async def test_the_remainder_at_the_end_of_the_stream_is_flushed_as_the_last_sentence():
    sentences = await _restore(Deltas("Первое. Второе без точки"))

    assert _texts(sentences) == ["Первое.", "Второе без точки"]


async def test_several_sentences_keep_their_order_and_are_restored_one_at_a_time():
    backend = FakeBackend(RESTORED, "Ответьте Игорю Мельникову сегодня.")

    sentences = await _restore(
        Deltas(
            f"Вступление. {SENTENCE} Середина. ",
            "Ответьте <PERSON_2> сегодня. Конец.",
        ),
        backend,
    )

    assert _texts(sentences) == [
        "Вступление.",
        RESTORED,
        "Середина.",
        "Ответьте Игорю Мельникову сегодня.",
        "Конец.",
    ]
    assert _methods(sentences) == [
        RestorationMethod.PASSTHROUGH,
        RestorationMethod.MODEL,
        RestorationMethod.PASSTHROUGH,
        RestorationMethod.MODEL,
        RestorationMethod.PASSTHROUGH,
    ]
    assert "Марина Крылова" in backend.requests[0].prompt
    assert "Игорь Мельников" in backend.requests[1].prompt


async def test_a_validated_model_reply_is_the_restored_sentence_stripped():
    sentences = await _restore(Deltas(SENTENCE), FakeBackend(f"  {RESTORED}\n"))

    assert sentences == [RestoredSentence(RESTORED, RestorationMethod.MODEL, False)]


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(SENTENCE, id="placeholder_left"),
        pytest.param(
            "Передайте Анне Лебедевой, что документы готовы.", id="original_missing"
        ),
        pytest.param(
            "Передайте Марине Крыловой, что бумаги готовы.", id="outside_word"
        ),
    ],
)
async def test_a_failed_validation_falls_back_to_substitution(reply):
    backend = FakeBackend(reply)

    sentences = await _restore(Deltas(SENTENCE), backend)

    assert sentences == [
        RestoredSentence(SUBSTITUTED, RestorationMethod.SUBSTITUTED, False)
    ]
    assert len(backend.requests) == 1


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(RuntimeError("model unavailable"), id="backend_error"),
        pytest.param(TimeoutError(), id="timeout"),
        pytest.param("", id="empty"),
        pytest.param("   \n", id="blank"),
        pytest.param(None, id="not_a_string"),
        pytest.param(b"bytes", id="bytes"),
    ],
)
async def test_a_backend_failure_or_unusable_reply_falls_back_without_retry(reply):
    backend = FakeBackend(reply)

    sentences = await _restore(Deltas(SENTENCE), backend)

    assert sentences == [
        RestoredSentence(SUBSTITUTED, RestorationMethod.SUBSTITUTED, False)
    ]
    assert len(backend.requests) == 1


async def test_a_failure_does_not_block_the_next_sentence():
    backend = FakeBackend(RuntimeError("down"), "Ответьте Игорю Мельникову сегодня.")

    sentences = await _restore(
        Deltas(f"{SENTENCE} Ответьте <PERSON_2> сегодня."), backend
    )

    assert _methods(sentences) == [
        RestorationMethod.SUBSTITUTED,
        RestorationMethod.MODEL,
    ]


async def test_a_placeholder_alone_outside_the_mapping_is_unresolved_and_unchanged():
    backend = FakeBackend()

    sentences = await _restore(Deltas("Позвоните <PERSON_9> завтра."), backend)

    assert sentences == [
        RestoredSentence(
            "Позвоните <PERSON_9> завтра.", RestorationMethod.PASSTHROUGH, True
        )
    ]
    assert backend.requests == []


async def test_an_unknown_placeholder_beside_a_known_one_stays_and_is_flagged():
    backend = FakeBackend("Анна Лебедева просила перезвонить <PERSON_9>.")
    mapping = {"<PERSON_1>": "Анна Лебедева"}

    sentences = await _restore(
        Deltas("<PERSON_1> просила перезвонить <PERSON_9>."), backend, mapping
    )

    assert sentences == [
        RestoredSentence(
            "Анна Лебедева просила перезвонить <PERSON_9>.",
            RestorationMethod.MODEL,
            True,
        )
    ]
    assert "<PERSON_9>" not in backend.requests[0].prompt.split("Sentence:")[0]


async def test_the_fallback_keeps_an_unknown_placeholder_and_substitutes_the_rest():
    backend = FakeBackend(RuntimeError("down"))
    mapping = {"<PERSON_1>": "Анна Лебедева"}

    sentences = await _restore(
        Deltas("<PERSON_1> просила перезвонить <PERSON_9>."), backend, mapping
    )

    assert sentences == [
        RestoredSentence(
            "Анна Лебедева просила перезвонить <PERSON_9>.",
            RestorationMethod.SUBSTITUTED,
            True,
        )
    ]


async def test_two_placeholders_in_one_sentence_send_both_entries_and_only_those():
    backend = FakeBackend("Отправьте копию Марине Крыловой и Игорю Мельникову.")

    await _restore(Deltas("Отправьте копию <PERSON_1> и <PERSON_2>."), backend)

    prompt = backend.requests[0].prompt
    assert "Марина Крылова" in prompt
    assert "Игорь Мельников" in prompt
    assert "8 915" not in prompt


async def test_the_mapping_entries_of_other_sentences_are_not_in_the_request():
    backend = FakeBackend(RESTORED, "Позвоните по номеру 8 915 234 56 78.")

    await _restore(Deltas(f"{SENTENCE} Позвоните по номеру <PHONE_1>."), backend)

    assert "8 915" not in backend.requests[0].prompt
    assert "Марина" not in backend.requests[1].prompt


async def test_the_request_is_text_only_with_the_check_temperature():
    backend = FakeBackend(RESTORED)

    await _restore(Deltas(SENTENCE), backend)

    request = backend.requests[0]
    assert request.audio_base64 == ""
    assert request.response_format is None
    assert request.options == GenerationOptions(
        temperature=SETTINGS.check_temperature, num_predict=512
    )


async def test_an_abbreviation_does_not_split_a_placeholder_sentence():
    backend = FakeBackend("Спросите Марину Крылову в г. Москве, т.е. лично.")

    sentences = await _restore(
        Deltas("Спросите <PERSON_1> в г. Москве, т.е. лично."), backend
    )

    assert len(backend.requests) == 1
    assert _methods(sentences) == [RestorationMethod.MODEL]


async def test_a_list_number_does_not_cut_into_the_placeholder_sentence():
    backend = FakeBackend(RESTORED)

    sentences = await _restore(Deltas(f"Шаг 1. {SENTENCE}"), backend)

    assert _texts(sentences) == ["Шаг 1.", RESTORED]
    assert len(backend.requests) == 1


async def test_an_input_error_discards_the_half_built_sentence_and_propagates():
    error = ValueError("answer stream broke")
    backend = FakeBackend(RESTORED)
    emitted = []

    with pytest.raises(ValueError) as raised:
        async for sentence in restore_answer(
            Deltas(f"{SENTENCE} Начало следующего <PERS", error=error),
            MAPPING,
            backend,
            SETTINGS,
        ):
            emitted.append(sentence)

    assert raised.value is error
    assert _texts(emitted) == [RESTORED]
    assert len(backend.requests) == 1


async def test_the_input_is_closed_when_the_consumer_stops_early():
    deltas = Deltas("Первое. Второе. Третье.")

    stage = restore_answer(deltas, MAPPING, FakeBackend(), SETTINGS)
    async for _ in stage:
        break
    await stage.aclose()

    assert deltas.closed


async def test_an_empty_stream_yields_nothing():
    assert await _restore(Deltas()) == []
    assert await _restore(Deltas("  ", "\n")) == []


async def test_nothing_derived_from_the_text_is_logged_or_in_a_failure(caplog):
    caplog.set_level(logging.DEBUG)
    backend = FakeBackend(RuntimeError("Марина Крылова leaked"))

    sentences = await _restore(Deltas(SENTENCE), backend)

    assert caplog.records == []
    assert "Крылов" not in repr(sentences)
