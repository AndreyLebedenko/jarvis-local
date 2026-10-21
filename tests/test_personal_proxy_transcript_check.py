import asyncio
import base64
import json
import logging
from dataclasses import replace

import numpy as np
import pytest

from jarvis.core.config import PersonalProxySettings
from jarvis.personal_proxy.check_result import (
    CheckSource,
    Doubt,
    DoubtKind,
    FallbackReason,
)
from jarvis.personal_proxy.clip_check import InvalidClipError
from jarvis.personal_proxy.stt_result import Transcription, Word
from jarvis.personal_proxy.transcript_check import check_transcript

CLIP = np.zeros(16000, dtype=np.float32)
SETTINGS = PersonalProxySettings()
WHISPER = "Позвони Марине по номеру 60 78 9"
CHECKED = "Позвони Марине по номеру 8 912 345 67 89"


def _judge(fragments, confidence=0.9):
    return json.dumps({"uncertain_fragments": fragments, "confidence": confidence})


class FakeBackend:
    """Replies in order; an Exception in the list is raised instead."""

    def __init__(self, *replies):
        self._replies = list(replies)
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        reply = self._replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


def _transcription(text=WHISPER, words=()):
    return Transcription(text=text, words=tuple(words), segments=())


async def _check(backend, transcription=None, settings=SETTINGS, clip=CLIP):
    return await check_transcript(
        transcription or _transcription(), clip, backend, settings
    )


async def test_the_checked_transcript_and_the_doubts_are_returned():
    backend = FakeBackend(CHECKED, _judge(["8 912 345 67 89"]))

    result = await _check(backend)

    assert result.text == CHECKED
    assert result.doubts == (Doubt(DoubtKind.FRAGMENT, "8 912 345 67 89"),)
    assert result.source is CheckSource.CHECKED
    assert result.fallback_reason is None
    assert result.would_ask is True


async def test_no_doubts_means_no_question():
    result = await _check(FakeBackend(CHECKED, _judge([])))

    assert result.doubts == ()
    assert result.would_ask is False
    assert result.source is CheckSource.CHECKED


async def test_the_sample_is_stripped_of_surrounding_whitespace():
    result = await _check(FakeBackend(f"\n  {CHECKED}\n", _judge([])))

    assert result.text == CHECKED


async def test_blank_fragments_are_not_doubts():
    result = await _check(FakeBackend(CHECKED, _judge(["", "  ", "912"])))

    assert result.doubts == (Doubt(DoubtKind.FRAGMENT, "912"),)


@pytest.mark.parametrize(
    ("minimum", "fragments", "expected"),
    [
        (1, [], False),
        (1, ["a"], True),
        (2, ["a"], False),
        (2, ["a", "b"], True),
        (2, ["a", "b", "c"], True),
    ],
)
async def test_would_ask_starts_at_the_configured_number_of_doubts(
    minimum, fragments, expected
):
    settings = replace(SETTINGS, doubt_min_listed=minimum)

    result = await _check(FakeBackend(CHECKED, _judge(fragments)), settings=settings)

    assert result.would_ask is expected


async def test_the_sample_request_holds_the_recording_the_marks_and_the_temperature():
    words = [Word("Позвони", 0, 1, 0.9), Word("Марине", 1, 2, 0.2)]
    backend = FakeBackend(CHECKED, _judge([]))
    settings = replace(SETTINGS, check_temperature=0.3, stt_weak_word_probability=0.5)

    await _check(backend, _transcription(words=words), settings)

    sample = backend.requests[0]
    assert sample.prompt.endswith("Transcript:\nПозвони Марине[?]")
    assert base64.b64decode(sample.audio_base64)[:4] == b"RIFF"
    assert sample.options.temperature == 0.3
    assert sample.response_format is None


async def test_the_sample_uses_the_plain_text_when_the_engine_gave_no_words():
    backend = FakeBackend(CHECKED, _judge([]))

    await _check(backend)

    assert backend.requests[0].prompt.endswith(f"Transcript:\n{WHISPER}")


