from __future__ import annotations

from pathlib import Path

import pytest
from brand_deployment_support import GOOD_ICO, put

from tools.deployment_shortcut import (
    DEFAULT_SHORTCUT_NAME,
    MAX_STEM_UTF16_UNITS,
    PACKAGED_ICON,
    safe_file_stem,
    shortcut_file_name,
    shortcut_icon,
    shortcut_result,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Work - copy", "Work - copy"),
        ("Работа - копия", "Работа - копия"),
        ('a<b>c:d"e/f\\g|h?i*j', "a_b_c_d_e_f_g_h_i_j"),
        ("tab\tand\nnewline", "tab_and_newline"),
        ("name. ", "name"),
        ("name . . ", "name"),
        ("  padded", "padded"),
        ("dots...", "dots"),
        ("a.b", "a.b"),
        ("", DEFAULT_SHORTCUT_NAME),
        ("...", DEFAULT_SHORTCUT_NAME),
        ("   ", DEFAULT_SHORTCUT_NAME),
        ("?", "_"),
    ],
)
def test_a_name_loses_only_what_windows_cannot_store(text: str, expected: str) -> None:
    assert safe_file_stem(text) == expected


@pytest.mark.parametrize(
    "device",
    [
        "CON",
        "con",
        "Prn",
        "AUX",
        "nul",
        "COM1",
        "com9",
        "COM0",
        "LPT1",
        "lpt0",
        "COM¹",
        "LPT²",
        "COM³",
        "CONIN$",
        "CONOUT$",
        "CON ",
    ],
)
def test_a_reserved_device_name_is_made_safe(device: str) -> None:
    result = safe_file_stem(device)

    assert result == device.rstrip() + "_"


def test_a_device_name_with_an_extension_is_still_reserved_and_is_changed() -> None:
    assert safe_file_stem("CON.txt") == "CON_.txt"
    assert safe_file_stem("nul.tar.gz") == "nul_.tar.gz"


@pytest.mark.parametrize(
    "fine", ["CONSOLE", "COM10", "LPT", "XCON", "COM1x", "AUXILIARY"]
)
def test_names_that_only_start_like_a_device_are_untouched(fine: str) -> None:
    assert safe_file_stem(fine) == fine


def test_a_long_name_is_cut_without_splitting_a_surrogate_pair() -> None:
    long_ascii = safe_file_stem("a" * 500)
    assert long_ascii == "a" * MAX_STEM_UTF16_UNITS

    emoji = "\U0001f600" * 200
    cut = safe_file_stem(emoji)
    assert len(cut.encode("utf-16-le")) // 2 <= MAX_STEM_UTF16_UNITS
    assert cut == "\U0001f600" * (MAX_STEM_UTF16_UNITS // 2)
    assert safe_file_stem("a" + emoji).encode("utf-16-le").decode("utf-16-le")


def test_trailing_dots_and_spaces_are_removed_again_after_the_cut() -> None:
    text = "a" * (MAX_STEM_UTF16_UNITS - 1) + ". tail"

    assert safe_file_stem(text) == "a" * (MAX_STEM_UTF16_UNITS - 1)


def test_the_default_brand_gives_exactly_the_name_the_wizard_always_used() -> None:
    assert shortcut_file_name("Jarvis", "Jarvis-copy") == "Jarvis - Jarvis-copy.lnk"


def test_a_brand_name_replaces_the_product_name() -> None:
    assert shortcut_file_name("Work", "new home") == "Work - new home.lnk"
    assert shortcut_file_name("A/B: C?", "x") == "A_B_ C_ - x.lnk"


def test_the_brand_part_survives_a_very_long_folder_name() -> None:
    name = shortcut_file_name("Work", "f" * 400)

    assert name.startswith("Work - fff")
    assert name.endswith(".lnk")
    assert len(name) == MAX_STEM_UTF16_UNITS + len(".lnk")


# --- icon and result ----------------------------------------------------------


def make_home(tmp_path: Path, config: str | None) -> Path:
    home = tmp_path / "home"
    put(home / PACKAGED_ICON, b"packaged icon bytes")
    if config is not None:
        put(home / "config.toml", config)
    return home


def test_a_default_home_uses_its_own_packaged_icon(tmp_path: Path) -> None:
    home = make_home(tmp_path, None)

    assert shortcut_icon(home) == home / PACKAGED_ICON
    assert shortcut_result(home) == {
        "target": str(home),
        "shortcut_file": "Jarvis - home.lnk",
        "shortcut_icon": str(home / PACKAGED_ICON),
    }


def test_a_branded_home_uses_its_generated_icon_and_name(tmp_path: Path) -> None:
    home = make_home(tmp_path, '[brand]\nname = "Work"\n')
    put(home / "brand" / "brand.ico", GOOD_ICO)

    result = shortcut_result(home)

    assert result["shortcut_icon"] == str(home / "brand" / "brand.ico")
    assert result["shortcut_file"] == "Work - home.lnk"


def test_a_default_brand_ignores_stale_generated_icons(tmp_path: Path) -> None:
    home = make_home(tmp_path, "[ui]\nlanguage = 'en'\n")
    put(home / "brand" / "brand.ico", GOOD_ICO)

    assert shortcut_icon(home) == home / PACKAGED_ICON


@pytest.mark.parametrize("ico", [None, b"not an icon"])
def test_a_branded_home_without_a_usable_icon_falls_back_to_its_packaged_one(
    tmp_path: Path, ico: bytes | None
) -> None:
    home = make_home(tmp_path, '[brand]\nname = "Work"\n')
    if ico is not None:
        put(home / "brand" / "brand.ico", ico)

    assert shortcut_icon(home) == home / PACKAGED_ICON
    assert shortcut_result(home)["shortcut_file"] == "Work - home.lnk"


def test_an_invalid_brand_gives_the_default_name_and_icon(tmp_path: Path) -> None:
    home = make_home(tmp_path, '[brand]\nmonogram = "AB"\n')

    assert shortcut_result(home)["shortcut_file"] == "Jarvis - home.lnk"
    assert shortcut_icon(home) == home / PACKAGED_ICON


def test_the_packaged_icon_path_matches_what_the_wizard_used(tmp_path: Path) -> None:
    assert Path("src/jarvis/launcher/assets/jarvis.ico") == PACKAGED_ICON
