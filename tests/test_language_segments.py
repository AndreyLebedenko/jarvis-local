import pytest

from jarvis.audio.language_segments import (
    CharsetLanguageStream,
    LanguageSegment,
    segment_by_charset,
    text_language,
)


def collect(*chunks: str) -> list[LanguageSegment]:
    stream = CharsetLanguageStream()
    segments: list[LanguageSegment] = []
    for chunk in chunks:
        segments.extend(stream.feed(chunk))
    segments.extend(stream.close())
    merged_text = "".join(segment.text for segment in segments)
    return segment_by_charset(merged_text)


def test_russian_only_defaults_to_russian():
    assert collect("Привет, мир.") == [LanguageSegment("ru", "Привет, мир.")]


def test_english_only_routes_to_english():
    assert collect("A WebSocket is persistent.") == [
        LanguageSegment("en", "A WebSocket is persistent.")
    ]


def test_mixed_identifier_splits_without_model_markup():
    assert collect("Функция parse_user_id в классе APIClient готова.") == [
        LanguageSegment("ru", "Функция"),
        LanguageSegment("en", "parse_user_id"),
        LanguageSegment("ru", "в классе"),
        LanguageSegment("en", "APIClient"),
        LanguageSegment("ru", "готова."),
    ]


def test_latin_terms_with_digits_and_punctuation_stay_together():
    assert collect("HTTP/2, WebSocket, REST: когда что выбрать?") == [
        LanguageSegment("en", "HTTP/2, WebSocket, REST:"),
        LanguageSegment("ru", "когда что выбрать?"),
    ]


def test_language_switch_survives_token_boundaries():
    assert collect("Функция par", "se_user_id готова.") == [
        LanguageSegment("ru", "Функция"),
        LanguageSegment("en", "parse_user_id"),
        LanguageSegment("ru", "готова."),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Что такое WebSocket?",
        "Объясни docker-compose.yml",
        "PostgreSQL - это СУБД.",
        "Kubernetes использует etcd.",
        "Используйте git rebase --interactive.",
    ],
)
def test_russian_text_heavy_with_english_terms_is_russian(text):
    assert text_language(text) == "ru"


def test_latin_only_text_is_english():
    assert text_language("What is a WebSocket?") == "en"


def test_any_cyrillic_word_makes_the_text_russian():
    """The accepted cost of the Cyrillic-first rule: English prose quoting a
    Russian word reads as Russian. Russian prose with English terms is far
    more common for this assistant."""
    assert text_language("What does слово mean?") == "ru"


@pytest.mark.parametrize(
    "text",
    [
        "Run `git rebase --interactive` first.",
        "Example:\n```\nprint('привет')\n```\nThat prints a greeting.",
    ],
)
def test_code_spans_do_not_decide_the_language(text):
    assert text_language(text) == "en"


def test_text_without_letters_has_no_language():
    assert text_language("2 + 2 = ?") is None
