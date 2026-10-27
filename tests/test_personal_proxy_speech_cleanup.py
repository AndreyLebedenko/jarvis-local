import pytest

from jarvis.personal_proxy.answer.speech_cleanup import clean_for_speech

ROMAN_1_TO_30 = [
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
    "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX",
    "XXI", "XXII", "XXIII", "XXIV", "XXV", "XXVI", "XXVII", "XXVIII", "XXIX", "XXX",
]  # fmt: skip

NOMINATIVE_1_TO_30 = [
    "первый", "второй", "третий", "четвёртый", "пятый",
    "шестой", "седьмой", "восьмой", "девятый", "десятый",
    "одиннадцатый", "двенадцатый", "тринадцатый", "четырнадцатый", "пятнадцатый",
    "шестнадцатый", "семнадцатый", "восемнадцатый", "девятнадцатый", "двадцатый",
    "двадцать первый", "двадцать второй", "двадцать третий", "двадцать четвёртый",
    "двадцать пятый", "двадцать шестой", "двадцать седьмой", "двадцать восьмой",
    "двадцать девятый", "тридцатый",
]  # fmt: skip

TWENTIETH = [
    ("XX век", "двадцатый век"),
    ("XX века", "двадцатого века"),
    ("XX веку", "двадцатому веку"),
    ("XX веком", "двадцатым веком"),
    ("XX веке", "двадцатом веке"),
    ("XX веков", "двадцатых веков"),
    ("XX векам", "двадцатым векам"),
    ("XX веками", "двадцатыми веками"),
    ("XX веках", "двадцатых веках"),
]
TWENTY_FIRST = [
    ("XXI век", "двадцать первый век"),
    ("XXI века", "двадцать первого века"),
    ("XXI веку", "двадцать первому веку"),
    ("XXI веком", "двадцать первым веком"),
    ("XXI веке", "двадцать первом веке"),
    ("XXI веков", "двадцать первых веков"),
    ("XXI векам", "двадцать первым векам"),
    ("XXI веками", "двадцать первыми веками"),
    ("XXI веках", "двадцать первых веках"),
]
THIRD = [
    ("III век", "третий век"),
    ("III века", "третьего века"),
    ("III веку", "третьему веку"),
    ("III веком", "третьим веком"),
    ("III веке", "третьем веке"),
    ("III веков", "третьих веков"),
    ("III векам", "третьим векам"),
    ("III веками", "третьими веками"),
    ("III веках", "третьих веках"),
]
TWENTY_THIRD = [
    ("XXIII век", "двадцать третий век"),
    ("XXIII века", "двадцать третьего века"),
    ("XXIII веку", "двадцать третьему веку"),
    ("XXIII веком", "двадцать третьим веком"),
    ("XXIII веке", "двадцать третьем веке"),
]


def sources_of(cases):
    return [source for source, _ in cases]


@pytest.mark.parametrize(("source", "expected"), TWENTIETH, ids=sources_of(TWENTIETH))
def test_xx_takes_the_case_of_the_century_word(source, expected):
    assert clean_for_speech(source) == expected


@pytest.mark.parametrize(
    ("source", "expected"), TWENTY_FIRST, ids=sources_of(TWENTY_FIRST)
)
def test_xxi_takes_the_case_of_the_century_word(source, expected):
    assert clean_for_speech(source) == expected


@pytest.mark.parametrize(("source", "expected"), THIRD, ids=sources_of(THIRD))
def test_iii_uses_the_soft_third_declension(source, expected):
    assert clean_for_speech(source) == expected


@pytest.mark.parametrize(
    ("source", "expected"), TWENTY_THIRD, ids=sources_of(TWENTY_THIRD)
)
def test_compound_twenty_third_inflects_only_the_last_word(source, expected):
    assert clean_for_speech(source) == expected


@pytest.mark.parametrize(
    ("roman", "ordinal"),
    list(zip(ROMAN_1_TO_30, NOMINATIVE_1_TO_30, strict=True)),
)
def test_every_numeral_from_1_to_30_has_its_nominative_ordinal(roman, ordinal):
    assert clean_for_speech(f"{roman} век") == f"{ordinal} век"


def test_xiv_becomes_fourteenth():
    assert clean_for_speech("XIV век") == "четырнадцатый век"


def test_stressed_oy_endings_are_kept_in_nominative():
    assert clean_for_speech("VI век, VII век, VIII век") == (
        "шестой век, седьмой век, восьмой век"
    )


def test_stressed_oy_numerals_take_regular_endings_in_other_cases():
    assert clean_for_speech("в VII веке") == "в седьмом веке"


def test_numeral_in_a_sentence_is_replaced_in_place():
    assert clean_for_speech("Это было в XX веке, а не раньше.") == (
        "Это было в двадцатом веке, а не раньше."
    )


def test_no_break_space_between_numeral_and_century_word_is_accepted():
    assert clean_for_speech("XX век") == "двадцатый век"


def test_only_the_numeral_before_a_century_word_is_replaced():
    assert clean_for_speech("С XIX по XX век") == "С XIX по двадцатый век"


