import pytest

from jarvis.personal_proxy.confirmation_vocabulary import (
    NO_PHRASES,
    YES_PHRASES,
    AnswerKind,
    classify_answer,
)

YES_SPOKEN = (
    "да",
    "да отправляй",
    "отправляй",
    "отправь",
    "давай",
    "ок",
    "окей",
    "верно",
    "подтверждаю",
    "yes",
    "send",
    "send it",
    "ok",
    "okay",
    "confirm",
)
NO_SPOKEN = (
    "нет",
    "не надо",
    "не отправляй",
    "стоп",
    "отмена",
    "no",
    "stop",
    "cancel",
    "dont send",
)


def test_the_yes_vocabulary_is_exactly_the_agreed_phrases():
    assert set(YES_PHRASES) == set(YES_SPOKEN)


def test_the_no_vocabulary_is_exactly_the_agreed_phrases():
    assert set(NO_PHRASES) == set(NO_SPOKEN)


@pytest.mark.parametrize("phrase", YES_SPOKEN)
def test_every_yes_phrase_is_yes(phrase):
    assert classify_answer(phrase) is AnswerKind.YES


@pytest.mark.parametrize("phrase", NO_SPOKEN)
def test_every_no_phrase_is_no(phrase):
    assert classify_answer(phrase) is AnswerKind.NO


@pytest.mark.parametrize(
    "text",
    [
        "да нет",
        "да но",
        "нет да",
        "да но исправь",
        "да, но исправь",
        "да, отправляй пожалуйста",
        "yes please",
        "no no",
        "",
        "   ",
        "...",
        "погода сегодня хорошая",
        "не отправляй да",
    ],
)
def test_anything_outside_the_vocabulary_is_unclear(text):
    assert classify_answer(text) is AnswerKind.UNCLEAR


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Да!", AnswerKind.YES),
        ("  ДА.  ", AnswerKind.YES),
        ("Да,   отправляй!", AnswerKind.YES),
        ("Send   IT.", AnswerKind.YES),
        ("Не отправляй.", AnswerKind.NO),
        ("СТОП!", AnswerKind.NO),
        ("Don't send", AnswerKind.NO),
        ("dont send", AnswerKind.NO),
    ],
)
def test_case_punctuation_and_spacing_do_not_matter(text, expected):
    assert classify_answer(text) is expected


def test_yo_is_read_as_ye():
    assert classify_answer("вёрно") is AnswerKind.YES
