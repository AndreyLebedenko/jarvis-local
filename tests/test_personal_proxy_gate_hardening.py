import time

import pytest

from jarvis.personal_proxy.common.findings import GateCategory, GateStage
from jarvis.personal_proxy.common.payload import (
    DEFAULT_SYSTEM_PROMPT,
    build_outbound_payload,
)
from jarvis.personal_proxy.gate import gate as gate_module
from jarvis.personal_proxy.gate.detectors.address import find_street_addresses
from jarvis.personal_proxy.gate.detectors.api_key import find_api_keys
from jarvis.personal_proxy.gate.detectors.card import find_payment_cards
from jarvis.personal_proxy.gate.detectors.digit_run import find_long_digit_runs
from jarvis.personal_proxy.gate.detectors.iban import find_ibans
from jarvis.personal_proxy.gate.detectors.password import find_passwords
from jarvis.personal_proxy.gate.detectors.phone import find_phones
from jarvis.personal_proxy.gate.gate import MAX_TOPICS_LENGTH, check_outbound_payload
from jarvis.personal_proxy.gate.gate_context import GateContext

VALID_CARD_DIGITS = "4539148803436467"


def _gate(request, mapping=None, topics_text="", system_prompt="system"):
    payload = build_outbound_payload(system_prompt, request)
    return check_outbound_payload(payload, GateContext(mapping or {}, topics_text))


def _categories(result):
    return [finding.category for finding in result.findings]


def _matched(find, text):
    return [text[span.start : span.end] for span in find(text)]


