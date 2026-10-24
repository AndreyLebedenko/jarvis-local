import pytest

from jarvis.personal_proxy.check.check_result import FallbackReason
from jarvis.personal_proxy.check.rewrite_guard import detect_rewrite


def test_a_second_invented_address_is_caught():
    whisper = "Напиши info собака trade-house точка ру что я приду"
    checked = "Напиши info@trade-house.ru и marina@trade-house.ru что я приду"

    assert detect_rewrite(whisper, checked) is FallbackReason.INVENTED_ADDRESS


def test_an_address_where_the_engine_heard_none_is_caught():
    assert (
        detect_rewrite("Позвони завтра утром", "Позвони ivan@primer.com утром")
        is FallbackReason.INVENTED_ADDRESS
    )


def test_a_spoken_address_assembled_into_latin_is_not_a_rewrite():
    whisper = "Отправь на иван точка петров собака пример точка ком"
    checked = "Отправь на ivan.petrov@primer.com"

    assert detect_rewrite(whisper, checked) is None


def test_an_address_already_in_the_engine_text_may_stay():
    text = "Напиши на ivan@primer.com про встречу"

    assert detect_rewrite(text, text) is None


def test_a_transliterated_marker_counts_as_a_spoken_address():
    whisper = "write to ivan sobaka primer dot com"

    assert detect_rewrite(whisper, "write to ivan@primer.com") is None


def test_a_request_translated_into_english_is_caught():
    whisper = "Переведи на английский слово яблоко"
    checked = "Translate the word apple into English"

    assert detect_rewrite(whisper, checked) is FallbackReason.ALPHABET_SWITCH


def test_the_share_must_fall_below_half_not_merely_to_half():
    whisper = "абвгд"
    at_half = "абgd"
    below_half = "абgde"

    assert detect_rewrite(whisper, at_half) is None
    assert detect_rewrite(whisper, below_half) is FallbackReason.ALPHABET_SWITCH


def test_a_latin_word_the_engine_already_wrote_is_not_a_rewrite():
    whisper = "Открой gmail и проверь почту"
    checked = "Открой Gmail и проверь почту"

    assert detect_rewrite(whisper, checked) is None


def test_a_latin_name_repaired_from_cyrillic_is_not_a_rewrite():
    whisper = "Позвони в Эппл завтра утром насчёт заказа"
    checked = "Позвони в Apple завтра утром насчёт заказа"

    assert detect_rewrite(whisper, checked) is None


def test_an_english_request_stays_english():
    text = "Send the report to the accountant tomorrow"

    assert detect_rewrite(text, text) is None


def test_a_request_that_is_only_an_address_is_not_an_alphabet_switch():
    assert detect_rewrite("иван собака пример точка ком", "ivan@primer.com") is None


@pytest.mark.parametrize("text", ["", "   ", "8 912 345 67 89"])
def test_text_without_letters_trips_nothing(text):
    assert detect_rewrite(text, text) is None


@pytest.mark.parametrize(
    ("whisper", "checked"),
    [
        ("Логин иван петров", "Логин ivan.petrov"),
        ("Позвони Майклу Джексону", "Позвони Michael Jackson"),
        ("Сайт гугл точка ком", "Сайт google.com"),
    ],
)
def test_a_latin_repair_in_a_very_short_utterance_trips_the_guard_by_design(
    whisper, checked
):
    assert detect_rewrite(whisper, checked) is FallbackReason.ALPHABET_SWITCH
