from speech_markup import SpeechSegment, parse_speech_markup


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


def test_code_like_identifiers_are_preserved_as_text():
    assert parse_speech_markup(
        '<lang xml:lang="en">Use get_user_id() in APIClient.</lang>'
    ) == [SpeechSegment("en", "Use get_user_id() in APIClient.")]
