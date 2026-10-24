import pytest

from jarvis.personal_proxy.check.check_result import Doubt, DoubtKind
from jarvis.personal_proxy.confirmation.confirmation_texts import (
    offer_text,
    shown_question,
    spoken_question,
)


def _fragments(*fragments):
    return tuple(Doubt(DoubtKind.FRAGMENT, f) for f in fragments)


@pytest.mark.parametrize("language", ["en", "EN", "en-US", "en_GB", " en ", "English"])
def test_english_is_recognised_in_its_usual_spellings(language):
    assert "yes" in spoken_question(language, _fragments("x")).lower()
    assert "Nothing was sent" in offer_text(language)


@pytest.mark.parametrize("language", ["ru", "RU", "de", "english-ish", "", None, 5])
def test_any_other_language_gets_russian(language):
    assert "Скажите да или нет" in spoken_question(language, _fragments("x"))
    assert "Ничего не отправлено" in offer_text(language)


def test_blank_fragments_are_skipped_in_the_spoken_question():
    text = spoken_question("ru", _fragments("", "   ", "адрес"))

    assert "адрес" in text
    assert ": ;" not in text
    assert "; ;" not in text


@pytest.mark.parametrize("fragments", [(), ("",), ("  ", "\n")])
def test_without_any_non_blank_fragment_the_spoken_question_is_a_fixed_sentence(
    fragments,
):
    ru = spoken_question("ru", _fragments(*fragments))
    en = spoken_question("en", _fragments(*fragments))

    assert ru.startswith("Проверьте услышанный текст.")
    assert "Проверьте: ." not in ru
    assert "да или нет" in ru
    assert en.startswith("Please check what I heard.")
    assert "yes or no" in en


def test_blank_fragments_do_not_use_up_the_cap_of_the_spoken_question():
    text = spoken_question("en", _fragments("", "", "", "", "kept"))

    assert "kept" in text


def test_the_shown_question_also_skips_blank_fragments():
    text = shown_question("ru", "услышанное", _fragments("", "адрес"))

    assert "Проверьте: адрес." in text


def test_the_shown_question_with_nothing_to_name_uses_the_fixed_sentence():
    text = shown_question("ru", "услышанное", _fragments(""))

    assert "услышанное" in text
    assert "Проверьте услышанный текст." in text
