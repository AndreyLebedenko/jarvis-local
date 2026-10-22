import pytest

from jarvis.personal_proxy import restoration_validation
from jarvis.personal_proxy.restoration_validation import (
    failed_rules,
    restoration_is_valid,
)


def _valid(original, restored, template="Скажите <PERSON_1> сегодня."):
    sentence_start, sentence_end = template.split("<PERSON_1>")
    return restoration_is_valid(
        template,
        {"<PERSON_1>": original},
        f"{sentence_start}{restored}{sentence_end}",
    )


@pytest.mark.parametrize(
    ("original", "restored"),
    [
        ("Марина Крылова", "Марине Крыловой"),
        ("Игорь Мельников", "Игорю Мельникову"),
        ("Дмитрий Орлов", "Дмитрию Орлову"),
        ("Анна Лебедева", "Анны Лебедевой"),
        ("Павел Сидоров", "Павлу Сидорову"),
        ("Северный Ветер", "Северном Ветре"),
        ("улица Лесная, дом 12", "улице Лесной, дом 12"),
        ("Олег Сергеевич Жуков", "Олегу Сергеевичу Жукову"),
    ],
)
def test_a_declined_cyrillic_value_is_accepted(original, restored):
    assert _valid(original, restored)


@pytest.mark.parametrize(
    ("original", "restored"),
    [
        ("Анна", "Аннотация"),
        ("Иван", "Ивановна"),
        ("Ольга", "Ольховская"),
        ("Лев Орлов", "Левый Орловский"),
        ("Анна Лебедева", "анна лебедева"),
        ("Анна Лебедева", "анна Лебедева"),
        ("Анна Лебедева", "Анна лебедева"),
        ("рублей", "Рублей"),
    ],
)
def test_a_longer_unrelated_or_differently_cased_word_is_rejected(original, restored):
    assert not _valid(original, restored)


@pytest.mark.parametrize(
    ("original", "restored", "accepted"),
    [
        ("Michael Brown", "Michael Brown", True),
        ("Michael Brown", "michael brown", False),
        ("Michael Brown", "Michaels Brown", False),
        ("Michael Brown", "Michael Browne", False),
        ("Sophie Laurent", "Sophie Laurent", True),
        ("Sophie Laurent", "Sophia Laurent", False),
        ("ivan.petrov@example.com", "ivan.petrov@example.com", True),
        ("ivan.petrov@example.com", "Ivan.petrov@example.com", False),
        ("ivan.petrov@example.com", "ivan.petrov@example.comm", False),
        ("8 915 234 56 78", "8 915 234 56 78", True),
        ("4276 1234 5678 9012", "4276 1234 5678 9012", True),
        ("4276 1234 5678 9012", "4276 1234 5678 9013", False),
        ("Ли", "Ли", True),
        ("Ли", "ли", False),
    ],
)
def test_a_latin_or_non_declinable_value_must_match_exactly(
    original, restored, accepted
):
    assert _valid(original, restored) is accepted


def test_without_placeholders_the_output_must_equal_the_text():
    assert restoration_is_valid("Просто текст.", {}, "Просто текст.")
    assert not restoration_is_valid("Просто текст.", {}, "Другой текст.")
    assert not restoration_is_valid("Просто текст.", {}, "")
    assert failed_rules("Просто текст.", {}, "Другой текст.") != []


def test_the_search_for_slot_ends_has_a_step_budget(monkeypatch):
    calls = []
    original_slot_matches = restoration_validation._slot_matches

    def counting(captured, original):
        calls.append(1)
        return original_slot_matches(captured, original)

    monkeypatch.setattr(restoration_validation, "_slot_matches", counting)
    entries = {f"<PERSON_{n}>": "а" * 10 for n in range(1, 9)}
    sentence = "".join(f"<PERSON_{n}>" for n in range(1, 9)) + "."

    result = restoration_is_valid(sentence, entries, "а" * 1000 + ".")

    assert result is False
    assert len(calls) <= 25_000
