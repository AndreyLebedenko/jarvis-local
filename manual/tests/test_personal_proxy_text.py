from manual.personal_proxy_text import (
    canonical_tokens,
    canonicalize_numbers,
    digit_runs,
    normalize_text,
    stem,
    stem_present,
    tokenize,
    word_error_rate,
)


def test_normalize_folds_case_yo_and_punctuation():
    assert normalize_text("  Ёлка, ЕЛЬ!  ") == "елка ель"


def test_normalize_treats_underscore_as_separator_so_placeholders_split():
    assert tokenize("<PERSON_2>") == ["person", "2"]


def test_phone_read_in_groups_becomes_digit_groups():
    tokens = tokenize(
        "восемь девятьсот пятнадцать двести тридцать четыре пятьдесят шесть "
        "семьдесят восемь"
    )

    assert canonicalize_numbers(tokens) == ["8", "915", "234", "56", "78"]


def test_digit_by_digit_reading_stays_separate_digits():
    assert canonical_tokens("девять один пять два три четыре") == [
        "9",
        "1",
        "5",
        "2",
        "3",
        "4",
    ]


def test_teens_do_not_absorb_following_units():
    assert canonical_tokens("двенадцать пять") == ["12", "5"]


def test_tens_after_tens_start_a_new_number():
    assert canonical_tokens("двадцать двадцать") == ["20", "20"]


def test_number_word_run_is_flushed_at_the_end_of_input():
    assert canonical_tokens("сто восемьдесят") == ["180"]


def test_non_number_words_are_untouched():
    assert canonical_tokens("позвони Марине") == ["позвони", "марине"]


def test_digit_runs_join_consecutive_digit_tokens_across_formatting():
    assert digit_runs("+7 (915) 234-56-78") == ["79152345678"]


def test_digit_runs_are_broken_by_words():
    assert digit_runs("серия сорок пять ноль два номер шесть один") == ["4502", "61"]


def test_digit_runs_do_not_join_placeholder_indexes():
    assert digit_runs("<PHONE_1> <PHONE_2>") == ["1", "2"]


def test_stem_keeps_at_least_three_letters_and_drops_two_endings():
    assert stem("марина") == "мари"
    assert stem("пав") == "пав"
    assert stem("ivan") == "iva"


def test_stem_present_matches_an_inflected_form():
    assert stem_present("марина", ["позвони", "марине"])


def test_stem_present_rejects_an_unrelated_token():
    assert not stem_present("марина", ["позвони", "олегу"])


def test_wer_is_zero_for_identical_text_ignoring_case_and_punctuation():
    assert word_error_rate("Привет, мир!", "привет мир") == 0.0


def test_wer_counts_substitution_over_reference_length():
    assert word_error_rate("раз два три четыре", "раз два пять четыре") == 0.25


def test_wer_counts_missing_words_as_errors():
    assert word_error_rate("раз два три четыре", "") == 1.0


def test_wer_treats_number_words_and_digits_as_equal():
    assert word_error_rate("сто восемьдесят рублей", "180 рублей") == 0.0


def test_wer_of_empty_reference_depends_on_hypothesis():
    assert word_error_rate("", "") == 0.0
    assert word_error_rate("", "лишнее") == 1.0
