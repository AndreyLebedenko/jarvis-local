"""What may be sent as an API key: printable ASCII, nothing else."""

from __future__ import annotations

from jarvis.personal_proxy.external_error import ExternalErrorKind

_FIRST_PRINTABLE = 0x21
_LAST_PRINTABLE = 0x7E


def key_problem(value: str) -> ExternalErrorKind | None:
    """Never echoes the value."""
    key = value.strip()
    if not key:
        return ExternalErrorKind.KEY_MISSING
    if any(not _FIRST_PRINTABLE <= ord(char) <= _LAST_PRINTABLE for char in key):
        return ExternalErrorKind.KEY_INVALID
    return None
