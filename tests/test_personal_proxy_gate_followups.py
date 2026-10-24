import pytest

from jarvis.personal_proxy.common.findings import GateCategory
from jarvis.personal_proxy.common.payload import build_outbound_payload
from jarvis.personal_proxy.gate.detectors.address import find_street_addresses
from jarvis.personal_proxy.gate.detectors.api_key import find_api_keys
from jarvis.personal_proxy.gate.detectors.password import find_passwords
from jarvis.personal_proxy.gate.gate import check_outbound_payload
from jarvis.personal_proxy.gate.gate_context import GateContext

BASE64_KEY = "fV88vYmBrICkR3NPXurXpvOq/0RJkn8v"


def _categories(request):
    payload = build_outbound_payload("system", request)
    result = check_outbound_payload(payload, GateContext())
    return [finding.category for finding in result.findings]


def _matched(find, text):
    return [text[span.start : span.end] for span in find(text)]


@pytest.mark.parametrize(
    "request_text",
    [
        "мой снилс 112-233\n445 95",
        "инн 77123\n45678",
        "паспорт 4519\n123456",
        "id 45391488\n03436468",
        "мой снилс 112-233\N{LINE SEPARATOR}445 95",
        "мой снилс 112-233\N{PARAGRAPH SEPARATOR}445 95",
        "мой снилс 112-233\x85445 95",
        "мой снилс 112-233\x0b445 95",
        "мой снилс 112-233\x0c445 95",
        "мой снилс 112-233\r\n445 95",
    ],
)
def test_a_number_split_by_a_line_break_is_a_digit_run(request_text):
    assert GateCategory.DIGIT_RUN in _categories(request_text)


@pytest.mark.parametrize(
    "request_text",
    [
        "Результаты:\n100\n200\n300\n",
        "Итоги:\n1234\n567\n890\n",
        "строка 12345\nстрока 678",
        "Список:\n1\n2\n3\n4\n5\n6\n7\n8\n9\n10",
    ],
)
def test_short_numbers_on_separate_lines_are_not_a_digit_run(request_text):
    assert _categories(request_text) == []


@pytest.mark.parametrize(
    "text",
    [
        "key: " + BASE64_KEY,
        "aB3dE5gH7jK9mN1/pQ3sT5uV7wX9y0Z1",
        "token Xq4+Rt9/Lm2wP8vZk3Nc7Yb5Hd1Fj6Ga0Sx=",
        "https://x.com/" + BASE64_KEY,
    ],
)
def test_a_base64_style_key_with_slashes_is_caught(text):
    assert _matched(find_api_keys, text)


@pytest.mark.parametrize(
    "text",
    [
        "/var/lib/docker/overlay2/containers/abc123def456",
        "/srv/data2/backups3/2026/archive4/file1x2y3z4",
        "see https://example.com/some/very/long/path/with/segments/1234567890abc",
        "C:/Users/name/projects/jarvis/src/personal_proxy/detectors",
        "src/jarvis/personal_proxy/detectors/api_key_detector_v2.py",
    ],
)
def test_paths_and_urls_are_not_keys(text):
    assert find_api_keys(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "пароль\nqwerty123",
        "пароль \nqwerty123",
        "password\nhunter42x",
        "Password:\nhunter42x",
    ],
)
def test_a_value_on_the_line_after_a_marker_is_caught(text):
    assert find_passwords(text) != []


@pytest.mark.parametrize(
    "text",
    [
        "забыл пароль\nи пошёл спать",
        "это мой пароль\nда",
        "новый пароль\nКак дела",
        "пароль от почты\nзабыл",
        "пароль.\nqwerty123",
        "password\n\nhunter42x",
    ],
)
def test_prose_after_a_marker_line_is_not_a_password(text):
    assert find_passwords(text) == []


def test_a_word_of_four_letters_after_a_marker_line_is_blocked_by_design():
    assert find_passwords("пароль\nпошёл спать") != []


@pytest.mark.parametrize(
    "text",
    [
        "key AbCdEfGhIjKlMnOpQrStUvWxYzAbCdEf",
        "secret aBcDeFgHiJkLmNoPqRsTuVwXyZaBcDeFgH",
    ],
)
def test_a_long_mixed_case_letter_token_is_caught(text):
    assert _matched(find_api_keys, text)


@pytest.mark.parametrize(
    "text",
    [
        "getUserAccountBalanceFromDatabaseService",
        "ThisIsAVeryLongNameForAClassThatDoesStuffInTheSystem",
        "internationalizationlocalizationconfiguration",
        "AVERYLONGCONSTANTNAMETHATISALLUPPERCASEXYZ",
        "someVeryLongCamelCaseIdentifierWithoutDigitsAtAll",
    ],
)
def test_long_identifiers_and_words_are_not_keys(text):
    assert find_api_keys(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "5 good street performers",
        "10 busy street vendors",
        "3 old street lamps",
        "2 new street lights",
        "I saw 5 big street signs",
        "We ate 4 tasty street tacos",
    ],
)
def test_adjective_street_phrases_are_not_addresses(text):
    assert find_street_addresses(text) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("lives at 123 main street", "123 main street"),
        ("10 downing street", "10 downing street"),
        ("please deliver to 42 elm street.", "42 elm street"),
        ("Ship to 7 oak avenue", "7 oak avenue"),
        ("Fine. 221 baker street", "221 baker street"),
    ],
)
def test_cued_or_sentence_initial_lowercase_addresses_are_caught(text, expected):
    assert expected in _matched(find_street_addresses, text)
