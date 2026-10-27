"""Loads the local-only list of public names the sanitize pass must keep. One
name per line; comment and blank lines are dropped. The names go into the
sanitize prompt and nowhere else; no error carries them or the OS error text."""

from __future__ import annotations

from jarvis.core.config import PersonalProxySettings
from jarvis.personal_proxy.gate.local_text_file import read_local_text

MAX_PUBLIC_NAMES_CHARACTERS = 8000
_COMMENT_MARK = "#"


class PublicNamesFileError(Exception):
    """The configured public names file cannot be read as UTF-8 text."""


def load_public_names(settings: PersonalProxySettings) -> str:
    text = read_local_text(
        settings.public_names_file,
        PersonalProxySettings().public_names_file,
        description="public names file",
        max_characters=MAX_PUBLIC_NAMES_CHARACTERS,
        error_type=PublicNamesFileError,
    )
    lines = (line.strip() for line in text.splitlines())
    return "\n".join(
        line for line in lines if line and not line.startswith(_COMMENT_MARK)
    )
