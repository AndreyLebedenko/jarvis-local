"""Password-like strings: the value after a password marker.

Markers: password(s), passwd, passphrase, passcode, pass, pwd, api key and the
Russian stem for "password". A Latin marker counts after '_' or at a camelCase
hump (DB_PASSWORD, userPassword) but not inside a word (bypass, compass); the
Russian marker also counts glued to a word.

After a marker, a closing quote or bracket and one of ':' '=' '=>' '(' '-' are
allowed, connector words (is, "for <word>", the Russian "of <word>" and "it
is", ...) are skipped, and the next word of four or more characters is the
value, unless it is a placeholder or one of a few stopwords. The trade-off is
deliberate: prose such as "password for the bank forgotten" may block (the word
after the connector is taken as a value). The detector fails closed. A marker
followed at once by a comma or period never matches.

A value on the line after the marker counts only when the line break directly
follows the marker (spaces allowed), and the first word of that line must
itself be a value: no connector is skipped. So "password" then a line starting
with "и пошёл" passes, while a line starting with an ordinary word of four or
more letters ("пошёл спать") is blocked.

Not markers: pin, secret and token. They are common words in ordinary prose
("secret santa", "a token gesture"), so adding them would block real requests.
"""

from __future__ import annotations

import re

from jarvis.personal_proxy.spans import Span

MIN_VALUE_LENGTH = 4
_MAX_STEPS = 5

_LATIN_START = r"(?:(?<![^\W_])|(?<=[a-z\d])(?=[A-Z]))"
_MARKER = re.compile(
    rf"{_LATIN_START}(?i:passwords?|passwd|passphrase|passcode|pass|pwd|api[_ -]?key)"
    r"(?![^\W_])"
    r"|(?i:парол\w*)"
)
_WORD = r"[\"'«]?(?P<word>[^\s,;\"'»)\]}]+)"
_NEXT = re.compile(r"(?:[ \t]*[\"'\]\)]?[ \t]*(?:=>|[:=\-\u2014(])\s*|[ \t]+)" + _WORD)
_AFTER_MARKER_LINE_BREAK = re.compile(r"[ \t]*\n[ \t]*" + _WORD)
_PLACEHOLDER = re.compile(r"<[A-Z_]+_\d+>")
_CONNECTORS = frozenset(
    {"is", "это", "-", "у", "меня", "мой", "моя", "my", "the", "а", "и"}
)
_CONNECTORS_WITH_OBJECT = frozenset({"от", "for", "of", "to", "на", "для"})
_STOPWORDS = frozenset(
    {
        "этот",
        "этого",
        "этой",
        "нужен",
        "нужно",
        "нужна",
        "который",
        "которая",
        "которое",
        "когда",
        "чтобы",
        "потом",
        "тоже",
        "that",
        "this",
        "with",
        "have",
        "your",
        "what",
        "which",
        "from",
        "here",
        "there",
        "when",
    }
)


def _is_value(word: str) -> bool:
    return (
        len(word) >= MIN_VALUE_LENGTH
        and word.casefold() not in _STOPWORDS
        and not _PLACEHOLDER.fullmatch(word)
    )


def _value_on_next_line(text: str, position: int) -> Span | None:
    match = _AFTER_MARKER_LINE_BREAK.match(text, position)
    if match is None or not _is_value(match.group("word")):
        return None
    return Span(match.start("word"), match.end("word"))


def _value_after(text: str, position: int) -> Span | None:
    on_next_line = _value_on_next_line(text, position)
    if on_next_line is not None:
        return on_next_line
    skip_object = False
    for _ in range(_MAX_STEPS):
        match = _NEXT.match(text, position)
        if match is None:
            return None
        position = match.end()
        word = match.group("word")
        if skip_object:
            skip_object = False
            continue
        lowered = word.casefold().rstrip(":=")
        if lowered in _CONNECTORS:
            continue
        if lowered in _CONNECTORS_WITH_OBJECT:
            skip_object = True
            continue
        if _is_value(word):
            return Span(match.start("word"), match.end("word"))
        return None
    return None


def find_passwords(text: str) -> list[Span]:
    spans = (_value_after(text, m.end()) for m in _MARKER.finditer(text))
    return [span for span in spans if span is not None]
