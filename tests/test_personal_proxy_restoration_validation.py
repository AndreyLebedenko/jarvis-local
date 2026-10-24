import time

import pytest

from jarvis.personal_proxy.restoration.restoration_validation import (
    MAX_MODEL_PLACEHOLDERS,
    MAX_MODEL_SENTENCE_CHARS,
    RestorationRule,
    failed_rules,
    fits_model_limits,
    restoration_is_valid,
)

PERSON = {"<PERSON_1>": "Марина Крылова"}
SENTENCE = "Передайте <PERSON_1>, что документы готовы."
PHONE = {"<PHONE_1>": "8 915 234 56 78"}
PHONE_SENTENCE = "Позвоните по номеру <PHONE_1> после обеда."


def _accepted(sentence, entries, output):
    assert restoration_is_valid(sentence, entries, output), output
    assert failed_rules(sentence, entries, output) == []


def _rejected(sentence, entries, output):
    assert not restoration_is_valid(sentence, entries, output), output
    assert failed_rules(sentence, entries, output) != []


def test_a_declined_original_with_the_rest_unchanged_is_valid():
    _accepted(SENTENCE, PERSON, "Передайте Марине Крыловой, что документы готовы.")


def test_the_base_form_original_is_valid():
    _accepted(SENTENCE, PERSON, "Передайте Марина Крылова, что документы готовы.")


@pytest.mark.parametrize(
    ("sentence", "entries", "output"),
    [
        (
            "Скажите <PERSON_1>, что <PERSON_2> ушла.",
            {"<PERSON_1>": "Игорь Мельников", "<PERSON_2>": "Анна Лебедева"},
            "Скажите Игорю Мельникову, что Анна Лебедева ушла.",
        ),
        (
            "Скажите Анне, что <PERSON_1> ушла.",
            {"<PERSON_1>": "Анна Лебедева"},
            "Скажите Анне, что Анна Лебедева ушла.",
        ),
        (
            "Банк закрыт, но <ORG_1> работает.",
            {"<ORG_1>": "Банк Москвы"},
            "Банк закрыт, но Банк Москвы работает.",
        ),
        (
            "Курьер был на <ADDRESS_1> утром.",
            {"<ADDRESS_1>": "улица Лесная, дом 12"},
            "Курьер был на улице Лесной, дом 12 утром.",
        ),
        (
            "Встреча с <PERSON_1> на <DATE_1>.",
            {"<PERSON_1>": "Дмитрий Орлов", "<DATE_1>": "23 марта"},
            "Встреча с Дмитрием Орловым на 23 марта.",
        ),
        (
            "Отправьте на адрес <EMAIL_1>.",
            {"<EMAIL_1>": "ivan.petrov@example.com"},
            "Отправьте на адрес ivan.petrov@example.com.",
        ),
    ],
)
def test_a_restoration_in_another_case_is_accepted(sentence, entries, output):
    _accepted(sentence, entries, output)


@pytest.mark.parametrize(
    "output",
    [
        "Передайте <PERSON_1>, что документы готовы.",
        "Передайте, что документы готовы.",
        "Передайте Анне Лебедевой, что документы готовы.",
        "Передайте Марине Крыловой, что бумаги готовы.",
        "Передайте Марине Крыловой, что все документы готовы.",
        "Передайте Марине Крыловой Марине Крыловой, что документы готовы.",
        "Передайте Марине Крыловой Мариновна, что документы готовы.",
        "Марине Крыловой передайте, что документы готовы.",
        "**Передайте Марине Крыловой, что документы готовы.**",
        '"Передайте Марине Крыловой, что документы готовы."',
        "Передайте Марине Крыловой, что документы готовы!",
        "Передайте Марине Крыловой; что документы готовы.",
        "ПЕРЕДАЙТЕ Марине Крыловой, что документы готовы.",
        "передайте Марине Крыловой, что документы готовы.",
        "Передайте Марине Крыловой, что документы готовы",
        "",
        "   ",
    ],
)
def test_a_changed_dropped_or_added_part_is_rejected(output):
    _rejected(SENTENCE, PERSON, output)


def test_digits_and_text_outside_the_values_must_be_exact():
    sentence = "Счёт <PERSON_1> на 100 руб."
    entries = {"<PERSON_1>": "Анна Лебедева"}

    _accepted(sentence, entries, "Счёт Анны Лебедевой на 100 руб.")
    _rejected(sentence, entries, "Счёт Анны Лебедевой на 900 руб.")
    _rejected(sentence, entries, "Счёт Анны Лебедевой на руб.")
    _rejected(sentence, entries, "Счёт Анны Лебедевой на 100 000 руб.")
    _rejected(sentence, entries, "Счет Анны Лебедевой на 100 руб.")


def test_a_value_is_not_duplicated_or_moved():
    sentence = "Скажите <PERSON_1>."
    entries = {"<PERSON_1>": "Марина Крылова"}

    _accepted(sentence, entries, "Скажите Марине Крыловой.")
    _rejected(sentence, entries, "Скажите Марине Крыловой Марине Крыловой.")
    _rejected(sentence, entries, "Марине Крыловой скажите.")


def test_a_short_value_must_match_exactly_and_not_gain_words():
    sentence = "Скажите <PERSON_1> сегодня."
    entries = {"<PERSON_1>": "Ли"}

    _accepted(sentence, entries, "Скажите Ли сегодня.")
    _rejected(sentence, entries, "Скажите Лидии сегодня.")
    _rejected(sentence, {"<PERSON_1>": "Ли"}, "Скажите Ли сегодня Ли.")
    _rejected("Скажите <PERSON_1>.", entries, "Скажите Ли сегодня Ли.")


