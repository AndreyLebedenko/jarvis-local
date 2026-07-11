import logging

from jarvis.audio.speech_markup import (
    SpeechMarkupStream,
    SpeechSegment,
    parse_speech_markup,
    speech_markup_to_text,
)


def test_plain_text_defaults_to_russian_segment():
    assert parse_speech_markup("Привет.") == [SpeechSegment("ru", "Привет.")]


def test_optional_speak_wrapper_is_accepted():
    assert parse_speech_markup("<speak>Привет.</speak>") == [
        SpeechSegment("ru", "Привет.")
    ]


def test_russian_lang_tag_creates_russian_segment():
    assert parse_speech_markup('<lang xml:lang="ru">Привет.</lang>') == [
        SpeechSegment("ru", "Привет.")
    ]


def test_english_lang_tag_creates_english_segment():
    assert parse_speech_markup('<lang xml:lang="en">Hello.</lang>') == [
        SpeechSegment("en", "Hello.")
    ]


def test_mixed_language_markup_returns_ordered_segments():
    assert parse_speech_markup(
        '<speak><lang xml:lang="ru">Скажи </lang>'
        '<lang xml:lang="en">hello world</lang>'
        '<lang xml:lang="ru"> сейчас.</lang></speak>'
    ) == [
        SpeechSegment("ru", "Скажи"),
        SpeechSegment("en", "hello world"),
        SpeechSegment("ru", "сейчас."),
    ]


def test_region_variants_normalize_to_base_language():
    assert parse_speech_markup(
        '<lang xml:lang="ru-RU">Привет.</lang><lang xml:lang="en_US">Hello.</lang>'
    ) == [
        SpeechSegment("ru", "Привет."),
        SpeechSegment("en", "Hello."),
    ]


def test_text_outside_lang_tags_is_preserved_as_default_language():
    assert parse_speech_markup(
        'До <lang xml:lang="en">hello</lang> после.'
    ) == [
        SpeechSegment("ru", "До"),
        SpeechSegment("en", "hello"),
        SpeechSegment("ru", "после."),
    ]


def test_adjacent_same_language_segments_are_merged():
    assert parse_speech_markup(
        '<lang xml:lang="ru">Один.</lang><lang xml:lang="ru">Два.</lang>'
    ) == [SpeechSegment("ru", "Один. Два.")]


def test_punctuation_only_segment_attaches_to_previous_segment():
    assert parse_speech_markup(
        '<lang xml:lang="en">Hello</lang><lang xml:lang="ru">, </lang>'
        '<lang xml:lang="en">world.</lang>'
    ) == [
        SpeechSegment("en", "Hello,"),
        SpeechSegment("en", "world."),
    ]


def test_leading_punctuation_segment_attaches_to_next_segment():
    assert parse_speech_markup(
        '<lang xml:lang="ru">...</lang><lang xml:lang="en">wait</lang>'
    ) == [SpeechSegment("en", "...wait")]


def test_unsupported_language_falls_back_to_default_language_without_spoken_tags():
    assert parse_speech_markup('<lang xml:lang="de">Guten Tag.</lang>') == [
        SpeechSegment("ru", "Guten Tag.")
    ]


def test_malformed_markup_strips_known_control_text():
    assert parse_speech_markup('<speak><lang xml:lang="en"Hello</lang> tail') == [
        SpeechSegment("ru", "Hello tail")
    ]


def test_speech_markup_to_text_returns_clean_speakable_text():
    assert (
        speech_markup_to_text(
            '<speak><lang xml:lang="ru">Открой </lang>'
            '<lang xml:lang="en">APIClient</lang>'
            '<lang xml:lang="ru">.</lang></speak>'
        )
        == "Открой APIClient."
    )


def test_malformed_markup_logs_warning(caplog):
    with caplog.at_level(logging.WARNING):
        parse_speech_markup('<lang xml:lang="en"Hello')

    assert "Ignoring malformed speech markup control fragment" in caplog.text


def test_unsupported_language_logs_warning(caplog):
    with caplog.at_level(logging.WARNING):
        parse_speech_markup('<lang xml:lang="de">Guten Tag.</lang>')

    assert "Unsupported speech markup language" in caplog.text


def test_code_like_identifiers_are_preserved_as_text():
    assert parse_speech_markup(
        '<lang xml:lang="en">Use get_user_id() in APIClient.</lang>'
    ) == [SpeechSegment("en", "Use get_user_id() in APIClient.")]


def test_unknown_tag_like_text_is_preserved_not_swallowed_as_markup():
    """Only the four known control tokens are markup; an assistant answer
    about code must not lose "<String>" or "<div>" to a markup parser
    (whitespace around the preserved token may be normalized)."""
    assert parse_speech_markup("Используй List<String> здесь.") == [
        SpeechSegment("ru", "Используй List <String> здесь.")
    ]


def test_comparison_operator_is_not_treated_as_markup():
    assert parse_speech_markup("a < b и c") == [SpeechSegment("ru", "a < b и c")]


def test_stream_feed_routes_language_across_a_tag_split_between_chunks():
    stream = SpeechMarkupStream()
    pieces = stream.feed("Привет <lang xml:l")
    pieces += stream.feed('ang="en">hello</lang> пока')
    pieces += stream.close()

    assert [
        (piece.language, piece.text.strip())
        for piece in pieces
        if piece.text.strip()
    ] == [("ru", "Привет"), ("en", "hello"), ("ru", "пока")]
