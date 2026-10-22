import unicodedata

import pytest

from jarvis.personal_proxy.confirmation_vocabulary import (
    NO_PHRASES,
    YES_PHRASES,
    AnswerKind,
    classify_answer,
)

ZERO_WIDTH_SPACE = "\u200b"
COMBINING_ACUTE = "\u0301"


def test_yes_and_no_vocabularies_do_not_overlap():
    assert YES_PHRASES.isdisjoint(NO_PHRASES)


@pytest.mark.parametrize("phrase", sorted(YES_PHRASES))
def test_every_yes_phrase_survives_decomposition_and_stays_yes(phrase):
    assert classify_answer(unicodedata.normalize("NFD", phrase)) is AnswerKind.YES


@pytest.mark.parametrize("phrase", sorted(NO_PHRASES))
def test_every_no_phrase_survives_decomposition_and_stays_no(phrase):
    assert classify_answer(unicodedata.normalize("NFD", phrase)) is AnswerKind.NO


@pytest.mark.parametrize("phrase", ["окей", "отправляй", "давай", "не отправляй"])
def test_decomposed_cyrillic_is_composed_before_matching(phrase):
    decomposed = unicodedata.normalize("NFD", phrase)

    assert decomposed != phrase
    assert classify_answer(decomposed) in (AnswerKind.YES, AnswerKind.NO)


@pytest.mark.parametrize(
    "text",
    [
        f"д{ZERO_WIDTH_SPACE}а",
        f"ye{ZERO_WIDTH_SPACE}s",
        f"д{COMBINING_ACUTE}а",
        "s.e.n.d",
        "y-e-s",
        "y\u00ades",
        "d\u2060a",
        "n.o",
    ],
)
def test_a_vocabulary_word_broken_by_a_hidden_or_joining_mark_is_unclear(text):
    assert classify_answer(text) is AnswerKind.UNCLEAR


@pytest.mark.parametrize(
    "text, expected",
    [
        ("да-отправляй", AnswerKind.YES),
        ("да\u200b отправляй", AnswerKind.YES),
        ("send\u200bit", AnswerKind.YES),
        ("send\u00a0it", AnswerKind.YES),
        ("не-отправляй", AnswerKind.NO),
    ],
)
def test_a_mark_between_words_separates_them_like_a_space(text, expected):
    assert classify_answer(text) is expected


@pytest.mark.parametrize(
    "text", ["Да?", "да ?", "yes?", "нет?", "send it?", "да\uff1f"]
)
def test_a_question_mark_makes_any_answer_unclear(text):
    assert classify_answer(text) is AnswerKind.UNCLEAR


@pytest.mark.parametrize("text", ["don't send", "Don\u2019t send", "dont send"])
def test_dont_send_is_no_with_either_apostrophe(text):
    assert classify_answer(text) is AnswerKind.NO


def test_an_apostrophe_inside_another_word_does_not_glue_it():
    assert classify_answer("s'end") is AnswerKind.UNCLEAR


@pytest.mark.parametrize("value", [None, 1, b"yes", ["yes"], 3.5])
def test_a_non_text_answer_is_unclear_not_an_error(value):
    assert classify_answer(value) is AnswerKind.UNCLEAR
