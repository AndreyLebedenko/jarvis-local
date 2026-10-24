"""The closed vocabulary of confirmation answers and the classifier over it.

Only a whole utterance made of one vocabulary phrase counts; any extra word
makes the answer unclear, and an unclear answer sends nothing. Hidden or joining
characters and punctuation separate words instead of vanishing, so a phrase
cannot be assembled from pieces ("y-e-s"), and a question mark makes any answer
unclear (a hesitant "Да?" is not a clear yes)."""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum


class AnswerKind(StrEnum):
    YES = "yes"
    NO = "no"
    UNCLEAR = "unclear"


YES_PHRASES = frozenset(
    {
        "да",
        "да отправляй",
        "отправляй",
        "отправь",
        "давай",
        "ок",
        "окей",
        "верно",
        "подтверждаю",
        "yes",
        "send",
        "send it",
        "ok",
        "okay",
        "confirm",
    }
)

NO_PHRASES = frozenset(
    {
        "нет",
        "не надо",
        "не отправляй",
        "стоп",
        "отмена",
        "no",
        "stop",
        "cancel",
        "dont send",
    }
)

_QUESTION_MARKS = ("?", "？", "؟", ";")
_CONTRACTION_APOSTROPHE = re.compile(r"(?<=n)['’](?=t(?:\s|$))")


def _normalize(text: str) -> str:
    composed = unicodedata.normalize("NFC", text).casefold().replace("ё", "е")
    contracted = _CONTRACTION_APOSTROPHE.sub("", composed)
    separated = "".join(ch if ch.isalnum() else " " for ch in contracted)
    return " ".join(separated.split())


def classify_answer(text: str) -> AnswerKind:
    if not isinstance(text, str) or any(mark in text for mark in _QUESTION_MARKS):
        return AnswerKind.UNCLEAR
    phrase = _normalize(text)
    if phrase in YES_PHRASES:
        return AnswerKind.YES
    if phrase in NO_PHRASES:
        return AnswerKind.NO
    return AnswerKind.UNCLEAR
