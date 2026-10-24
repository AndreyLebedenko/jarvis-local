"""How the page tells a default system prompt from a changed one.

The server decides, so the page keeps no copy of the prompt. Nothing here
changes what is stored: it only reads a sent record and splits it for display."""

from __future__ import annotations

from jarvis.personal_proxy.common.payload import DEFAULT_SYSTEM_PROMPT
from jarvis.personal_proxy.confirmation.confirmation_blocks import SentBlock

_DEFAULT_SYSTEM_MESSAGE = ("system", DEFAULT_SYSTEM_PROMPT)
_BLOCK_SEPARATOR = "\n\n"


def has_default_system_prompt(messages: tuple[tuple[str, str], ...]) -> bool:
    return bool(messages) and messages[0] == _DEFAULT_SYSTEM_MESSAGE


def request_after_default_system_prompt(stored_text: str) -> str | None:
    """The stored text of a sent record minus its default system message, or
    None when the record starts with anything else."""
    # The record keeps only the joined text, so this relies on the system
    # prompt being a constant that never embeds a blank line and a role line.
    prefix = SentBlock((_DEFAULT_SYSTEM_MESSAGE,)).text + _BLOCK_SEPARATOR
    if not stored_text.startswith(prefix):
        return None
    return stored_text[len(prefix) :]
