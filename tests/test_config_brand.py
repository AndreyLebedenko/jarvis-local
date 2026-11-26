from pathlib import Path

import pytest

from jarvis.core.config import (
    BrandSettings,
    ConfigError,
    Settings,
    brand_from_table,
    load_brand,
    load_settings,
)

EXAMPLE_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.example.toml"


def _write(tmp_path, text: str, name: str = "config.toml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _brand(tmp_path, body: str) -> BrandSettings:
    config = _write(tmp_path, f"[brand]\n{body}\n")
    return load_settings(config).brand


def test_without_a_brand_section_the_defaults_are_the_current_identity(tmp_path):
    config = _write(tmp_path, "")

    brand = load_settings(config).brand

    assert brand == BrandSettings()
    assert (brand.name, brand.monogram, brand.accent, brand.icon) == (
        "Jarvis",
        "J",
        "#3FE0D0",
        None,
    )


def test_name_only_derives_the_monogram_from_its_first_letter(tmp_path):
    brand = _brand(tmp_path, 'name = "work station"')

    assert (brand.name, brand.monogram) == ("work station", "W")


def test_cyrillic_name_derives_an_upper_case_cyrillic_monogram(tmp_path):
    brand = _brand(tmp_path, 'name = "домашний"')

    assert brand.monogram == "Д"


def test_a_digit_is_a_valid_monogram(tmp_path):
    assert _brand(tmp_path, 'name = "Bot"\nmonogram = "7"').monogram == "7"


def test_explicit_monogram_overrides_the_first_letter(tmp_path):
    brand = _brand(tmp_path, 'name = "Work"\nmonogram = "x"')

    assert brand.monogram == "X"


def test_monogram_alone_keeps_the_default_name(tmp_path):
    brand = _brand(tmp_path, 'monogram = "K"')

    assert (brand.name, brand.monogram) == ("Jarvis", "K")


def test_name_is_stripped_and_unicode_normalized(tmp_path):
    brand = _brand(tmp_path, 'name = "  Cafe\\u0301  "')

    assert brand.name == "Caf\u00e9"


@pytest.mark.parametrize(
    "monogram",
    ["", "AB", "!", "\u4e2d", " ", "\u0301", "\u0663"],
)
def test_invalid_monogram_is_rejected_naming_the_key(tmp_path, monogram):
    config = _write(tmp_path, f'[brand]\nmonogram = "{monogram}"\n')

    with pytest.raises(ConfigError, match=r"\[brand\]\.monogram"):
        load_settings(config)


def test_a_decomposed_accented_letter_is_one_normalized_monogram(tmp_path):
    assert _brand(tmp_path, 'monogram = "e\\u0301"').monogram == "É"


def test_name_starting_with_an_unsupported_character_requires_a_monogram(tmp_path):
    config = _write(tmp_path, '[brand]\nname = "#1 Bot"\n')

    with pytest.raises(ConfigError, match=r"\[brand\]\.monogram.*explicit"):
        load_settings(config)


def test_name_starting_with_an_unsupported_character_accepts_a_monogram(tmp_path):
    assert _brand(tmp_path, 'name = "#1 Bot"\nmonogram = "B"').monogram == "B"


@pytest.mark.parametrize(
    "name",
    [
        "",
        "   ",
        "a" * 33,
        "line\\nbreak",
        "tab\\there",
        "nul\\u0000",
        "bell\\u0007",
        "zero\\u200bwidth",
        "sep\\u2028arator",
        "nb\\u00a0sp",
    ],
)
def test_invalid_name_is_rejected_naming_the_key(tmp_path, name):
    config = _write(tmp_path, f'[brand]\nname = "{name}"\nmonogram = "A"\n')

    with pytest.raises(ConfigError, match=r"\[brand\]\.name"):
        load_settings(config)


def test_a_name_of_exactly_the_maximum_length_is_accepted(tmp_path):
    assert _brand(tmp_path, f'name = "{"a" * 32}"').name == "a" * 32


def test_a_very_long_name_is_bounded_not_stored(tmp_path):
    config = _write(tmp_path, f'[brand]\nname = "{"a" * 10000}"\n')

    with pytest.raises(ConfigError, match=r"\[brand\]\.name"):
        load_settings(config)


@pytest.mark.parametrize(
    "name",
    ["<img src=x onerror=alert(1)>", 'say \\"hi\\"', "$& {max} {name}", "a'b"],
)
def test_markup_quotes_and_placeholders_are_kept_literally(tmp_path, name):
    brand = _brand(tmp_path, f'name = "{name}"\nmonogram = "A"')

    assert brand.name == name.encode().decode("unicode_escape")


def test_name_must_be_a_string(tmp_path):
    config = _write(tmp_path, "[brand]\nname = 5\n")

    with pytest.raises(ConfigError, match=r"\[brand\]\.name"):
        load_settings(config)


def test_accent_is_normalized_to_upper_case(tmp_path):
    assert _brand(tmp_path, 'accent = "#e0a03f"').accent == "#E0A03F"


@pytest.mark.parametrize(
    "accent", ["", "red", "#fff", "E0A03F", "#E0A03", "#E0A03FF", "#GGGGGG", "#E0A03 "]
)
def test_malformed_accent_is_rejected_naming_the_key(tmp_path, accent):
    config = _write(tmp_path, f'[brand]\naccent = "{accent}"\n')

    with pytest.raises(ConfigError, match=r"\[brand\]\.accent"):
        load_settings(config)


@pytest.mark.parametrize(
    "icon", ["icon.png", "art/icon.png", "art\\\\icon.PNG", "brand-src/My Icon.png"]
)
def test_relative_png_icon_paths_are_accepted(tmp_path, icon):
    assert _brand(tmp_path, f'icon = "{icon}"').icon == icon.replace("\\\\", "\\")


@pytest.mark.parametrize(
    "icon",
    [
        "",
        "icon.jpg",
        "icon",
        "/abs/icon.png",
        "\\\\rooted\\\\icon.png",
        "C:\\\\icon.png",
        "C:icon.png",
        "\\\\\\\\server\\\\share\\\\icon.png",
        "../icon.png",
        "art/../../icon.png",
        "art\\\\..\\\\icon.png",
        "ic\\u0000on.png",
    ],
)
def test_unsafe_or_non_png_icon_paths_are_rejected_naming_the_key(tmp_path, icon):
    config = _write(tmp_path, f'[brand]\nicon = "{icon}"\n')

    with pytest.raises(ConfigError, match=r"\[brand\]\.icon"):
        load_settings(config)


def test_a_missing_icon_file_is_not_a_config_error(tmp_path):
    assert _brand(tmp_path, 'icon = "does-not-exist.png"').icon == (
        "does-not-exist.png"
    )


def test_unknown_brand_keys_are_rejected(tmp_path):
    config = _write(tmp_path, '[brand]\nlogo = "x"\n')

    with pytest.raises(ConfigError, match=r"\[brand\].*logo"):
        load_settings(config)


def test_a_brand_section_in_the_ui_layer_is_rejected(tmp_path):
    config = _write(tmp_path, "")
    ui = _write(tmp_path, '[brand]\nname = "Work"\n', "config.ui.toml")

    with pytest.raises(ConfigError, match=r"\[brand\].*config\.toml"):
        load_settings(config, ui_path=ui)


def test_the_example_config_leaves_the_brand_at_its_defaults(tmp_path):
    settings = load_settings(EXAMPLE_CONFIG_PATH, ui_path=tmp_path / "none.toml")

    assert settings.brand == Settings().brand


def test_the_example_config_carries_a_commented_brand_block_that_is_valid(tmp_path):
    lines = EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8").splitlines()
    block = []
    for line in lines[lines.index("# [brand]") :]:
        if not line.startswith("# "):
            break
        block.append(line[2:])
    config = _write(tmp_path, "\n".join(block) + "\n")

    brand = load_settings(config).brand

    assert {"name", "monogram", "accent", "icon"} <= {
        line.split("=")[0].strip() for line in block if "=" in line
    }
    assert brand.icon is not None


def test_load_brand_reads_only_the_brand_section(tmp_path):
    config = _write(tmp_path, '[brand]\nname = "Work"\n[backend]\nmodel = 5\n')

    assert load_brand(config).name == "Work"


def test_load_brand_without_files_returns_the_defaults(tmp_path):
    assert load_brand(tmp_path / "config.toml") == BrandSettings()


def test_load_brand_rejects_a_ui_layer_brand(tmp_path):
    config = _write(tmp_path, "")
    _write(tmp_path, '[brand]\nname = "Work"\n', "config.ui.toml")

    with pytest.raises(ConfigError, match=r"\[brand\]"):
        load_brand(config)


def test_load_brand_reports_malformed_toml(tmp_path):
    config = _write(tmp_path, "[brand\n")

    with pytest.raises(ConfigError):
        load_brand(config)


def test_an_undecodable_config_file_is_a_config_error_naming_the_file(tmp_path):
    config = tmp_path / "config.toml"
    config.write_bytes('[brand]\nname = "Работа"\n'.encode("cp1251"))

    with pytest.raises(ConfigError, match=r"config\.toml.*UTF-8"):
        load_brand(config)
    with pytest.raises(ConfigError, match=r"config\.toml.*UTF-8"):
        load_settings(config)


def test_an_undecodable_ui_layer_is_a_config_error_naming_the_file(tmp_path):
    config = _write(tmp_path, "")
    (tmp_path / "config.ui.toml").write_bytes(b'[ui]\nlanguage = "\xff"\n')

    with pytest.raises(ConfigError, match=r"config\.ui\.toml.*UTF-8"):
        load_settings(config)


def test_a_ui_layer_brand_with_an_unknown_key_still_gets_the_brand_message(tmp_path):
    config = _write(tmp_path, "")
    ui = _write(tmp_path, '[brand]\nlogo = "x"\n', "config.ui.toml")

    with pytest.raises(ConfigError, match=r"belongs in config\.toml"):
        load_settings(config, ui_path=ui)


def test_a_table_that_is_not_a_file_is_validated_with_the_file_messages():
    assert brand_from_table({"name": "Work"}) == BrandSettings(
        name="Work", monogram="W"
    )
    with pytest.raises(ConfigError, match=r"\[brand\]\.monogram must be exactly one"):
        brand_from_table({"name": "Work", "monogram": "AB"})
    with pytest.raises(ConfigError, match=r"Unknown key\(s\) in \[brand\]: colour"):
        brand_from_table({"colour": "red"})
