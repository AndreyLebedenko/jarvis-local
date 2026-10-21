"""Loads the local-only topics text. Its content goes into the sanitize prompt
and nowhere else; no error carries it or the OS error text."""

from __future__ import annotations

from pathlib import Path

from jarvis.core.config import PersonalProxySettings

MAX_TOPICS_CHARACTERS = 8000


class TopicsFileError(Exception):
    """The configured topics file cannot be read as UTF-8 text."""


def load_topics(settings: PersonalProxySettings) -> str:
    path = Path(settings.topics_file)
    is_default = settings.topics_file == PersonalProxySettings().topics_file
    try:
        # utf-8-sig: Notepad saves a BOM, which is not part of the first topic.
        text = path.read_bytes().decode("utf-8-sig")
    except FileNotFoundError:
        if is_default:
            return ""
        raise TopicsFileError("the configured topics file does not exist") from None
    except (OSError, ValueError):
        raise TopicsFileError("the topics file cannot be read as UTF-8") from None
    if len(text) > MAX_TOPICS_CHARACTERS:
        raise TopicsFileError("the topics file is too long for the prompt")
    return text
