import pytest

from jarvis.personal_proxy.common.normalize import normalize_message
from jarvis.personal_proxy.common.spans import Span


@pytest.mark.parametrize(
    ("original", "expected"),
    [
        ("a\u00a0b\u2009c\u202fd\te", "a b c d e"),
        ("a\r\nb\u2028c\x85d", "a\nb\nc\nd"),
        ("1\u20132\u20143\u22124\u20115", "1-2-3-4-5"),
        ("\uff14\uff15\uff20\uff1a", "45@:"),
        ("Ле\u00adбе\ufeffдева", "Лебедева"),
        ("a  \t b", "a b"),
        ("a \r\n  b", "a\nb"),
        ("4539 \u2013 1488", "4539 - 1488"),
    ],
)
def test_normalization_unifies_spaces_dashes_width_and_drops_invisibles(
    original, expected
):
    assert normalize_message(original).text == expected


def test_a_zero_width_space_between_digits_or_letters_vanishes_by_default():
    assert normalize_message("8915\u200b2345678").text == "89152345678"
    assert normalize_message("мой\u200bд").text == "мойд"
    assert normalize_message("a\u2060b").text == "ab"


def test_a_zero_width_space_between_letters_can_read_as_a_word_boundary():
    spaced = normalize_message("мой\u200bдиагноз", zero_width_as_space=True)

    assert spaced.text == "мой диагноз"
    assert normalize_message("a\u2060b", zero_width_as_space=True).text == "a b"


def test_a_zero_width_space_next_to_a_digit_or_space_still_vanishes_as_space_reading():
    assert normalize_message("12\u200b34", zero_width_as_space=True).text == "1234"
    assert normalize_message("a \u200bb", zero_width_as_space=True).text == "a b"


def test_decomposed_letters_are_composed():
    decomposed = "е\u0308лка и\u0306"

    assert normalize_message(decomposed).text == "ёлка й"


def test_a_composed_letter_maps_back_over_all_its_original_characters():
    original = "x е\u0308 y"
    normalized = normalize_message(original)
    start = normalized.text.index("ё")

    mapped = normalized.original_span(Span(start, start + 1))

    assert original[mapped.start : mapped.end] == "е\u0308"


def test_a_span_of_the_normalized_text_maps_back_to_the_original_text():
    original = "ID \u200b12\u00a034\u2013 end"
    normalized = normalize_message(original)
    start = normalized.text.index("12")
    span = Span(start, start + len("12 34"))

    mapped = normalized.original_span(span)

    assert original[mapped.start : mapped.end] == "12\u00a034"


def test_a_collapsed_whitespace_run_maps_back_to_the_whole_run():
    original = "a  \r\n  b"
    normalized = normalize_message(original)

    mapped = normalized.original_span(Span(1, 2))

    assert original[mapped.start : mapped.end] == "  \r\n  "


def test_plain_text_is_unchanged_and_maps_to_itself():
    normalized = normalize_message("plain text")

    assert normalized.text == "plain text"
    assert normalized.original_span(Span(2, 5)) == Span(2, 5)
