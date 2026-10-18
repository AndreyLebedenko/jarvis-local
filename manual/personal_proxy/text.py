"""Text primitives of tasks/spike-v2.1.0-1-combined-transcribe-sanitize.md.

Pure functions shared by the scorer: normalization, tokenization, Russian
number-word canonicalization, word error rate, and the declension-tolerant
stem match used to decide whether a sensitive span leaked.
"""

from __future__ import annotations

import re

_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)

MIN_STEM_LENGTH = 3
STEM_ENDING_LENGTH = 2

_UNITS = {
    "ноль": 0,
    "один": 1,
    "одна": 1,
    "одно": 1,
    "два": 2,
    "две": 2,
    "три": 3,
    "четыре": 4,
    "пять": 5,
    "шесть": 6,
    "семь": 7,
    "восемь": 8,
    "девять": 9,
}
_TEENS = {
    "десять": 10,
    "одиннадцать": 11,
    "двенадцать": 12,
    "тринадцать": 13,
    "четырнадцать": 14,
    "пятнадцать": 15,
    "шестнадцать": 16,
    "семнадцать": 17,
    "восемнадцать": 18,
    "девятнадцать": 19,
}
_TENS = {
    "двадцать": 20,
    "тридцать": 30,
    "сорок": 40,
    "пятьдесят": 50,
    "шестьдесят": 60,
    "семьдесят": 70,
    "восемьдесят": 80,
    "девяносто": 90,
}
_HUNDREDS = {
    "сто": 100,
    "двести": 200,
    "триста": 300,
    "четыреста": 400,
    "пятьсот": 500,
    "шестьсот": 600,
    "семьсот": 700,
    "восемьсот": 800,
    "девятьсот": 900,
}

_NUMBER_WORDS: dict[str, tuple[str, int]] = {
    **{word: ("units", value) for word, value in _UNITS.items()},
    **{word: ("teens", value) for word, value in _TEENS.items()},
    **{word: ("tens", value) for word, value in _TENS.items()},
    **{word: ("hundreds", value) for word, value in _HUNDREDS.items()},
}

# A number word may extend the number being built only along the descending
# Russian pattern hundreds -> tens/teens/units, tens -> units. Anything else
# starts a new number, which is how "8 915 234 56 78" read as words splits.
_CAN_FOLLOW = {
    "hundreds": {"tens", "teens", "units"},
    "tens": {"units"},
    "teens": set(),
    "units": set(),
}


def normalize_text(text: str) -> str:
    folded = text.casefold().replace("ё", "е")
    return _NON_WORD.sub(" ", folded).strip()


def tokenize(text: str) -> list[str]:
    normalized = normalize_text(text)
    return normalized.split() if normalized else []


def canonicalize_numbers(tokens: list[str]) -> list[str]:
    """Replaces runs of Russian number words with one digit token per number.

    Thousands and larger are not parsed: the corpus reads long numbers in
    groups, and an unparsed word is left as it is.
    """
    result: list[str] = []
    value: int | None = None
    previous_kind = ""
    for token in tokens:
        entry = _NUMBER_WORDS.get(token)
        if entry is None:
            if value is not None:
                result.append(str(value))
                value = None
            result.append(token)
            continue
        kind, amount = entry
        if value is not None and kind in _CAN_FOLLOW[previous_kind]:
            value += amount
        else:
            if value is not None:
                result.append(str(value))
            value = amount
        previous_kind = kind
    if value is not None:
        result.append(str(value))
    return result


def canonical_tokens(text: str) -> list[str]:
    return canonicalize_numbers(tokenize(text))


def digit_runs(text: str) -> list[str]:
    """Maximal runs of consecutive digit tokens, joined into digit strings."""
    runs: list[str] = []
    current: list[str] = []
    for token in canonical_tokens(text):
        if token.isdigit():
            current.append(token)
        elif current:
            runs.append("".join(current))
            current = []
    if current:
        runs.append("".join(current))
    return runs


def stem(token: str) -> str:
    return token[: max(MIN_STEM_LENGTH, len(token) - STEM_ENDING_LENGTH)]


def stem_present(form: str, tokens: list[str]) -> bool:
    prefix = stem(form)
    return any(token.startswith(prefix) for token in tokens)


def wer_tokens(text: str) -> list[str]:
    """Canonical tokens with each run of digit tokens merged into one token,
    so "4276 1234" and "четыре два семь шесть, один два три четыре" compare
    equal: how a number is grouped says nothing about how well it was heard."""
    merged: list[str] = []
    run: list[str] = []
    for token in canonical_tokens(text):
        if token.isdigit():
            run.append(token)
            continue
        if run:
            merged.append("".join(run))
            run = []
        merged.append(token)
    if run:
        merged.append("".join(run))
    return merged


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref = wer_tokens(reference)
    hyp = wer_tokens(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return _edit_distance(ref, hyp) / len(ref)


def _edit_distance(ref: list[str], hyp: list[str]) -> int:
    previous = list(range(len(hyp) + 1))
    for i, ref_token in enumerate(ref, start=1):
        current = [i]
        for j, hyp_token in enumerate(hyp, start=1):
            cost = 0 if ref_token == hyp_token else 1
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            )
        previous = current
    return previous[-1]
