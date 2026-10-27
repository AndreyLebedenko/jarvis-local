"""How the page tells a default system prompt from a changed one.

The server decides, so the page keeps no copy of the prompt. Nothing here
changes what is stored: it only reads a sent record and splits it for display."""

from __future__ import annotations

from jarvis.personal_proxy.common.payload import (
    DEFAULT_SYSTEM_PROMPT,
    VOICE_SYSTEM_PROMPT,
)
from jarvis.personal_proxy.confirmation.confirmation_blocks import SentBlock

_KNOWN_SYSTEM_PROMPTS = (DEFAULT_SYSTEM_PROMPT, VOICE_SYSTEM_PROMPT)
_BLOCK_SEPARATOR = "\n\n"


def has_default_system_prompt(messages: tuple[tuple[str, str], ...]) -> bool:
    """True for any system message Jarvis composes itself: the default prompt
    or the default prompt with the voice contract."""
    return bool(messages) and messages[0] in {
        ("system", prompt) for prompt in _KNOWN_SYSTEM_PROMPTS
    }


def split_known_system_prompt(stored_text: str) -> tuple[str, str] | None:
    """The known system prompt a sent record starts with and the rest of its
    text, or None when the record starts with anything else."""
    # The record keeps only the joined text, so this relies on the system
    # prompts being constants that never embed a blank line and a role line.
    for prompt in _KNOWN_SYSTEM_PROMPTS:
        prefix = SentBlock((("system", prompt),)).text + _BLOCK_SEPARATOR
        if stored_text.startswith(prefix):
            return prompt, stored_text[len(prefix) :]
    return None


def request_after_default_system_prompt(stored_text: str) -> str | None:
    split = split_known_system_prompt(stored_text)
    return None if split is None else split[1]
