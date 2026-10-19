"""Expected e-mail addresses of the corpus utterances that spell one aloud.

The labeled spans check stems (`alex`, `smirnov`), which a wrongly assembled
domain still satisfies. This module holds, per phrase, the addresses that count
as right and the spoken form that also counts (an address left as words). Used by
the label rule `addresses_assembled` of spike v2.1.0-9. Keyed by the phrase id
without the voice suffix. Spoken domains such as "пример" have more than one
legitimate Latin rendering, so a phrase lists every accepted address.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

VOICE_SEPARATOR = "__"
_EDGE_PUNCTUATION = " \t\n.,;:!?()[]{}\"'«»"
_WORD = re.compile(r"[\w@.\-]+", re.UNICODE)


@dataclass(frozen=True)
class ExpectedAddress:
    accepted: tuple[str, ...]
    spoken: str


EXPECTED: dict[str, ExpectedAddress] = {
    "id_email": ExpectedAddress(
        ("ivan.petrov@primer.com", "ivan.petrov@example.com"),
        "иван точка петров собака пример точка ком",
    ),
    "id_letter_long": ExpectedAddress(
        ("ivan.petrov@primer.com", "ivan.petrov@example.com"),
        "иван точка петров собака пример точка ком",
    ),
    "m_trade_house": ExpectedAddress(
        ("info@trade-house.ru",), "info собака trade-house точка ru"
    ),
    "m_github": ExpectedAddress(
        ("dvolkov@gmail.com",), "dvolkov собака gmail точка com"
    ),
    "v2_email_underscore": ExpectedAddress(
        ("alex.smirnov_92@pochta.ru", "alex.smirnov_92@почта.ру"),
        "алекс точка смирнов подчёркивание девяносто два собака почта точка ру",
    ),
}


def base_id(utterance_id: str) -> str:
    return utterance_id.split(VOICE_SEPARATOR)[0]


def _address_tokens(text: str) -> set[str]:
    return {
        token.strip(_EDGE_PUNCTUATION).lower() for token in text.split() if "@" in token
    }


def _spoken_words(text: str) -> str:
    return " ".join(w.lower().strip(".-") for w in _WORD.findall(text))


def address_is_right(utterance_id: str, output: str) -> bool | None:
    """None when the phrase spells no address; else whether `output` carries a
    right assembled address or the spoken form unchanged."""
    expected = EXPECTED.get(base_id(utterance_id))
    if expected is None:
        return None
    found = _address_tokens(output)
    if len(found) > 1:
        return False
    if found & {a.lower() for a in expected.accepted}:
        return True
    return _spoken_words(expected.spoken) in _spoken_words(output)
