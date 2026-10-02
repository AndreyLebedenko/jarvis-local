"""The bearer token of the --mcp-mode server, kept in `[mcp_mode].token_file`.

The file is created once and reused, so an MCP client configured with the
token keeps working across runs; deleting the file rotates the token. A broken
file is an error, never a silent regeneration, which would break the client's
stored configuration without telling the user. The token itself never appears
in a log record or an exception message.
"""

from __future__ import annotations

import logging
import secrets
from pathlib import Path

logger = logging.getLogger(__name__)

TOKEN_FILE_CONFIG_KEY = "[mcp_mode].token_file"
_TOKEN_BYTES = 32
_ENCODING = "utf-8"


class McpTokenFileError(Exception):
    """The token file cannot provide a token. The message names the file and
    the config key, never the file's content."""

    def __init__(self, token_file: Path, problem: str) -> None:
        super().__init__(
            f"MCP mode token file {token_file} ({TOKEN_FILE_CONFIG_KEY}) {problem}"
        )
        self.token_file = token_file


def load_or_create_token(token_file: Path) -> str:
    """Returns the token stored in `token_file`, creating the file with a new
    token if it does not exist. A relative path is relative to the working
    directory."""
    try:
        content = token_file.read_text(encoding=_ENCODING)
    except FileNotFoundError:
        return _create_token_file(token_file)
    except UnicodeDecodeError:
        # from None: the decode error carries the file's bytes, i.e. the token.
        raise McpTokenFileError(token_file, "is not valid UTF-8 text") from None
    except OSError as error:
        raise McpTokenFileError(
            token_file, f"cannot be read: {error.strerror}"
        ) from error
    token = content.strip()
    if not token:
        raise McpTokenFileError(
            token_file, "is empty; delete it to generate a new token"
        )
    return token


def _create_token_file(token_file: Path) -> str:
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    try:
        token_file.parent.mkdir(parents=True, exist_ok=True)
        with token_file.open("x", encoding=_ENCODING) as stream:
            stream.write(token)
    except OSError as error:
        raise McpTokenFileError(
            token_file, f"cannot be created: {error.strerror}"
        ) from error
    logger.info("Created MCP mode token file %s", token_file)
    return token
