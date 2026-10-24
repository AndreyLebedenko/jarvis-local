"""Bounded line splitting of a raw byte stream.

The raw (not decoded) bytes are used on purpose: a compressed answer must not
expand beyond the caps.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator

from jarvis.personal_proxy.external.external_error import (
    ExternalClientError,
    ExternalErrorKind,
)

_BOM = "﻿"


def _decode(raw: bytes | bytearray) -> str:
    line = bytes(raw).decode("utf-8", errors="replace")
    return line[:-1] if line.endswith("\r") else line


async def iter_lines(
    chunks: AsyncIterable[bytes], max_line_bytes: int
) -> AsyncIterator[str]:
    """Raises TOO_LARGE as soon as one line exceeds the cap, without reading on."""
    buffer = bytearray()
    first = True
    async for chunk in chunks:
        buffer += chunk
        while (newline := buffer.find(b"\n")) != -1:
            if newline > max_line_bytes:
                buffer.clear()
                raise ExternalClientError(ExternalErrorKind.TOO_LARGE)
            line = _decode(buffer[:newline])
            del buffer[: newline + 1]
            yield line.removeprefix(_BOM) if first else line
            first = False
        if len(buffer) > max_line_bytes:
            buffer.clear()
            raise ExternalClientError(ExternalErrorKind.TOO_LARGE)
    if buffer:
        line = _decode(buffer)
        yield line.removeprefix(_BOM) if first else line