@pytest.mark.parametrize(
    ("find", "text", "expected"),
    [
        (find_passwords, "DB_PASSWORD=hunter2x", "hunter2x"),
        (find_passwords, "userPassword=Kotik2020", "Kotik2020"),
        (find_passwords, "MYSQL_PWD=abcd1234", "abcd1234"),
        (
            find_passwords,
            "мойпароль: kotik2020",
            "kotik2020",
        ),
        (find_passwords, '{"password": "Zk9mQ2xyz"}', "Zk9mQ2xyz"),
        (find_passwords, "{'password':'Zk9mQ2xyz'}", "Zk9mQ2xyz"),
        (find_passwords, "Password(Zk9mQ2xyz)", "Zk9mQ2xyz"),
        (find_passwords, "password => Zk9mQ2xyz", "Zk9mQ2xyz"),
        (find_passwords, "password is: Zk9mQ2xyz", "Zk9mQ2xyz"),
        (find_passwords, "the passphrase is correcthorse", "correcthorse"),
        (find_passwords, "passcode: 482913", "482913"),
        (find_passwords, "api_key=Zk9mQ2xyz", "Zk9mQ2xyz"),
        (
            find_api_keys,
            "x_sk-proj-abcdEFGH1234ijklMNOP5678",
            "sk-proj-abcdEFGH1234ijklMNOP5678",
        ),
        (find_api_keys, "KEY_AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
    ],
)
def test_markers_after_underscore_and_wider_separators_are_caught(find, text, expected):
    assert expected in _matched(find, text)


@pytest.mark.parametrize(
    "text",
    [
        "bypass the problem entirely",
        "compass points north",
        "he said the secret is out",
        "the token of appreciation",
        "забыл пароль от почты",
        "\u00abpassword\u00bb is a word",
    ],
)
def test_ordinary_prose_with_marker_like_words_passes(text):
    assert find_passwords(text) == []


@pytest.mark.parametrize(
    ("find", "text", "expected"),
    [
        (find_payment_cards, "4539 1488\r\n0343 6467", "4539 1488\n0343 6467"),
        (
            find_payment_cards,
            "4539 \u2013 1488 \u2013 0343 \u2013 6467",
            "4539 - 1488 - 0343 - 6467",
        ),
        (find_payment_cards, "4539  1488   0343 6467", "4539 1488 0343 6467"),
        (find_phones, "(999) 123 - 45 - 67", "(999) 123 - 45 - 67"),
        (find_phones, "+7 915\n234 56 78", "+7 915\n234 56 78"),
        (find_ibans, "GB82 WEST\n1234 5698\n7654 32", "GB82 WEST\n1234 5698\n7654 32"),
        (find_long_digit_runs, "4539 - 1488 - 03", "4539 - 1488 - 03"),
    ],
)
def test_digit_groups_join_across_collapsed_whitespace(find, text, expected):
    from jarvis.personal_proxy.common.normalize import normalize_message

    normalized = normalize_message(text).text

    assert expected in _matched(find, normalized)


def test_digit_groups_on_separate_lines_are_not_a_digit_run():
    assert _gate("Результаты:\n100\n200\n300\n").allowed


def test_a_card_split_by_a_line_break_is_found_in_the_original_text():
    request = "card 4539 1488\r\n0343 6467 ok"

    [finding] = _gate(request).findings

    assert finding.category is GateCategory.PAYMENT_CARD
    assert request[finding.start : finding.end] == "4539 1488\r\n0343 6467"


@pytest.mark.parametrize(
    ("secret_text", "topic_or_original", "kind"),
    [
        (
            "мой\u200bдиагноз такой",
            "мой диагноз",
            "topic",
        ),
        (
            "Иван\u200bПетров пришёл",
            "Петров",
            "original",
        ),
        (
            "Лебе\u200bдева пришла",
            "Лебедева",
            "original",
        ),
    ],
)
def test_a_zero_width_space_between_letters_does_not_hide_a_word(
    secret_text, topic_or_original, kind
):
    if kind == "topic":
        result = _gate(secret_text, topics_text=topic_or_original)
        expected = GateCategory.TOPIC_TEXT
    else:
        result = _gate(secret_text, mapping={"<P_1>": topic_or_original})
        expected = GateCategory.MAPPING_ORIGINAL

    assert expected in _categories(result)


def test_a_zero_width_space_inside_a_number_does_not_hide_it():
    assert GateCategory.PHONE in _categories(_gate("8915\u200b2345678"))
    assert GateCategory.PHONE in _categories(_gate("+7915\u20602345678"))


def test_a_request_that_is_empty_after_normalization_is_a_block():
    result = _gate("\u200b\u00ad \ufeff ")

    assert _categories(result) == [GateCategory.GATE_ERROR]
    assert result.findings[0].stage is GateStage.EMPTY


def test_decomposed_letters_match_the_composed_mapping_original():
    result = _gate(
        "Елена Е\u0308жикова",
        {"<P_1>": "Ёжикова"},
    )

    assert GateCategory.MAPPING_ORIGINAL in _categories(result)


def test_a_decomposed_topic_line_matches_composed_text():
    result = _gate(
        "ёлка больна",
        topics_text="е\u0308лка больна",
    )

    assert GateCategory.TOPIC_TEXT in _categories(result)


def test_a_mapping_original_that_is_a_short_word_does_not_hit_the_system_prompt():
    for original in ("Lana", "Per", "Req", "Plac"):
        result = _gate(
            "<PERSON_1> wrote",
            {"<P_1>": original},
            system_prompt=DEFAULT_SYSTEM_PROMPT,
        )

        assert result.allowed, original


def test_a_mapping_original_equal_to_a_whole_system_word_still_blocks():
    result = _gate("hello", {"<P_1>": "Answer"}, system_prompt=DEFAULT_SYSTEM_PROMPT)

    [finding] = result.findings
    assert (finding.category, finding.message_index) == (
        GateCategory.MAPPING_ORIGINAL,
        0,
    )


def test_the_stem_rule_still_applies_to_the_user_message():
    result = _gate(
        "Передай Анне",
        {"<P_1>": "Анна"},
        system_prompt=DEFAULT_SYSTEM_PROMPT,
    )

    assert _categories(result) == [GateCategory.MAPPING_ORIGINAL]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "пр-т Мира 10",
            "пр-т Мира 10",
        ),
        (
            "просп. Мира 10",
            "просп. Мира 10",
        ),
        (
            "ул Ленина 5",
            "ул Ленина 5",
        ),
        (
            "б-р Сенкевича 5",
            "б-р Сенкевича 5",
        ),
        (
            "ул. 8 Марта 10",
            "ул. 8 Марта 10",
        ),
        (
            "ул. 1905 года 5",
            "ул. 1905 года 5",
        ),
        (
            "улица 8 Марта 10",
            "улица 8 Марта 10",
        ),
        ("lives at 123 main street", "123 main street"),
        ("10 downing street", "10 downing street"),
    ],
)
def test_more_address_forms_are_caught(text, expected):
    assert expected in _matched(find_street_addresses, text)


