import time

import pytest

from jarvis.audio.speech_emphasis import normalize_emphasis, strip_emphasis


def test_one_marker_in_a_question_is_kept():
    assert normalize_emphasis("Вы уже отправили нам *договор*?") == (
        "Вы уже отправили нам *договор*?"
    )


def test_one_marker_in_a_statement_is_kept():
    assert normalize_emphasis("Курьер *привёз* заказ.") == "Курьер *привёз* заказ."


def test_two_markers_in_a_question_are_kept():
    text = "Твой брат всё ещё *живёт* в *Лондоне*?"

    assert normalize_emphasis(text) == text


def test_second_marker_in_a_statement_becomes_a_plain_word():
    assert normalize_emphasis("Курьер *привёз* *заказ* вчера.") == (
        "Курьер *привёз* заказ вчера."
    )


def test_three_markers_in_a_question_leave_the_first_and_the_last():
    assert normalize_emphasis("*Курьер* *привёз* заказ *вечером*?") == (
        "*Курьер* привёз заказ *вечером*?"
    )


@pytest.mark.parametrize("ending", ["?!", "!?", "?..", "?…"])
def test_question_followed_by_more_punctuation_is_still_a_question(ending):
    text = f"Ты *правда* пришёл *сам*{ending}"

    assert normalize_emphasis(text) == text


@pytest.mark.parametrize("closing", ['"', "»", "”", ")"])
def test_question_followed_by_a_closing_quote_or_bracket_is_still_a_question(closing):
    text = f"Он спросил: *кто* *пришёл*?{closing}"

    assert normalize_emphasis(text) == text


def test_stray_asterisk_after_the_question_mark_does_not_hide_the_question():
    assert normalize_emphasis("Ты *правда* *пришёл*?*") == "Ты *правда* *пришёл*?"


def test_marker_that_swallows_the_question_mark_still_makes_a_question():
    text = "Ты *правда* *пришёл?*"

    assert normalize_emphasis(text) == text


@pytest.mark.parametrize(
    "closing", ["“", "’", "}"], ids=["curly-double", "curly-single", "brace"]
)
def test_other_closing_quotes_and_brackets_after_a_question_mark_keep_the_question(
    closing,
):
    text = f"Он спросил: *кто* *пришёл*?{closing}"

    assert normalize_emphasis(text) == text


@pytest.mark.parametrize("trailing", [" ", "\n", " \r\n"])
def test_whitespace_after_the_question_mark_keeps_the_question(trailing):
    text = f"Ты *правда* *пришёл*?{trailing}"

    assert normalize_emphasis(text) == text


def test_question_mark_in_the_middle_does_not_make_a_statement_a_question():
    assert normalize_emphasis("Что? *Да* *нет*.") == "Что? *Да* нет."


def test_four_markers_in_a_question_leave_the_first_and_the_last():
    assert normalize_emphasis("*а* *б* *в* *г*?") == "*а* б в *г*?"


def test_three_markers_in_a_statement_leave_only_the_first():
    assert normalize_emphasis("*а* *б* *в*.") == "*а* б в."


@pytest.mark.parametrize(
    "text", ["*слово*, потом.", "Он (*слово*) пришёл.", 'Он "*слово*" пришёл.']
)
def test_punctuation_next_to_a_marker_does_not_stop_it_being_a_marker(text):
    assert normalize_emphasis(text) == text


def test_asterisk_glued_to_a_word_before_it_does_not_open_a_marker():
    assert normalize_emphasis("Смотри a*b* тут.") == "Смотри ab тут."


def test_asterisk_glued_to_a_word_after_it_does_not_close_a_marker():
    assert normalize_emphasis("Смотри *b*c тут.") == "Смотри bc тут."


def test_long_run_of_question_marks_is_checked_in_linear_time():
    started = time.perf_counter()

    normalize_emphasis("?" * 20_000 + "x")

    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Тест *—* тире.", "Тест — тире."),
        ("*?* *да*?", "? *да*?"),
        ("Это *_* тоже.", "Это _ тоже."),
    ],
    ids=["dash", "question-mark", "underscore"],
)
def test_marker_without_a_letter_or_digit_is_not_a_marker(text, expected):
    assert normalize_emphasis(text) == expected


def test_marker_with_a_letter_and_punctuation_is_still_a_marker():
    assert normalize_emphasis("*слово.* два.") == "*слово.* два."


def test_marker_made_of_a_digit_is_a_marker():
    assert normalize_emphasis("Он купил *3* билета.") == "Он купил *3* билета."


def test_exclamation_is_a_statement():
    assert normalize_emphasis("*Вы* *пришли*!") == "*Вы* пришли!"


def test_markdown_bold_loses_its_asterisks_and_keeps_the_words():
    assert normalize_emphasis("Это **важно** понимать.") == "Это важно понимать."


def test_marker_around_several_words_loses_its_asterisks_and_keeps_the_words():
    assert normalize_emphasis("Он *прислал нам* билеты?") == "Он прислал нам билеты?"


def test_unpaired_asterisk_is_removed():
    assert normalize_emphasis("*Организаторы прислали билеты?") == (
        "Организаторы прислали билеты?"
    )


def test_asterisks_inside_a_word_are_removed_and_do_not_form_a_marker():
    assert normalize_emphasis("Смотри a*b*c тут.") == "Смотри abc тут."


def test_markdown_bold_next_to_a_kept_marker_loses_only_its_own_asterisks():
    assert normalize_emphasis("Он **слово** и *точно* пришёл.") == (
        "Он слово и *точно* пришёл."
    )


def test_unit_without_asterisks_is_returned_identical():
    text = "Просто обычная фраза, без всего."

    assert normalize_emphasis(text) == text


def test_empty_unit_stays_empty():
    assert normalize_emphasis("") == ""


def test_marker_survives_digits_hyphens_and_yo():
    text = "Это *всё-таки* *ёлка-2*?"

    assert normalize_emphasis(text) == text


def test_strip_removes_markers_and_stray_asterisks_and_keeps_the_words():
    text = "*Твой* брат **всё** ещё *живёт в* *Лондоне*?*"

    assert strip_emphasis(text) == "Твой брат всё ещё живёт в Лондоне?"


def test_strip_returns_text_without_asterisks_identical():
    text = "Обычная фраза."

    assert strip_emphasis(text) == text
