"""The commands a typed request can start with. Pure text in, a parse result out.

A command is the first token of the text: a slash and letters only. A known one
(lowercase, from `COMMAND_TABLE`) carries the text after it; a token that looks
like a command and is not known is flagged, so that a typo is never sent as an
ordinary request. Any other leading slash (a path, a lone slash) is ordinary
text. A further command is a new `Command` member and a table entry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from jarvis.personal_proxy.visible_text import has_visible_text


class Command(StrEnum):
    FORCE = "force"


class ParsedKind(StrEnum):
    ORDINARY = "ordinary"
    COMMAND = "command"
    EMPTY_COMMAND = "empty_command"
    UNKNOWN_COMMAND = "unknown_command"


COMMAND_TABLE: Mapping[str, Command] = MappingProxyType(
    {"force": Command.FORCE, "f": Command.FORCE}
)


@dataclass(frozen=True)
class ParsedRequest:
    kind: ParsedKind
    command: Command | None = None
    text: str = field(default="", repr=False)


def parse_typed_request(typed: str) -> ParsedRequest:
    head, rest = _split_first_token(typed)
    if not _looks_like_command(head):
        return ParsedRequest(ParsedKind.ORDINARY, text=typed)
    command = COMMAND_TABLE.get(head[1:])
    if command is None:
        return ParsedRequest(ParsedKind.UNKNOWN_COMMAND)
    text = rest.strip()
    if not has_visible_text(text):
        return ParsedRequest(ParsedKind.EMPTY_COMMAND, command)
    return ParsedRequest(ParsedKind.COMMAND, command, text)


def _looks_like_command(token: str) -> bool:
    return token.startswith("/") and token[1:].isalpha()


def _split_first_token(typed: str) -> tuple[str, str]:
    parts = typed.split(maxsplit=1)
    if not parts:
        return "", ""
    return parts[0], parts[1] if len(parts) > 1 else ""
