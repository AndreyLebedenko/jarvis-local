"""Reads a local-only text file for the sanitize prompt. Its content goes into
that prompt and nowhere else; no error carries it or the OS error text."""

from __future__ import annotations

from pathlib import Path


def read_local_text(
    configured_path: str,
    default_path: str,
    *,
    description: str,
    max_characters: int,
    error_type: type[Exception],
) -> str:
    is_default = configured_path == default_path
    try:
        # utf-8-sig: Notepad saves a BOM, which is not part of the first line.
        text = Path(configured_path).read_bytes().decode("utf-8-sig")
    except FileNotFoundError:
        if is_default:
            return ""
        raise error_type(f"the configured {description} does not exist") from None
    except (OSError, ValueError):
        raise error_type(f"the {description} cannot be read as UTF-8") from None
    if len(text) > max_characters:
        raise error_type(f"the {description} is too long for the prompt")
    return text
