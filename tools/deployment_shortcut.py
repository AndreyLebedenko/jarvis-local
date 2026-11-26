"""The Windows shortcut of a deployed home: its file name and icon."""

from __future__ import annotations

import unicodedata
from pathlib import Path

from jarvis.launcher.identity import LauncherIdentity, load_launcher_identity

DEFAULT_SHORTCUT_NAME = "Jarvis"
PACKAGED_ICON = Path("src/jarvis/launcher/assets/jarvis.ico")
MAX_STEM_UTF16_UNITS = 120
_SHORTCUT_SUFFIX = ".lnk"
_FORBIDDEN = frozenset('<>:"/\\|?*')
_DIGITS = "0123456789¹²³"
_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "CONIN$",
        "CONOUT$",
        *(f"{device}{digit}" for device in ("COM", "LPT") for digit in _DIGITS),
    }
)


def _is_unusable(character: str) -> bool:
    return character in _FORBIDDEN or unicodedata.category(character)[0] == "C"


def _cut_to_utf16_units(text: str, limit: int) -> str:
    used = 0
    for index, character in enumerate(text):
        used += 2 if ord(character) > 0xFFFF else 1
        if used > limit:
            return text[:index]
    return text


def _without_reserved_device(text: str) -> str:
    head, dot, rest = text.partition(".")
    if head.rstrip().upper() in _RESERVED:
        return head.rstrip() + "_" + dot + rest
    return text


def safe_file_stem(text: str) -> str:
    """A Windows file name stem: no forbidden or control characters, no
    leading spaces or trailing dots and spaces, no device name, at most
    MAX_STEM_UTF16_UNITS UTF-16 units, never empty."""
    cleaned = "".join("_" if _is_unusable(c) else c for c in text).lstrip()
    cut = _cut_to_utf16_units(cleaned, MAX_STEM_UTF16_UNITS).rstrip(" .")
    return _without_reserved_device(cut) if cut else DEFAULT_SHORTCUT_NAME


def shortcut_file_name(brand_name: str, folder_name: str) -> str:
    return safe_file_stem(f"{brand_name} - {folder_name}") + _SHORTCUT_SUFFIX


def _icon_of(home: Path, identity: LauncherIdentity) -> Path:
    icon = identity.icon
    return icon if icon.is_relative_to(home) else home / PACKAGED_ICON


def shortcut_icon(home: Path) -> Path:
    return _icon_of(home, load_launcher_identity(home))


def shortcut_result(home: Path) -> dict[str, str]:
    identity = load_launcher_identity(home)
    return {
        "target": str(home),
        "shortcut_file": shortcut_file_name(identity.name, home.name),
        "shortcut_icon": str(_icon_of(home, identity)),
    }