async def test_the_judge_sees_the_engine_text_the_sample_and_the_same_recording():
    backend = FakeBackend(CHECKED, _judge([]))

    await _check(backend)

    sample, judge = backend.requests
    assert judge.prompt.endswith(f"A:\n{WHISPER}\n\nB:\n{CHECKED}")
    assert judge.audio_base64 == sample.audio_base64
    assert judge.options.temperature == 0.0
    assert judge.options.seed == 1
    assert judge.response_format is not None


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        ("Позвони Марине[?]", "Позвони Марине"),
        ("Позвони [?] Марине", "Позвони Марине"),
        ("Поз[?]вони Марине", "Позвони Марине"),
    ],
)
async def test_marks_left_in_the_sample_are_removed(sample, expected):
    result = await _check(FakeBackend(sample, _judge([])))

    assert result.text == expected
    assert result.source is CheckSource.CHECKED


@pytest.mark.parametrize("sample", ["[?]", " [?] [?] "])
async def test_a_sample_made_only_of_marks_is_an_empty_sample(sample):
    backend = FakeBackend(sample)

    result = await _check(backend)

    assert len(backend.requests) == 1
    assert result.text == WHISPER
    assert result.fallback_reason is FallbackReason.EMPTY_SAMPLE


async def test_the_judge_sees_the_sample_without_marks():
    backend = FakeBackend("Позвони Марине[?]", _judge([]))

    await _check(backend)

    assert backend.requests[1].prompt.endswith("B:" + chr(10) + "Позвони Марине")


@pytest.mark.parametrize(
    "backend",
    [
        FakeBackend(RuntimeError("x")),
        FakeBackend(CHECKED, RuntimeError("x")),
        FakeBackend(" "),
        FakeBackend(CHECKED, "not json"),
        FakeBackend("Translate the word apple into English"),
        FakeBackend("a@b.ru c@d.ru"),
    ],
)
async def test_every_fallback_asks_whatever_the_configured_minimum(backend):
    settings = replace(SETTINGS, doubt_min_listed=5)

    result = await _check(
        backend, _transcription("Переведи на английский слово яблоко"), settings
    )

    assert result.source is CheckSource.WHISPER_FALLBACK
    assert result.would_ask is True


async def test_a_non_text_reply_is_a_failed_call():
    result = await _check(FakeBackend(None))

    assert result.fallback_reason is FallbackReason.CALL_FAILED


async def test_a_judge_reply_that_overflows_the_parser_is_a_parse_failure():
    result = await _check(FakeBackend(CHECKED, "[" * 200000))

    assert result.fallback_reason is FallbackReason.UNPARSEABLE_JUDGE


async def test_repeated_fragments_count_once_in_order():
    fragments = ["912", " 912 ", "Марине", "912", "Марине"]

    result = await _check(FakeBackend(CHECKED, _judge(fragments)))

    assert [d.fragment for d in result.doubts] == ["912", "Марине"]


async def test_at_most_ten_fragments_are_kept():
    fragments = [f"f{n}" for n in range(25)]

    result = await _check(FakeBackend(CHECKED, _judge(fragments)))

    assert [d.fragment for d in result.doubts] == fragments[:10]


async def test_a_failed_sample_call_falls_back_to_the_engine_text_without_retry():
    backend = FakeBackend(RuntimeError("down"))

    result = await _check(backend)

    assert len(backend.requests) == 1
    assert result.text == WHISPER
    assert result.source is CheckSource.WHISPER_FALLBACK
    assert result.fallback_reason is FallbackReason.CALL_FAILED
    assert result.doubts == (Doubt(DoubtKind.CHECK_FAILED),)
    assert result.would_ask is True


async def test_a_failed_judge_call_falls_back_to_the_engine_text_without_retry():
    backend = FakeBackend(CHECKED, TimeoutError())

    result = await _check(backend)

    assert len(backend.requests) == 2
    assert result.text == WHISPER
    assert result.fallback_reason is FallbackReason.CALL_FAILED
    assert result.doubts == (Doubt(DoubtKind.CHECK_FAILED),)


