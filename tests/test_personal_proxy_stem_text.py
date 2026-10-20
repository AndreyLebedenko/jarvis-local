from jarvis.personal_proxy.text import (
    MIN_STEM_LENGTH,
    STEM_ENDING_LENGTH,
    joined_token_spans,
    stem,
    stem_present,
    token_spans,
    tokenize,
)


def test_stem_constants_keep_the_values_the_spike_measured():
    assert MIN_STEM_LENGTH == 3
    assert STEM_ENDING_LENGTH == 2


def test_tokenize_lowercases_folds_yo_and_drops_punctuation():
    assert tokenize("Алёна, Иванова!  Лондон-сити_1") == [
        "алена",
        "иванова",
        "лондон",
        "сити",
        "1",
    ]


def test_tokenize_of_empty_or_punctuation_only_text_is_empty():
    assert tokenize("") == []
    assert tokenize(" ,.- ") == []


def test_token_spans_point_into_the_original_text():
    text = "Ответ: Алёна пришла"

    spans = token_spans(text)

    assert [text[s.start : s.end] for s in spans] == ["Ответ", "Алёна", "пришла"]
    assert [s.token for s in spans] == ["ответ", "алена", "пришла"]


def test_stem_cuts_the_ending_but_keeps_at_least_the_minimum():
    assert stem("анна") == "анн"
    assert stem("ольга") == "оль"
    assert stem("иванов") == "иван"
    assert stem("ян") == "ян"


def test_stem_present_matches_other_declensions_of_a_name():
    forms = ["ольге", "ольгу", "ольгой", "ольга"]
    assert all(stem_present("ольга", [form]) for form in forms)


def test_stem_present_does_not_match_an_unrelated_word():
    assert not stem_present("ольга", ["олег", "школа"])


def test_joined_token_spans_make_a_hyphenated_word_one_token():
    text = "A well-known Алёна-Мария"

    spans = joined_token_spans(text)

    assert [s.token for s in spans] == ["a", "wellknown", "аленамария"]
    assert text[spans[1].start : spans[1].end] == "well-known"
