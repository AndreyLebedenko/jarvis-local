import logging
import subprocess
import sys
from pathlib import Path

import pytest
from png_fixtures import make_ico, make_png

import jarvis.launcher.identity as identity_module
from jarvis.core.brand import PACKAGE_ASSETS
from jarvis.core.brand_icon import ICO_FRAME_SIZES
from jarvis.launcher.identity import (
    DEFAULT_IDENTITY,
    LauncherIdentity,
    load_launcher_identity,
)

GOOD_ICO = make_ico([(side, make_png(side, side)) for side in ICO_FRAME_SIZES])


def write_config(home: Path, text: str) -> None:
    (home / "config.toml").write_text(text, encoding="utf-8")


def write_brand_icon(home: Path, data: bytes = GOOD_ICO) -> Path:
    path = home / "brand" / "brand.ico"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(data)
    return path


def test_the_default_identity_is_jarvis_with_the_packaged_icon():
    assert LauncherIdentity("Jarvis", PACKAGE_ASSETS / "jarvis.ico") == DEFAULT_IDENTITY


def test_a_home_without_a_config_has_the_default_identity(tmp_path):
    assert load_launcher_identity(tmp_path) == DEFAULT_IDENTITY


def test_a_home_without_a_brand_section_has_the_default_identity(tmp_path):
    write_config(tmp_path, '[ui]\nlanguage = "en"\n')

    assert load_launcher_identity(tmp_path) == DEFAULT_IDENTITY


def test_a_branded_home_uses_its_name_and_generated_icon(tmp_path):
    write_config(tmp_path, '[brand]\nname = "Work"\n')
    icon = write_brand_icon(tmp_path)

    assert load_launcher_identity(tmp_path) == LauncherIdentity("Work", icon)


def test_a_branded_home_without_generated_files_keeps_the_packaged_icon(tmp_path):
    write_config(tmp_path, '[brand]\nname = "Work"\n')

    assert load_launcher_identity(tmp_path) == LauncherIdentity(
        "Work", DEFAULT_IDENTITY.icon
    )


def test_a_default_brand_ignores_stale_generated_files(tmp_path):
    write_brand_icon(tmp_path)
    write_config(tmp_path, '[brand]\nname = "Jarvis"\n')

    assert load_launcher_identity(tmp_path) == DEFAULT_IDENTITY


def test_deleting_the_brand_section_returns_the_default_although_files_remain(
    tmp_path,
):
    write_config(tmp_path, '[brand]\nname = "Work"\n')
    write_brand_icon(tmp_path)
    assert load_launcher_identity(tmp_path).name == "Work"

    write_config(tmp_path, "")

    assert load_launcher_identity(tmp_path) == DEFAULT_IDENTITY


@pytest.mark.parametrize(
    "broken",
    [b"junk", GOOD_ICO[:-40], b"", make_ico([(16, make_png(32, 32))])],
    ids=["junk", "cut", "empty", "frame-size-mismatch"],
)
def test_a_corrupt_icon_file_falls_back_to_the_packaged_icon_per_field(
    tmp_path, broken
):
    write_config(tmp_path, '[brand]\nname = "Work"\n')
    write_brand_icon(tmp_path, broken)

    assert load_launcher_identity(tmp_path) == LauncherIdentity(
        "Work", DEFAULT_IDENTITY.icon
    )


def test_an_oversized_icon_file_falls_back_without_being_parsed(tmp_path):
    write_config(tmp_path, '[brand]\nname = "Work"\n')
    path = write_brand_icon(tmp_path)
    with path.open("r+b") as stream:
        stream.truncate(8 * 1024 * 1024 + 1)

    assert load_launcher_identity(tmp_path).icon == DEFAULT_IDENTITY.icon


def test_a_hand_placed_classic_icon_is_used(tmp_path):
    write_config(tmp_path, '[brand]\nname = "Work"\n')
    dib = make_ico([(32, b"\x28\x00\x00\x00" + bytes(100))])
    icon = write_brand_icon(tmp_path, dib)

    assert load_launcher_identity(tmp_path).icon == icon


@pytest.mark.parametrize(
    "config",
    [
        '[brand]\nmonogram = "AB"\n',
        '[brand]\nname = ""\n',
        "[brand\n",
        "[brand]\nunknown = 1\n",
        "[brand]\nname = 3\n",
    ],
)
def test_an_invalid_brand_gives_the_default_identity_and_one_warning(
    tmp_path, config, caplog
):
    write_config(tmp_path, config)

    with caplog.at_level(logging.WARNING, logger=identity_module.logger.name):
        result = load_launcher_identity(tmp_path)

    assert result == DEFAULT_IDENTITY
    (record,) = caplog.records
    assert str(tmp_path) in record.getMessage()


def test_an_undecodable_config_gives_the_default_identity(tmp_path):
    (tmp_path / "config.toml").write_bytes(b"\xff\xfe\x00bad")

    assert load_launcher_identity(tmp_path) == DEFAULT_IDENTITY


@pytest.mark.parametrize("error", [RecursionError(), MemoryError(), PermissionError()])
def test_no_failure_while_reading_the_brand_can_stop_the_launcher(
    tmp_path, monkeypatch, error
):
    def fail(path):
        raise error

    monkeypatch.setattr(identity_module, "load_brand", fail)

    assert load_launcher_identity(tmp_path) == DEFAULT_IDENTITY


def test_a_ui_layer_brand_section_is_ignored_with_the_default_identity(tmp_path):
    write_config(tmp_path, '[brand]\nname = "Work"\n')
    (tmp_path / "config.ui.toml").write_text('[brand]\nname = "X"\n', encoding="utf-8")

    assert load_launcher_identity(tmp_path) == DEFAULT_IDENTITY


def test_a_hostile_name_is_kept_literally(tmp_path):
    write_config(tmp_path, '[brand]\nname = "<b>%s</b> {x} $&"\nmonogram = "B"\n')

    assert load_launcher_identity(tmp_path).name == "<b>%s</b> {x} $&"


def test_loading_an_identity_never_writes_into_the_home(tmp_path):
    write_config(tmp_path, '[brand]\nname = "Work"\n')
    before = sorted(p.name for p in tmp_path.rglob("*"))

    load_launcher_identity(tmp_path)

    assert sorted(p.name for p in tmp_path.rglob("*")) == before


def test_importing_the_launcher_modules_loads_no_engine_module():
    pytest.importorskip("tkinter")
    code = (
        "import sys\n"
        "import jarvis.launcher.identity, jarvis.launcher.model, "
        "jarvis.launcher.tray, jarvis.launcher.window, jarvis.launcher.branding\n"
        "engine = sorted(m for m in sys.modules if m.startswith('jarvis.') "
        "and not m.startswith(('jarvis.core', 'jarvis.launcher')))\n"
        "print(engine)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "[]"
