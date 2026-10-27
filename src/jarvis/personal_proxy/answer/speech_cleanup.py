import re

_HARD = "hard"
_STRESSED = "stressed"
_SOFT = "soft"

_ENDINGS = {
    _HARD: ("ый", "ого", "ому", "ым", "ом", "ых", "ым", "ыми", "ых"),
    _STRESSED: ("ой", "ого", "ому", "ым", "ом", "ых", "ым", "ыми", "ых"),
    _SOFT: ("ий", "ьего", "ьему", "ьим", "ьем", "ьих", "ьим", "ьими", "ьих"),
}

_CENTURY_FORMS = {
    "век": 0,
    "века": 1,
    "веку": 2,
    "веком": 3,
    "веке": 4,
    "веков": 5,
    "векам": 6,
    "веками": 7,
    "веках": 8,
}

_ORDINAL_STEMS = {
    1: ("перв", _HARD),
    2: ("втор", _STRESSED),
    3: ("трет", _SOFT),
    4: ("четвёрт", _HARD),
    5: ("пят", _HARD),
    6: ("шест", _STRESSED),
    7: ("седьм", _STRESSED),
    8: ("восьм", _STRESSED),
    9: ("девят", _HARD),
    10: ("десят", _HARD),
    11: ("одиннадцат", _HARD),
    12: ("двенадцат", _HARD),
    13: ("тринадцат", _HARD),
    14: ("четырнадцат", _HARD),
    15: ("пятнадцат", _HARD),
    16: ("шестнадцат", _HARD),
    17: ("семнадцат", _HARD),
    18: ("восемнадцат", _HARD),
    19: ("девятнадцат", _HARD),
    20: ("двадцат", _HARD),
    30: ("тридцат", _HARD),
}

_ROMAN_VALUE = re.compile(r"(?P<tens>X{0,3})(?P<units>IX|IV|V?I{0,3})")
_ROMAN_UNITS = {"": 0, "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}
_ROMAN_UNITS.update({"VI": 6, "VII": 7, "VIII": 8, "IX": 9})
_MAX_CENTURY = 30
_TWENTY_CARDINAL = "двадцать"

_CENTURY_FORM_PATTERN = "|".join(sorted(_CENTURY_FORMS, key=len, reverse=True))
_CENTURY_NUMERAL = re.compile(
    rf"(?<![\w-])(?P<numeral>[IVX]+)(?=[  ](?P<form>{_CENTURY_FORM_PATTERN})(?!\w))"
)

_LINE_PREFIX = re.compile(r"^[ \t]*(?:(?:#{1,6}|[-*+]|\d+[.)])[ \t]+(?=\S)|>[ \t]*)+")
_LINK = re.compile(r"\[([^\]\n]+)\]\([^)\s]*\)")
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_STAR_EMPHASIS = re.compile(r"(?<![\w*])(\*{1,3})(?=[^\s*])(.+?)(?<=[^\s*])\1(?![\w*])")
_UNDERSCORE_EMPHASIS = re.compile(
    r"(?<![\w_])(_{1,3})(?=[^\s_])(.+?)(?<=[^\s_])\1(?![\w_])"
)
_SPACE_RUN = re.compile(r"[ \t]{2,}")


def clean_for_speech(text: str) -> str:
    current = text
    while True:
        cleaned = _replace_century_numerals(_strip_markdown(current))
        if cleaned == current:
            return cleaned
        current = cleaned


def _strip_markdown(text: str) -> str:
    return "\n".join(_strip_markdown_line(line) for line in text.split("\n"))


def _strip_markdown_line(line: str) -> str:
    stripped = _LINE_PREFIX.sub("", line)
    stripped = _LINK.sub(r"\1", stripped)
    stripped = _INLINE_CODE.sub(r"\1", stripped)
    stripped = _STAR_EMPHASIS.sub(r"\2", stripped)
    stripped = _UNDERSCORE_EMPHASIS.sub(r"\2", stripped)
    if stripped == line:
        return line
    return _SPACE_RUN.sub(" ", stripped)


def _replace_century_numerals(text: str) -> str:
    return _CENTURY_NUMERAL.sub(_century_ordinal, text)


def _century_ordinal(match: re.Match[str]) -> str:
    value = _roman_to_int(match.group("numeral"))
    if value is None:
        return match.group("numeral")
    return _ordinal(value, _CENTURY_FORMS[match.group("form")])


def _roman_to_int(numeral: str) -> int | None:
    parts = _ROMAN_VALUE.fullmatch(numeral)
    if parts is None:
        return None
    value = len(parts.group("tens")) * 10 + _ROMAN_UNITS[parts.group("units")]
    if not 1 <= value <= _MAX_CENTURY:
        return None
    return value


def _ordinal(value: int, case: int) -> str:
    if value in _ORDINAL_STEMS:
        return _inflect(value, case)
    return f"{_TWENTY_CARDINAL} {_inflect(value % 10, case)}"


def _inflect(value: int, case: int) -> str:
    stem, kind = _ORDINAL_STEMS[value]
    return stem + _ENDINGS[kind][case]
