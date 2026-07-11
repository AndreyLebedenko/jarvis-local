"""Pure scanner for Jarvis's small speech-markup subset.

This is not an SSML implementation. Exactly four control tokens are
recognized as Jarvis routing metadata - <speak ...>, </speak>,
<lang ...>, </lang> (with xml:lang/lang attributes) - stripped from
spoken text, and turned into language-tagged segments. Anything else
that merely looks like markup ("List<String>", "<div>", "a < b") is
preserved as literal spoken text: an assistant answering a code
question must never lose content to a markup parser.

SpeechMarkupStream is an incremental tokenizer: feed() accepts text in
arbitrary chunks (an unterminated "<..." tail is held back until more
input or close() decides), so the TTS buffering integration can route
language segments during token streaming and use a closing </lang> as
a flush boundary. feed()/close() return raw pieces in input order;
parse_speech_markup() is the one-shot wrapper that also cleans
whitespace, merges adjacent same-language pieces, and smooths
punctuation-only fragments into their neighbors.
"""

import logging
import re
from dataclasses import dataclass

DEFAULT_LANGUAGE = "ru"
SUPPORTED_LANGUAGES = {"ru", "en"}
logger = logging.getLogger(__name__)

_CONTROL_NAME_RE = re.compile(r"</?(?:speak|lang)\b", re.IGNORECASE)
_LANG_ATTR_RE = re.compile(r"(?:xml:)?lang\s*=\s*['\"]([^'\"]*)['\"]", re.IGNORECASE)
_LANG_ATTR_STRIP_RE = re.compile(
    r"(?:xml:)?lang\s*=\s*['\"][^'\"]*['\"]?", re.IGNORECASE
)
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class SpeechSegment:
    language: str
    text: str


def parse_speech_markup(text: str) -> list[SpeechSegment]:
    stream = SpeechMarkupStream()
    pieces = stream.feed(text) + stream.close()
    cleaned = [
        SpeechSegment(piece.language, cleaned_text)
        for piece in pieces
        if (cleaned_text := _clean_text(piece.text))
    ]
    return _smooth_punctuation(_merge_adjacent(cleaned))


def speech_markup_to_text(text: str) -> str:
    rendered = ""
    for segment in parse_speech_markup(text):
        rendered = _join_text(rendered, segment.text)
    return rendered


class SpeechMarkupStream:
    """Incremental control-token scanner over streamed text.

    Emits raw SpeechSegment pieces (whitespace untouched) tagged with the
    language active where the text appeared. A malformed known control tag
    (e.g. `<lang xml:lang="en"Hello`) is softly dropped from the text
    without changing the active language, so control junk is never spoken
    but real words glued to it survive.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._languages = [DEFAULT_LANGUAGE]

    def feed(self, text: str) -> list[SpeechSegment]:
        self._buffer += text
        pieces: list[SpeechSegment] = []
        while True:
            angle = self._buffer.find("<")
            if angle == -1:
                self._emit(pieces, self._buffer)
                self._buffer = ""
                break
            if angle > 0:
                self._emit(pieces, self._buffer[:angle])
                self._buffer = self._buffer[angle:]
            close = self._buffer.find(">")
            reopen = self._buffer.find("<", 1)
            if close != -1 and (reopen == -1 or close < reopen):
                token = self._buffer[: close + 1]
                self._buffer = self._buffer[close + 1 :]
                self._handle_token(pieces, token)
                continue
            if reopen == -1:
                # Unterminated "<..." tail: more input may complete it.
                break
            fragment = self._buffer[:reopen]
            self._buffer = self._buffer[reopen:]
            self._emit_broken_fragment(pieces, fragment)
        return pieces

    def close(self) -> list[SpeechSegment]:
        """Flushes a held-back unterminated tail at end of input."""
        tail, self._buffer = self._buffer, ""
        pieces: list[SpeechSegment] = []
        if tail:
            self._emit_broken_fragment(pieces, tail)
        return pieces

    def _handle_token(self, pieces: list[SpeechSegment], token: str) -> None:
        if not _CONTROL_NAME_RE.match(token):
            # Well-formed but unknown tag-like text ("<String>", "<div>"):
            # literal spoken content, not markup.
            self._emit(pieces, token)
            return
        if token.startswith("</"):
            if "lang" in token.lower():
                if len(self._languages) > 1:
                    self._languages.pop()
                else:
                    logger.warning(
                        "Ignoring unmatched speech markup closing tag: %s", token
                    )
            return
        if token.lower().startswith("<lang"):
            self._languages.append(_language_from_token(token))

    def _emit_broken_fragment(self, pieces: list[SpeechSegment], fragment: str) -> None:
        """A "<..." run that never closed. Known control junk is stripped
        (soft fallback - never spoken, never changes language); anything
        else is literal text."""
        if _CONTROL_NAME_RE.match(fragment):
            logger.warning(
                "Ignoring malformed speech markup control fragment: %s", fragment
            )
            fragment = _CONTROL_NAME_RE.sub("", fragment, count=1)
            fragment = _LANG_ATTR_STRIP_RE.sub("", fragment)
        self._emit(pieces, fragment)

    def _emit(self, pieces: list[SpeechSegment], text: str) -> None:
        if text:
            pieces.append(SpeechSegment(self._languages[-1], text))


def _language_from_token(token: str) -> str:
    match = _LANG_ATTR_RE.search(token)
    if match is None:
        logger.warning("Speech markup lang tag has no language attribute: %s", token)
        return DEFAULT_LANGUAGE
    return _normalize_language(match.group(1))


def _normalize_language(value: str) -> str:
    base = value.replace("_", "-").split("-", maxsplit=1)[0].lower()
    if base in SUPPORTED_LANGUAGES:
        return base
    logger.warning(
        "Unsupported speech markup language %r; falling back to %s",
        value,
        DEFAULT_LANGUAGE,
    )
    return DEFAULT_LANGUAGE


def _clean_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


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
                smoothed[-1] = SpeechSegment(
                    previous.language, previous.text + segment.text
                )
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