def test_every_copy_of_a_repeated_placeholder_must_be_restored():
    sentence = "Скажите <PERSON_1>, что <PERSON_1> может не торопиться."
    entries = {"<PERSON_1>": "Павел Сидоров"}

    _accepted(
        sentence,
        entries,
        "Скажите Павлу Сидорову, что Павел Сидоров может не торопиться.",
    )
    _rejected(sentence, entries, "Скажите Павлу Сидорову, что может не торопиться.")
    _rejected(
        sentence,
        entries,
        "Скажите Павлу Сидорову, что <PERSON_1> может не торопиться.",
    )


def test_swapped_values_are_rejected():
    sentence = "Отправьте копию <PERSON_1> и <PERSON_2>."
    entries = {"<PERSON_1>": "Анна Лебедева", "<PERSON_2>": "Игорь Мельников"}

    _accepted(sentence, entries, "Отправьте копию Анне Лебедевой и Игорю Мельникову.")
    _rejected(sentence, entries, "Отправьте копию Игорю Мельникову и Анне Лебедевой.")


def test_a_phone_keeps_its_digits_order_and_separators():
    _accepted(PHONE_SENTENCE, PHONE, "Позвоните по номеру 8 915 234 56 78 после обеда.")
    for wrong in (
        "8 915 234 56 79",
        "78 56 234 915 8",
        "8 915 234 56 78 78 8",
        "8915 234 56 78",
        "8-915-234-56-78",
    ):
        _rejected(PHONE_SENTENCE, PHONE, f"Позвоните по номеру {wrong} после обеда.")


def test_an_email_keeps_its_shape():
    sentence = "Отправьте на <EMAIL_1> сегодня."
    entries = {"<EMAIL_1>": "ivan.petrov@example.com"}

    _accepted(sentence, entries, "Отправьте на ivan.petrov@example.com сегодня.")
    for wrong in (
        "ivan_petrov@example.com",
        "ivan petrov example com",
        "petrov.ivan@example.com",
        "ivan.petrov@example.org",
    ):
        _rejected(sentence, entries, f"Отправьте на {wrong} сегодня.")


def test_a_value_without_word_characters_must_appear_verbatim():
    sentence = "Код <SECRET_1> не сообщать."
    entries = {"<SECRET_1>": "---"}

    _accepted(sentence, entries, "Код --- не сообщать.")
    _rejected(sentence, entries, "Код не сообщать.")
    _rejected(sentence, entries, "Код -- не сообщать.")


def test_an_unknown_placeholder_is_literal_text_and_must_stay():
    entries = {"<PERSON_1>": "Анна Лебедева"}
    sentence = "<PERSON_1> просила перезвонить <PERSON_2>."

    _accepted(sentence, entries, "Анна Лебедева просила перезвонить <PERSON_2>.")
    _rejected(sentence, entries, "Анна Лебедева просила перезвонить.")
    _rejected(sentence, entries, "Анна Лебедева просила перезвонить Игорю.")


def test_adjacent_placeholders_split_by_the_value_shapes():
    sentence = "Звонил <PERSON_1><PERSON_2>"
    entries = {"<PERSON_1>": "Анна", "<PERSON_2>": "Лебедева"}

    _accepted(sentence, entries, "Звонил АннаЛебедева")


def test_the_rules_name_what_failed():
    assert RestorationRule.PLACEHOLDER_LEFT in failed_rules(
        SENTENCE, PERSON, "Передайте <PERSON_1>, что документы готовы."
    )
    assert failed_rules(
        SENTENCE, PERSON, "Передайте Марине Крыловой, что бумаги готовы."
    ) == [RestorationRule.LITERAL_CHANGED]
    assert failed_rules(
        SENTENCE, PERSON, "Передайте Анне Лебедевой, что документы готовы."
    ) == [RestorationRule.BAD_SLOT]


def test_the_model_limits_are_eight_placeholders_and_a_thousand_characters():
    assert (MAX_MODEL_PLACEHOLDERS, MAX_MODEL_SENTENCE_CHARS) == (8, 1000)
    entries = {"<PERSON_1>": "Анна"}

    assert fits_model_limits("<PERSON_1> " * 8, entries)
    assert not fits_model_limits("<PERSON_1> " * 9, entries)
    assert fits_model_limits("а" * 980 + " <PERSON_1>", entries)
    assert not fits_model_limits("а" * 991 + " <PERSON_1>", entries)


def test_an_adversarial_output_is_decided_quickly():
    entries = {f"<PERSON_{n}>": "Анна" for n in range(1, 9)}
    sentence = "".join(f"<PERSON_{n}>" for n in range(1, 9)) + "."
    output = "А" * 1000 + "."

    started = time.perf_counter()
    result = restoration_is_valid(sentence, entries, output)
    elapsed = time.perf_counter() - started

    assert result is False
    assert elapsed < 2.0


def test_an_adversarial_output_with_repeated_literals_is_decided_quickly():
    entries = {f"<PERSON_{n}>": "ааа" for n in range(1, 9)}
    sentence = " а ".join(f"<PERSON_{n}>" for n in range(1, 9)) + " б"
    output = " а ".join(["ааа"] * 7 + ["ааа ааа " + "а " * 400]) + " в"

    started = time.perf_counter()
    result = restoration_is_valid(sentence, entries, output)
    failed_rules(sentence, entries, output)
    elapsed = time.perf_counter() - started

    assert result is False
    assert elapsed < 2.0
