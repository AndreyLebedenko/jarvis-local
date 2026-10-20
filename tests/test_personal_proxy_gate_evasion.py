import time

import pytest

from jarvis.personal_proxy.findings import GateCategory
from jarvis.personal_proxy.gate import MAX_MESSAGE_LENGTH, check_outbound_payload
from jarvis.personal_proxy.gate_context import GateContext
from jarvis.personal_proxy.payload import build_outbound_payload


def _gate(request, mapping=None):
    payload = build_outbound_payload("system", request)
    return check_outbound_payload(payload, GateContext(mapping or {}))


@pytest.mark.parametrize(
    ("category", "secret", "mapping"),
    [
        (GateCategory.PHONE, "+7\u00a0915\u00a0234\u00a056\u00a078", None),
        (GateCategory.PHONE, "+7 915 234\u201356\u201378", None),
        (GateCategory.PAYMENT_CARD, "4539\u20091488\u20090343\u20096467", None),
        (GateCategory.PAYMENT_CARD, "\uff14\uff15\uff13\uff19 1488 0343 6467", None),
        (GateCategory.IBAN, "GB82\u00a0WEST\u00a01234 5698 7654 32", None),
        (GateCategory.DIGIT_RUN, "123\u2009456\u2009789", None),
        (GateCategory.EMAIL, "anna\u200b@example.com", None),
        (GateCategory.EMAIL, "anna\uff20example.com", None),
        (GateCategory.MAPPING_ORIGINAL, "Лебе\u200bдева", {"<P_1>": "Лебедева"}),
        (GateCategory.MAPPING_ORIGINAL, "Лебе\u00adдева", {"<P_1>": "Лебедева"}),
        (GateCategory.PASSWORD, "пароль\uff1a Zk9#mQ2x", None),
    ],
)
def test_invisible_and_lookalike_characters_do_not_hide_a_leak(
    category, secret, mapping
):
    request = f"вот данные {secret} конец"

    result = _gate(request, mapping)

    assert category in [f.category for f in result.findings]


def test_a_finding_position_refers_to_the_original_text():
    request = "ID \u200b123456789 end"

    [finding] = _gate(request).findings

    assert request[finding.start : finding.end] == "123456789"


def test_a_message_above_the_length_cap_is_a_block_without_running_detectors():
    result = _gate("а" * (MAX_MESSAGE_LENGTH + 1))

    assert [f.category for f in result.findings] == [GateCategory.GATE_ERROR]
    assert result.findings[0].message_index == 1


ADVERSARIAL = {
    "iban_starts": "AB12 " * 4000,
    "alnum_pairs": "a1" * 10000,
    "one_letter": "a" * 20000,
    "digit_hyphens": "1-" * 10000,
    "digit_spaces": "1 " * 10000,
    "plus_seven": "+7 " * 6000,
    "at_signs": "x@" * 10000,
    "street_marker": "улица " * 3300,
    "password_marker": "пароль " * 2800,
    "dotted_street": "ул. Ленина " * 1800,
    "brackets": "(1) " * 5000,
    "dotted_digits": "1.1" * 6000,
    "jwt_prefix": "eyJ" * 6000,
    "long_digits": "1" * 20000,
    "dot_triplets": "123." * 5000,
}


@pytest.mark.parametrize("name", sorted(ADVERSARIAL))
def test_adversarial_input_at_the_cap_finishes_quickly(name):
    adversarial = ADVERSARIAL[name]
    assert len(adversarial) <= MAX_MESSAGE_LENGTH
    started = time.perf_counter()

    _gate(adversarial, {"<P_1>": "Анна Лебедева"})

    assert time.perf_counter() - started < 2.0
