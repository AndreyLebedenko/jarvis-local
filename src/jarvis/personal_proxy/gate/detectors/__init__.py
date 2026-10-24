"""Deterministic pattern detectors, in the order the gate gives them priority.

A detector takes one message text and returns where it matched. The gate turns
a match into a finding that holds a category and a position, never the match.
"""

from __future__ import annotations

from collections.abc import Callable

from jarvis.personal_proxy.common.findings import GateCategory
from jarvis.personal_proxy.common.spans import Span
from jarvis.personal_proxy.gate.detectors.address import find_street_addresses
from jarvis.personal_proxy.gate.detectors.api_key import find_api_keys
from jarvis.personal_proxy.gate.detectors.card import find_payment_cards
from jarvis.personal_proxy.gate.detectors.digit_run import find_long_digit_runs
from jarvis.personal_proxy.gate.detectors.email import find_emails
from jarvis.personal_proxy.gate.detectors.iban import find_ibans
from jarvis.personal_proxy.gate.detectors.password import find_passwords
from jarvis.personal_proxy.gate.detectors.phone import find_phones

Detector = Callable[[str], list[Span]]

PATTERN_DETECTORS: tuple[tuple[GateCategory, Detector], ...] = (
    (GateCategory.EMAIL, find_emails),
    (GateCategory.API_KEY, find_api_keys),
    (GateCategory.IBAN, find_ibans),
    (GateCategory.PAYMENT_CARD, find_payment_cards),
    (GateCategory.PHONE, find_phones),
    (GateCategory.PASSWORD, find_passwords),
    (GateCategory.STREET_ADDRESS, find_street_addresses),
    (GateCategory.DIGIT_RUN, find_long_digit_runs),
)
