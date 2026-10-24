"""Whether a text holds anything a reader or a model could see."""

from __future__ import annotations

from jarvis.personal_proxy.common.normalize import normalize_message


def has_visible_text(text: str) -> bool:
    return bool(normalize_message(text).text.strip())
