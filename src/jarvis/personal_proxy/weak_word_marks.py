"""Marks the words the engine was unsure of, for the check request."""

from __future__ import annotations

import re
from collections.abc import Sequence

from jarvis.personal_proxy.stt_result import Word

WEAK_WORD_MARK = "[?]"
_MARK_WITH_PRECEDING_BLANKS = re.compile(r"[ 	]*" + re.escape(WEAK_WORD_MARK))


def mark_weak_words(words: Sequence[Word], threshold: float) -> str:
    return " ".join(
        word.word + WEAK_WORD_MARK if word.probability < threshold else word.word
        for word in words
    )


def strip_weak_word_marks(text: str) -> str:
    return _MARK_WITH_PRECEDING_BLANKS.sub("", text)
