from language_segments import CharsetLanguageStream, LanguageSegment, segment_by_charset


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
