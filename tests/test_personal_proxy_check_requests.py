import json

import pytest

from jarvis.personal_proxy.check.check_prompts import ERROR_HINT, JUDGE_SCHEMA, RULES
from jarvis.personal_proxy.check.check_requests import (
    JUDGE_SEED,
    NUM_PREDICT,
    build_judge_request,
    build_sample_request,
)
from jarvis.personal_proxy.check.judge_parsing import JudgeResult, parse_judge
from jarvis.personal_proxy.check.weak_word_marks import mark_weak_words
from jarvis.personal_proxy.stt.stt_result import Word


def _word(text, probability):
    return Word(text, 0.0, 0.1, probability)


def test_only_words_below_the_threshold_are_marked():
    words = [_word("позвони", 0.99), _word("Марине", 0.31), _word("завтра", 0.5)]

    assert mark_weak_words(words, 0.5) == "позвони Марине[?] завтра"


def test_no_words_give_no_marked_text():
    assert mark_weak_words([], 0.5) == ""


def test_the_sample_prompt_carries_the_marked_transcript_and_the_spike_texts():
    request = build_sample_request("позвони Марине[?]", "QVVESU8=", 0.618)

    assert request.prompt.endswith("Transcript:\nпозвони Марине[?]")
    assert ERROR_HINT in request.prompt
    assert RULES in request.prompt
    assert "Words followed by [?] were low-confidence" in request.prompt
    assert "do not assume they are wrong" in request.prompt
    assert "Do not output the [?] marks" in request.prompt


def test_the_sample_carries_the_recording_and_the_configured_temperature():
    request = build_sample_request("text", "QVVESU8=", 0.618)

    assert request.audio_base64 == "QVVESU8="
    assert request.options.as_request_options() == {
        "temperature": 0.618,
        "num_predict": NUM_PREDICT,
    }
    assert request.response_format is None


def test_the_judge_compares_the_engine_text_with_the_sample():
    request = build_judge_request("engine words", "sample words", "QVVESU8=")

    assert request.prompt.endswith("A:\nengine words\n\nB:\nsample words")
    assert request.audio_base64 == "QVVESU8="


def test_the_judge_is_deterministic_and_constrained_to_the_schema():
    request = build_judge_request("a", "b", "QVVESU8=")

    assert request.options.as_request_options() == {
        "temperature": 0.0,
        "seed": JUDGE_SEED,
        "num_predict": NUM_PREDICT,
    }
    assert JUDGE_SEED == 1
    assert request.response_format == JUDGE_SCHEMA


def test_the_request_repr_does_not_show_the_prompt_or_the_recording():
    request = build_judge_request("секретный текст", "секретный текст", "QVVESU8=")

    assert "секретный" not in repr(request)
    assert "QVVESU8=" not in repr(request)


def test_a_valid_judge_answer_is_parsed():
    reply = json.dumps(
        {"uncertain_fragments": ["912 345", "Марине"], "confidence": 0.7}
    )

    assert parse_judge(reply) == JudgeResult(0.7, ("912 345", "Марине"))


def test_an_empty_list_of_doubts_is_valid():
    reply = '{"uncertain_fragments": [], "confidence": 1}'

    assert parse_judge(reply) == JudgeResult(1.0, ())


@pytest.mark.parametrize(
    "reply",
    [
        "",
        "not json",
        "[]",
        '"text"',
        "null",
        '{"confidence": 0.5}',
        '{"uncertain_fragments": []}',
        '{"uncertain_fragments": "a", "confidence": 0.5}',
        '{"uncertain_fragments": [1], "confidence": 0.5}',
        '{"uncertain_fragments": [], "confidence": "high"}',
        '{"uncertain_fragments": [], "confidence": true}',
        '{"uncertain_fragments": [], "confidence": 1.5}',
        '{"uncertain_fragments": [], "confidence": -0.1}',
    ],
)
def test_anything_but_the_expected_structure_is_rejected(reply):
    assert parse_judge(reply) is None


def test_parsing_deeply_nested_text_is_a_rejection_not_a_crash():
    assert parse_judge("[" * 200000) is None
