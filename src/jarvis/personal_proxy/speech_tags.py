"""Removes the speech layer's control tags from text that came from outside, so
that the text cannot steer how it is spoken. Only the four tags of
`jarvis.audio.speech_markup` are touched; any other angle-bracket text stays.

Every sentence is spoken by its own call, so a tag cut by a sentence boundary
must not survive in either half: a control tag that is not closed is removed to
the end of the text, and so is a leading attribute tail such as `xml:lang="en">`
that the end of a cut tag would leave at the start of the next sentence."""

from __future__ import annotations

import re

_CONTROL_TAG = re.compile(r"</?(?:speak|lang)\b[^>]*>?", re.IGNORECASE)
_LEADING_ATTRIBUTE_TAIL = re.compile(
    r"^[^<>]*?(?:xml:)?lang\s*=\s*[\"'][^\"']*[\"']\s*/?>", re.IGNORECASE
)


def strip_speech_control_tags(text: str) -> str:
    while True:
        stripped = _CONTROL_TAG.sub("", _LEADING_ATTRIBUTE_TAIL.sub("", text))
        if stripped == text:
            return text
        text = stripped
