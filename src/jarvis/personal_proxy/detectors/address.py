"""Street-address shapes: a street marker, a name, and a house number.

Russian: the marker (a word, or an abbreviation with or without a dot) comes
before the name, or after a capitalized name ("Рублёвское шоссе 12"). A name
must start with a capital letter, with these exceptions: it may be lowercase
after a dotted abbreviation or the dashed abbreviations of avenue and
boulevard, or when a house marker precedes the number. A name may start with a
number ("ул. 8 Марта 10"). So "на улице было 5 человек" passes.

English: "<number> <Capitalized Name> <street word>", "<Capitalized Name>
<street word> <number>", or one lowercase word before street/avenue/boulevard
("123 main street"). A lowercase name counts only after an address cue (at, on,
to, from, near, address, deliver to, ship to) or at the start of a sentence,
only when the name is not an adjective, article or unit of time from a short
stoplist, and only when no lowercase word follows the street word: so "5 good
street performers" and "3 hours road trip" are ordinary prose.

Every word is length-bounded so a long single word cannot make the scan
quadratic.
"""

from __future__ import annotations

import re

from jarvis.personal_proxy.spans import Span

_RU_WORD_MARKER = (
    r"(?<!\w)(?i:улиц\w*|проспект\w*|переул\w*|шоссе|бульвар\w*|набережн\w*"
    r"|площад\w*)"
)
_RU_ABBREVIATION = r"(?<!\w)(?:(?i:ул|просп|пр|пер|наб|пл)\.?|(?i:пр-т|б-р)\.?)(?!\w)"
_RU_STRICT_ABBREVIATION = (
    r"(?<!\w)(?:(?i:ул|просп|пр|пер|наб|пл)\.|(?i:пр-т|б-р)\.?)(?!\w)"
)
_RU_MARKER = rf"(?:{_RU_WORD_MARKER}|{_RU_ABBREVIATION})"
_RU_HOUSE_MARKER = r"(?i:д\.?|дом)"
_RU_CAPITALIZED_WORD = r"[А-ЯЁ][\w.-]{0,40}"
_RU_ANY_WORD = r"[^\W\d_][\w-]{0,40}"
_RU_HOUSE_NUMBER = r"\d{1,4}(?:[а-яa-z]|[/-]\d{1,3})?"

_RU_CAPITALIZED_NAME = (
    rf"{_RU_MARKER}[\s,]+(?:{_RU_CAPITALIZED_WORD}[\s,]+){{1,3}}?"
    rf"(?:{_RU_HOUSE_MARKER}\s*)?{_RU_HOUSE_NUMBER}"
)
_RU_ABBREVIATED_ANY_CASE = (
    rf"{_RU_STRICT_ABBREVIATION}\s*(?:{_RU_ANY_WORD}[\s,]+){{1,3}}?"
    rf"(?:{_RU_HOUSE_MARKER}\s*)?{_RU_HOUSE_NUMBER}"
)
_RU_NUMBERED_NAME = (
    rf"(?:{_RU_STRICT_ABBREVIATION}|(?<!\w)(?i:улица)(?!\w))\s*"
    rf"\d{{1,4}}\s+{_RU_ANY_WORD}[\s,]+{_RU_HOUSE_NUMBER}"
)
_RU_MARKED_HOUSE = (
    rf"{_RU_MARKER}[\s,]+(?:{_RU_ANY_WORD}[\s,]+){{1,3}}?"
    rf"{_RU_HOUSE_MARKER}\s*{_RU_HOUSE_NUMBER}"
)
_RU_NAME_BEFORE_MARKER = (
    rf"(?<![\w.-]){_RU_CAPITALIZED_WORD}\s+{_RU_MARKER}[\s,]+"
    rf"(?:{_RU_HOUSE_MARKER}\s*)?{_RU_HOUSE_NUMBER}"
)
_EN_STREET_WORD = (
    r"(?i:street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|court|ct|way"
    r"|drive|dr)\b\.?"
)
_EN_NAME = r"(?:[A-Z][a-z'-]{0,30}\s+){1,3}"
_EN_NUMBER_FIRST = rf"\b\d{{1,5}}[A-Za-z]?\s+{_EN_NAME}{_EN_STREET_WORD}"
_EN_NUMBER_LAST = rf"\b{_EN_NAME}{_EN_STREET_WORD}[\s,]*\d{{1,5}}[A-Za-z]?\b"
_EN_LOWERCASE_NAME = re.compile(
    r"\b\d{1,5}[A-Za-z]?\s+"
    r"(?!(?i:the|an?|on|in|of|to|my|your|our|this|that|these|those|every|each"
    r"|some|any|seconds?|minutes?|hours?|days?|weeks?|months?|years?|times?"
    r"|blocks?|miles?|steps?"
    r"|good|bad|busy|old|new|big|small|little|long|short|narrow|wide|quiet"
    r"|noisy|famous|local|nice|great|fine|hot|cold|dark|bright|empty|full"
    r"|many|few|other|same|last|next|first)\b)"
    r"[a-z][a-z']{1,20}\s+(?i:street|avenue|boulevard)\b(?!\s+[a-z])"
)
_EN_ADDRESS_CUE = re.compile(
    r"(?:^|[.!?]\s+"
    r"|(?i:\b(?:at|on|to|from|near|address|deliver to|ship to)\b)[:,]?\s+)$"
)
_CUE_LOOKBACK = 20

_ADDRESS = re.compile(
    "|".join(
        (
            _RU_CAPITALIZED_NAME,
            _RU_ABBREVIATED_ANY_CASE,
            _RU_NUMBERED_NAME,
            _RU_MARKED_HOUSE,
            _RU_NAME_BEFORE_MARKER,
            _EN_NUMBER_FIRST,
            _EN_NUMBER_LAST,
        )
    )
)


def _has_address_cue(text: str, start: int) -> bool:
    before = text[max(0, start - _CUE_LOOKBACK) : start]
    return start == 0 or _EN_ADDRESS_CUE.search(before) is not None


def find_street_addresses(text: str) -> list[Span]:
    spans = [Span(m.start(), m.end()) for m in _ADDRESS.finditer(text)]
    spans += [
        Span(m.start(), m.end())
        for m in _EN_LOWERCASE_NAME.finditer(text)
        if _has_address_cue(text, m.start())
    ]
    return spans
