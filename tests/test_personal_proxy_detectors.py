import pytest

from jarvis.personal_proxy.detectors.address import find_street_addresses
from jarvis.personal_proxy.detectors.api_key import find_api_keys
from jarvis.personal_proxy.detectors.card import find_payment_cards
from jarvis.personal_proxy.detectors.digit_run import find_long_digit_runs
from jarvis.personal_proxy.detectors.email import find_emails
from jarvis.personal_proxy.detectors.iban import find_ibans
from jarvis.personal_proxy.detectors.password import find_passwords
from jarvis.personal_proxy.detectors.phone import find_phones

VALID_CARD = "4539 1488 0343 6467"
LUHN_INVALID_CARD = "4539 1488 0343 6468"
RANDOM_TOKEN = "4IBAf3xjijU5slyTB65sIEZHU6wMKOC2UciBUhbn"
JWT = (
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
    "dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk"
)


def _matched(find, text):
    return [text[span.start : span.end] for span in find(text)]


@pytest.mark.parametrize(
    ("find", "text", "expected"),
    [
        (
            find_emails,
            "напиши на anna.lebedeva@example.com сегодня",
            "anna.lebedeva@example.com",
        ),
        (find_emails, "почта ivan+work@почта.рф", "ivan+work@почта.рф"),
        (find_phones, "позвони +7 (915) 234-56-78 завтра", "+7 (915) 234-56-78"),
        (find_phones, "мой номер 8 915 234 56 78.", "8 915 234 56 78"),
        (find_phones, "call +44 20 7946 0958 now", "+44 20 7946 0958"),
        (find_payment_cards, f"карта {VALID_CARD} срок", VALID_CARD),
        (find_payment_cards, "карта 4539148803436467", "4539148803436467"),
        (
            find_ibans,
            "счет GB82 WEST 1234 5698 7654 32 открыт",
            "GB82 WEST 1234 5698 7654 32",
        ),
        (find_ibans, "IBAN DE89370400440532013000", "DE89370400440532013000"),
        (find_long_digit_runs, "номер 123456789 в базе", "123456789"),
        (find_long_digit_runs, "код 12 345 678 9", "12 345 678 9"),
        (
            find_api_keys,
            "ключ sk-proj-abcdEFGH1234ijklMNOP5678",
            "sk-proj-abcdEFGH1234ijklMNOP5678",
        ),
        (find_api_keys, "AWS AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
        (find_api_keys, "token ghp_" + "a1B2c3D4e5" * 4, "ghp_" + "a1B2c3D4e5" * 4),
        (find_api_keys, f"jwt {JWT}", JWT),
        (find_api_keys, f"секрет {RANDOM_TOKEN} вот", RANDOM_TOKEN),
        (find_passwords, "пароль: Zk9#mQ2x", "Zk9#mQ2x"),
        (find_passwords, "мой пароль qwerty123", "qwerty123"),
        (find_passwords, "password is hunter42!", "hunter42!"),
        (find_passwords, "pwd=correcthorse", "correcthorse"),
        (find_passwords, "пароль от почты: abcd1234", "abcd1234"),
        (find_street_addresses, "живу на улице Ленина 5", "улице Ленина 5"),
        (find_street_addresses, "ул. Тверская, д. 7", "ул. Тверская, д. 7"),
        (find_street_addresses, "проспект Мира 101", "проспект Мира 101"),
        (find_street_addresses, "переулок тихий дом 3", "переулок тихий дом 3"),
        (find_street_addresses, "Рублёвское шоссе 12", "Рублёвское шоссе 12"),
        (find_street_addresses, "I live at 221 Baker Street", "221 Baker Street"),
        (find_street_addresses, "send to 10 Downing St.", "10 Downing St."),
    ],
)
def test_detector_reports_the_sensitive_span(find, text, expected):
    assert expected in _matched(find, text)


@pytest.mark.parametrize(
    ("find", "text"),
    [
        (find_emails, "пиши мне @вечером или на сайте example.com"),
        (find_phones, "встреча 20.10.2026 в 15:30, 3 или 12 человек"),
        (find_phones, "позвони 915 234 56 78"),
        (find_phones, "+7 915"),
        (find_payment_cards, f"карта {LUHN_INVALID_CARD}"),
        (find_payment_cards, "заказ 12345 на 2026 год и 700 рублей"),
        (find_ibans, "GB82 WEST 1234 5698 7654 33"),
        (find_ibans, "AB12 просто слова"),
        (find_long_digit_runs, "встреча 20.10.2026, 1500 рублей, 3 яблока и 12 груш"),
        (find_long_digit_runs, "в 2026 году 15 июня, 12 345 678"),
        (find_api_keys, "обычный текст про sk и ключи в целом"),
        (find_api_keys, "a" * 40),
        (
            find_api_keys,
            "https://example.com/some/very/long/path/with/segments/1234567890abc",
        ),
        (find_passwords, "пароль от банка"),
        (find_phones, "(20.10.2026) и (100) 200"),
        (find_phones, "дата 2026-10-20 и 20-10-2026 и 1,500,000"),
        (find_phones, "цена 12.50 и 3.99 доллара, 100.200.300"),
        (find_long_digit_runs, "20.10.2026 14, 1,500,000, 12/10/2026, 10.5 3.25"),
        (find_api_keys, "get_user_by_id_2_final_version_v2_config_name"),
        (find_api_keys, "someVeryLongCamelCaseIdentifierWithV2Suffix1"),
        (find_street_addresses, "улица была тихая, 5 минут"),
        (find_street_addresses, "5 minutes on the street way back"),
        (find_passwords, "password: <SECRET_1>"),
        (find_passwords, "забыл пароль"),
        (find_passwords, "пароль: abc"),
        (find_passwords, "забыл пароль от почты"),
        (find_passwords, "пароль, который нужен"),
        (find_passwords, "пароль нужен для сайта"),
        (find_street_addresses, "на улице было 5 человек"),
        (find_street_addresses, "улица Ленина длинная"),
        (find_street_addresses, "I have 5 good reasons for this street"),
    ],
)
def test_detector_passes_ordinary_text(find, text):
    assert find(text) == []


def test_a_luhn_invalid_digit_run_is_a_digit_run_and_not_a_card():
    text = f"карта {LUHN_INVALID_CARD}"

    assert find_payment_cards(text) == []
    assert _matched(find_long_digit_runs, text) == [LUHN_INVALID_CARD]


def test_a_card_next_to_another_number_is_still_found():
    text = f"20 10 2026 {VALID_CARD}"

    assert VALID_CARD in _matched(find_payment_cards, text)


def test_a_date_is_not_a_digit_run_even_with_a_time():
    assert find_long_digit_runs("20.10.2026 14:30:15") == []


@pytest.mark.parametrize(
    ("find", "text", "expected"),
    [
        (find_phones, "call (415) 555-2671 now", "(415) 555-2671"),
        (find_phones, "тел (495) 123-45-67.", "(495) 123-45-67"),
        (find_phones, "tel 415.555.2671 ok", "415.555.2671"),
        (find_phones, "tel 415-555-2671 ok", "415-555-2671"),
        (find_phones, "тел 495-123-45-67 ok", "495-123-45-67"),
        (find_payment_cards, "card 4539.1488.0343.6467 ok", "4539.1488.0343.6467"),
        (find_long_digit_runs, "id 123.456.789 ok", "123.456.789"),
        (find_long_digit_runs, "id 123/456/789 ok", "123/456/789"),
        (find_api_keys, "key:" + RANDOM_TOKEN, RANDOM_TOKEN),
        (find_api_keys, "https://x.com/" + RANDOM_TOKEN, RANDOM_TOKEN),
        (find_api_keys, "key=" + RANDOM_TOKEN, RANDOM_TOKEN),
        (
            find_api_keys,
            "bot 123456789:AAH" + "x7Qa9" * 7,
            "123456789:AAH" + "x7Qa9" * 7,
        ),
        (
            find_api_keys,
            "glpat-" + "aB3dE5gH7jK9mN1pQ3sT",
            "glpat-" + "aB3dE5gH7jK9mN1pQ3sT",
        ),
        (
            find_api_keys,
            "hash 5d41402abc4b2a76b9719d911017c592 ok",
            "5d41402abc4b2a76b9719d911017c592",
        ),
        (
            find_api_keys,
            "sha 356a192b7913b04c54574d18c28d46e6395428ab ok",
            "356a192b7913b04c54574d18c28d46e6395428ab",
        ),
        (find_passwords, "passwords: hunter2", "hunter2"),
        (find_passwords, "pass hunter42", "hunter42"),
        (find_passwords, "пароль у меня qwerty", "qwerty"),
        (find_passwords, "мой пароль - kotik2020", "kotik2020"),
        (find_passwords, "пароль это solnce", "solnce"),
        (find_passwords, "пароль от почты kotik", "kotik"),
        (find_street_addresses, "ул. ленина 5", "ул. ленина 5"),
        (find_street_addresses, "пр. мира 12", "пр. мира 12"),
        (find_street_addresses, "Цветной бульвар 7", "Цветной бульвар 7"),
        (find_street_addresses, "наб. Мойки, 12", "наб. Мойки, 12"),
        (find_street_addresses, "Красная площадь 1", "Красная площадь 1"),
        (find_street_addresses, "пл. Ленина 3", "пл. Ленина 3"),
        (find_street_addresses, "Baker Street 221", "Baker Street 221"),
        (find_street_addresses, "12 Oak Way", "12 Oak Way"),
        (find_street_addresses, "5 High Court", "5 High Court"),
        (find_street_addresses, "Sunset Blvd 9", "Sunset Blvd 9"),
        (find_street_addresses, "7 Elm Rd", "7 Elm Rd"),
    ],
)
def test_detector_covers_the_wider_forms(find, text, expected):
    assert any(expected in found for found in _matched(find, text))