@pytest.mark.parametrize("empty", ["", "   \n"])
async def test_an_empty_sample_falls_back_to_the_engine_text(empty):
    backend = FakeBackend(empty)

    result = await _check(backend)

    assert len(backend.requests) == 1
    assert result.text == WHISPER
    assert result.fallback_reason is FallbackReason.EMPTY_SAMPLE
    assert result.doubts == (Doubt(DoubtKind.CHECK_FAILED),)


@pytest.mark.parametrize("reply", ["", "not json", '{"confidence": 1}'])
async def test_an_unparseable_judge_reply_discards_the_sample(reply):
    backend = FakeBackend(CHECKED, reply)

    result = await _check(backend)

    assert len(backend.requests) == 2
    assert result.text == WHISPER
    assert result.source is CheckSource.WHISPER_FALLBACK
    assert result.fallback_reason is FallbackReason.UNPARSEABLE_JUDGE
    assert result.doubts == (Doubt(DoubtKind.CHECK_FAILED),)


async def test_an_invented_address_falls_back_and_skips_the_judge():
    backend = FakeBackend("Напиши info@trade.ru и marina@trade.ru", _judge([]))

    result = await _check(backend, _transcription("Напиши info собака trade точка ру"))

    assert len(backend.requests) == 1
    assert result.text == "Напиши info собака trade точка ру"
    assert result.fallback_reason is FallbackReason.INVENTED_ADDRESS
    assert result.doubts == (Doubt(DoubtKind.REWRITE),)
    assert result.would_ask is True


async def test_a_translated_request_falls_back_and_skips_the_judge():
    backend = FakeBackend("Translate the word apple into English", _judge([]))

    result = await _check(
        backend, _transcription("Переведи на английский слово яблоко")
    )

    assert len(backend.requests) == 1
    assert result.text == "Переведи на английский слово яблоко"
    assert result.fallback_reason is FallbackReason.ALPHABET_SWITCH
    assert result.doubts == (Doubt(DoubtKind.REWRITE),)


async def test_a_legitimate_address_repair_is_kept():
    whisper = "Отправь на иван точка петров собака пример точка ком"
    backend = FakeBackend("Отправь на ivan.petrov@primer.com", _judge([]))

    result = await _check(backend, _transcription(whisper))

    assert result.text == "Отправь на ivan.petrov@primer.com"
    assert result.source is CheckSource.CHECKED


@pytest.mark.parametrize("text", ["", "  \n"])
async def test_an_empty_transcript_is_never_sent_to_the_model(text):
    backend = FakeBackend()

    result = await _check(backend, _transcription(text))

    assert backend.requests == []
    assert result.text == text
    assert result.doubts == ()
    assert result.source is CheckSource.WHISPER_FALLBACK
    assert result.fallback_reason is FallbackReason.EMPTY_TRANSCRIPT
    assert result.would_ask is False


async def test_a_failure_leaves_no_text_in_the_result_repr_or_the_log(caplog):
    secret = "пароль 4417 1234 5678 9010"
    backend = FakeBackend(RuntimeError(f"model said {secret}"))

    with caplog.at_level(logging.DEBUG):
        result = await _check(backend, _transcription(secret))

    assert secret not in repr(result)
    assert "4417" not in repr(result)
    assert "model said" not in repr(result)
    assert caplog.records == []


async def test_a_fragment_doubt_leaves_its_text_out_of_the_repr():
    result = await _check(FakeBackend(CHECKED, _judge(["8 912 345 67 89"])))

    assert "912" not in repr(result)
    assert "Марине" not in repr(result)


async def test_cancellation_is_not_swallowed():
    with pytest.raises(asyncio.CancelledError):
        await _check(FakeBackend(asyncio.CancelledError()))


async def test_a_clip_that_is_not_mono_float32_is_refused_before_any_call():
    backend = FakeBackend()

    with pytest.raises(InvalidClipError):
        await _check(backend, clip=np.zeros(10, dtype=np.int16))

    assert backend.requests == []