@pytest.mark.parametrize(
    "text",
    [
        "XX",
        "глава XX",
        "Людовик XIV правил долго",
        "I think so",
        "V",
        "X marks the spot",
        "MIX век",
        "CD век",
        "IIII век",
        "VX век",
        "XXXI век",
        "xx век",
        "XX Век",
        "XIX-XX веках",
        "XX веко",
        "XXвек",
    ],
)
def test_text_that_is_not_a_roman_century_is_unchanged(text):
    assert clean_for_speech(text) == text


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("**важно**", "важно"),
        ("__важно__", "важно"),
        ("*важно*", "важно"),
        ("_важно_", "важно"),
        ("это **очень важная фраза** тут", "это очень важная фраза тут"),
        ("это *очень важная фраза* тут", "это очень важная фраза тут"),
        ("это _очень важная фраза_ тут", "это очень важная фраза тут"),
    ],
)
def test_emphasis_markers_are_removed_and_words_kept(source, expected):
    assert clean_for_speech(source) == expected


@pytest.mark.parametrize(
    "text",
    ["snake_case_name", "a_b", "2*3", "2*3*4", "a * b * c", "*", "x * y", "my_var_"],
)
def test_markers_inside_words_and_expressions_are_kept(text):
    assert clean_for_speech(text) == text


def test_lone_asterisk_inside_text_is_kept():
    assert clean_for_speech("Сноска * внизу страницы") == "Сноска * внизу страницы"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("# Заголовок", "Заголовок"),
        ("### Заголовок третьего уровня", "Заголовок третьего уровня"),
        ("###### Шестой", "Шестой"),
    ],
)
def test_heading_markers_at_line_start_are_removed(source, expected):
    assert clean_for_speech(source) == expected


def test_hash_without_following_space_is_kept():
    assert clean_for_speech("#hashtag") == "#hashtag"


def test_hash_inside_a_line_is_kept():
    assert clean_for_speech("номер # 5") == "номер # 5"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("- пункт", "пункт"),
        ("* пункт", "пункт"),
        ("+ пункт", "пункт"),
        ("1. пункт", "пункт"),
        ("12) пункт", "пункт"),
        ("  - вложенный пункт", "вложенный пункт"),
    ],
)
def test_list_markers_at_line_start_are_removed(source, expected):
    assert clean_for_speech(source) == expected


def test_dash_inside_a_line_is_kept():
    assert clean_for_speech("кошка - это животное") == "кошка - это животное"


def test_hyphen_glued_to_a_word_at_line_start_is_kept():
    assert clean_for_speech("-5 градусов") == "-5 градусов"


def test_number_with_dot_inside_a_line_is_kept():
    assert clean_for_speech("версия 1. дальше") == "версия 1. дальше"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("> цитата", "цитата"),
        (">цитата", "цитата"),
        ("> > вложенная цитата", "вложенная цитата"),
    ],
)
def test_block_quote_markers_are_removed(source, expected):
    assert clean_for_speech(source) == expected


def test_greater_than_inside_a_line_is_kept():
    assert clean_for_speech("если a > b, то") == "если a > b, то"


def test_inline_code_backticks_are_removed_and_code_text_kept():
    assert clean_for_speech("вызови `run_task` сейчас") == "вызови run_task сейчас"


def test_unpaired_backtick_is_kept():
    assert clean_for_speech("один ` символ") == "один ` символ"


def test_link_becomes_its_text():
    assert clean_for_speech("см. [документацию](https://example.com/a_b) тут") == (
        "см. документацию тут"
    )


def test_square_brackets_without_link_target_are_kept():
    assert clean_for_speech("массив [1, 2] готов") == "массив [1, 2] готов"


def test_bare_url_is_left_alone():
    assert clean_for_speech("https://example.com/a_b_c") == "https://example.com/a_b_c"


def test_whitespace_runs_are_collapsed_on_touched_line_only():
    source = "- слово   **жирное**   конец\nдругая   строка   без разметки"
    assert (
        clean_for_speech(source) == "слово жирное конец\nдругая   строка   без разметки"
    )


def test_multi_line_input_is_cleaned_line_by_line():
    source = "# Итог\n\n- первое в XX веке\n- второе **важное**\n\nКонец."
    assert (
        clean_for_speech(source)
        == "Итог\n\nпервое в двадцатом веке\nвторое важное\n\nКонец."
    )


def test_line_endings_are_preserved():
    assert clean_for_speech("- a\r\n- b\r\n") == "a\r\nb\r\n"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Просто русский текст без разметки, с запятыми и точками.",
        "Plain English text, nothing to clean. It works!",
        "Смешанный mixed text: 2 + 2 = 4; 10% of 50.",
        "  отступ и   пробелы  сохранены  ",
        "tab\tseparated\tvalues",
        "Привет!\n\n\nТри перевода строки.\n",
    ],
)
def test_plain_text_is_unchanged_byte_for_byte(text):
    assert clean_for_speech(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "# **Заголовок** в XX веке",
        "- *один* и _два_ и `три`",
        "> > 1. [ссылка](http://x.y) XXI века",
        "***тройной*** акцент",
        "**a**b**c**",
        "- - - вложенные маркеры",
        "1. 2. 3. числа",
        "IIII и XX век и snake_case и 2*3",
    ],
)
def test_cleaning_is_idempotent(text):
    once = clean_for_speech(text)
    assert clean_for_speech(once) == once