@pytest.mark.parametrize(
    "text",
    [
        "на улице 5 минут 3 раза",
        "улица была пуста",
        "правило 5",
        "it takes 5 minutes on the street",
        "about 3 hours road trip",
        "5 minutes street food",
    ],
)
def test_ordinary_prose_is_not_an_address(text):
    assert find_street_addresses(text) == []


def test_a_failure_reports_its_stage_and_not_the_cause(monkeypatch):
    secret = "k7q.canary@example.com"

    def broken(text):
        raise RuntimeError(text)

    monkeypatch.setattr(
        gate_module, "PATTERN_DETECTORS", ((GateCategory.EMAIL, broken),)
    )

    result = _gate(f"write to {secret}")

    [finding] = result.findings
    assert (finding.category, finding.stage) == (
        GateCategory.GATE_ERROR,
        GateStage.PATTERNS,
    )
    assert secret not in repr(result) + str(result)


@pytest.mark.parametrize(
    ("payload_or_context", "stage"),
    [
        (("nope", GateContext()), GateStage.INPUT),
        ((build_outbound_payload("s", "x" * 20001), GateContext()), GateStage.LENGTH),
        (
            (build_outbound_payload("s", "u"), GateContext(mapping={"<A_1>": 5})),
            GateStage.NORMALIZATION,
        ),
        (
            (
                build_outbound_payload("s", "u"),
                GateContext(topics_text="t" * (MAX_TOPICS_LENGTH + 1)),
            ),
            GateStage.LENGTH,
        ),
    ],
)
def test_each_block_names_the_stage_that_failed(payload_or_context, stage):
    payload, context = payload_or_context

    [finding] = check_outbound_payload(payload, context).findings

    assert (finding.category, finding.stage) == (GateCategory.GATE_ERROR, stage)


ADVERSARIAL = {
    "single_capital_word": "А" * 20000,
    "capital_then_lower": "Аа" * 10000,
    "latin_capital_word": "A" * 20000,
    "digit_word_pairs": "1а" * 10000,
    "newlines": "1\n" * 10000,
    "dash_spaces": "1 - " * 5000,
    "bracket_digits": "(123) " * 3300,
    "zero_width": "\u200b" * 20000,
    "letters_zero_width": "a\u200b" * 10000,
    "combining": "е\u0308" * 10000,
}


@pytest.mark.parametrize("name", sorted(ADVERSARIAL))
def test_more_adversarial_messages_finish_quickly(name):
    started = time.perf_counter()

    _gate(
        ADVERSARIAL[name],
        {"<P_1>": "Анна Лебедева"},
        "а б",
    )

    assert time.perf_counter() - started < 1.0


def test_a_long_topics_line_against_a_repetitive_message_is_fast():
    topics = " ".join(["a"] * 5000)
    request = " ".join(["a"] * 9999)
    started = time.perf_counter()

    result = _gate(request, topics_text=topics)

    assert time.perf_counter() - started < 1.0
    assert GateCategory.TOPIC_TEXT in _categories(result)


def test_many_topic_lines_are_fast():
    topics = "\n".join(f"topic{index} line" for index in range(3000))
    started = time.perf_counter()

    _gate("an ordinary request " * 900, topics_text=topics)

    assert time.perf_counter() - started < 1.0
