"""Loads the local-only topics text. Its content goes into the sanitize prompt
and nowhere else; no error carries it or the OS error text."""

from __future__ import annotations

from jarvis.core.config import PersonalProxySettings
from jarvis.personal_proxy.gate.local_text_file import read_local_text

MAX_TOPICS_CHARACTERS = 8000


class TopicsFileError(Exception):
    """The configured topics file cannot be read as UTF-8 text."""


def load_topics(settings: PersonalProxySettings) -> str:
    return read_local_text(
        settings.topics_file,
        PersonalProxySettings().topics_file,
        description="topics file",
        max_characters=MAX_TOPICS_CHARACTERS,
        error_type=TopicsFileError,
    )
