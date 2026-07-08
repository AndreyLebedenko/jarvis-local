"""Pure parser for Jarvis's small speech-markup subset.

This is not an SSML implementation. It only treats optional <speak> and
<lang xml:lang="ru|en"> as Jarvis routing metadata, strips those controls
from spoken text, and returns language-tagged text segments for later TTS
routing.
"""

import re
from dataclasses import dataclass
from html.parser import HTMLParser

DEFAULT_LANGUAGE = "ru"
SUPPORTED_LANGUAGES = {"ru", "en"}

_KNOWN_CONTROL_RE = re.compile(
    r"</?(?:speak|lang)(?:\s+[^<>]*)?>?|xml:lang\s*=\s*['\"][^'\"]*['\"]?",
    re.IGNORECASE,
)
_MALFORMED_LANG_START_RE = re.compile(
    r"<lang\b[^<>]*?(?:xml:lang|lang)\s*=\s*['\"][^'\"]*['\"]",
    re.IGNORECASE,
)
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class SpeechSegment:
    language: str
    text: str


def parse_speech_markup(text: str) -> list[SpeechSegment]:
    if _has_malformed_control_tag(text):
        cleaned = _clean_malformed_markup(text)
        return [SpeechSegment(DEFAULT_LANGUAGE, cleaned)] if cleaned else []
    parser = _SpeechMarkupParser()
    parser.feed(text)
    parser.close()
    return _smooth_punctuation(_merge_adjacent(parser.segments))


class _SpeechMarkupParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._language_stack = [DEFAULT_LANGUAGE]
        self.segments: list[SpeechSegment] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "lang":
            self._language_stack.append(_language_from_attrs(attrs))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "lang" and len(self._language_stack) > 1:
            self._language_stack.pop()

    def handle_data(self, data: str) -> None:
        cleaned = _clean_text(data)
        if cleaned:
            self.segments.append(SpeechSegment(self._language_stack[-1], cleaned))


def _language_from_attrs(attrs: list[tuple[str, str | None]]) -> str:
    for name, value in attrs:
        if name.lower() in {"xml:lang", "lang"} and value is not None:
            return _normalize_language(value)
    return DEFAULT_LANGUAGE


def _normalize_language(value: str) -> str:
    base = value.replace("_", "-").split("-", maxsplit=1)[0].lower()
    if base in SUPPORTED_LANGUAGES:
        return base
    return DEFAULT_LANGUAGE


def _clean_text(text: str) -> str:
    without_controls = _KNOWN_CONTROL_RE.sub("", text)
    return _WHITESPACE_RE.sub(" ", without_controls).strip()


def _has_malformed_control_tag(text: str) -> bool:
    for match in re.finditer(r"<(?:speak|lang)\b", text, re.IGNORECASE):
        next_close = text.find(">", match.end())
        next_open = text.find("<", match.end())
        if next_close == -1 or (next_open != -1 and next_open < next_close):
            return True
    return False


def _clean_malformed_markup(text: str) -> str:
    text = _MALFORMED_LANG_START_RE.sub("", text)
    return _clean_text(text)


def _merge_adjacent(segments: list[SpeechSegment]) -> list[SpeechSegment]:
    merged: list[SpeechSegment] = []
    for segment in segments:
        if not segment.text:
            continue
        if merged and merged[-1].language == segment.language:
            previous = merged[-1]
            merged[-1] = SpeechSegment(
                previous.language, _join_text(previous.text, segment.text)
            )
        else:
            merged.append(segment)
    return merged


def _smooth_punctuation(segments: list[SpeechSegment]) -> list[SpeechSegment]:
    smoothed: list[SpeechSegment] = []
    pending_prefix = ""
    for segment in segments:
        if _is_punctuation_only(segment.text):
            if smoothed:
                previous = smoothed[-1]
                smoothed[-1] = SpeechSegment(previous.language, previous.text + segment.text)
            else:
                pending_prefix += segment.text
            continue
        text = pending_prefix + segment.text
        pending_prefix = ""
        smoothed.append(SpeechSegment(segment.language, text))
    if pending_prefix and smoothed:
        previous = smoothed[-1]
        smoothed[-1] = SpeechSegment(previous.language, previous.text + pending_prefix)
    return smoothed


def _is_punctuation_only(text: str) -> bool:
    return bool(text) and all(not char.isalnum() for char in text)


def _join_text(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    if right[0] in ".,!?;:)」]" or left[-1] in "([「":
        return left + right
    return f"{left} {right}"
