"""Incremental Russian/English segmentation by character set.

This module is deliberately narrower than language detection. Jarvis v1.2.8
only needs to split Russian and English text, whose primary alphabets do not
overlap: Cyrillic means Russian, Latin means English. Digits, whitespace, and
punctuation are neutral and are attached to the nearest surrounding text.
"""

from dataclasses import dataclass

DEFAULT_LANGUAGE = "ru"
ENGLISH = "en"


@dataclass(frozen=True)
class LanguageSegment:
    language: str
    text: str


class CharsetLanguageStream:
    def __init__(self) -> None:
        self._language: str | None = None
        self._neutral = ""

    def feed(self, text: str) -> list[LanguageSegment]:
        segments: list[LanguageSegment] = []
        for char in text:
            language = _char_language(char)
            if language is None:
                self._neutral += char
                continue
            if self._language is None:
                self._language = language
                self._emit(segments, language, self._neutral + char)
                continue
            if language == self._language:
                self._emit(segments, language, self._neutral + char)
                continue
            self._emit(segments, self._language, self._neutral)
            self._language = language
            self._emit(segments, language, char)
        if (
            self._language is not None
            and self._neutral
            and self._neutral[-1].isspace()
        ):
            self._emit(segments, self._language, self._neutral)
        return segments

    def close(self) -> list[LanguageSegment]:
        segments: list[LanguageSegment] = []
        self._emit(segments, self._language or DEFAULT_LANGUAGE, self._neutral)
        self._neutral = ""
        return segments

    def reset(self) -> None:
        self._language = None
        self._neutral = ""

    def _emit(self, segments: list[LanguageSegment], language: str, text: str) -> None:
        if text:
            segments.append(LanguageSegment(language, text))
        self._neutral = ""


def segment_by_charset(text: str) -> list[LanguageSegment]:
    stream = CharsetLanguageStream()
    return _merge_adjacent([*stream.feed(text), *stream.close()])


def _merge_adjacent(segments: list[LanguageSegment]) -> list[LanguageSegment]:
    merged: list[LanguageSegment] = []
    for segment in segments:
        if not segment.text.strip():
            continue
        if merged and merged[-1].language == segment.language:
            previous = merged[-1]
            merged[-1] = LanguageSegment(previous.language, previous.text + segment.text)
        else:
            merged.append(segment)
    return [
        LanguageSegment(segment.language, segment.text.strip())
        for segment in merged
        if segment.text.strip()
    ]


def _char_language(char: str) -> str | None:
    if _is_cyrillic(char):
        return DEFAULT_LANGUAGE
    if _is_latin(char):
        return ENGLISH
    return None


def _is_cyrillic(char: str) -> bool:
    return (
        "\u0400" <= char <= "\u04ff"
        or "\u0500" <= char <= "\u052f"
        or "\u2de0" <= char <= "\u2dff"
        or "\ua640" <= char <= "\ua69f"
    )


def _is_latin(char: str) -> bool:
    return (
        "A" <= char <= "Z"
        or "a" <= char <= "z"
        or "\u00c0" <= char <= "\u024f"
        or "\u1e00" <= char <= "\u1eff"
    )
