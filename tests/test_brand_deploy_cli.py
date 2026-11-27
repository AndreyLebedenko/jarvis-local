"""deploy.cmd with brand parameters, against the real scripts and the real
Windows PowerShell icon renderer (the destination has no .venv at all)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from brand_deployment_support import (
    GOOD_ICO,
    GOOD_PNG,
    USER_PNG,
    make_source_home,
    put,
)
from deploy_cli_support import build_cli_home, run_deploy_cmd

from jarvis.core.brand_icon import check_standard_ico, inspect_png
from jarvis.core.config import BrandSettings, load_brand
from tools import deployment
from tools.deployment_brand_check import BRAND_CHECK_PREFIX

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows deployment command")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    source = make_source_home(tmp_path / "source")
    build_cli_home(source)
    return source


@pytest.fixture(autouse=True)
def isolated_runtime_mutex(monkeypatch: pytest.MonkeyPatch) -> None:
    # The CLI runs in its own process with a patched mutex name (build_cli_home);
    # this only keeps the in-process import of tools.deployment untouched.
    monkeypatch.setattr(deployment, "MUTEX_NAME", "Local\\Jarvis.BrandCliTest")


def result_of(stdout: str) -> dict[str, str]:
    lines = [
        line.removeprefix(deployment.RESULT_PREFIX)
        for line in stdout.splitlines()
        if line.startswith(deployment.RESULT_PREFIX)
    ]
    assert len(lines) == 1, stdout
    return json.loads(lines[0])


def test_flags_produce_a_branded_home_with_real_icons_and_no_venv(
    home: Path, tmp_path: Path
) -> None:
    target = tmp_path / "work home"

    result = run_deploy_cmd(
        home,
        tmp_path,
        "-Target",
        target.name,
        "-Yes",
        "-Name",
        "Work",
        "-Monogram",
        "W",
        "-Accent",
        "#E0A03F",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert load_brand(target / "config.toml") == BrandSettings("Work", "W", "#E0A03F")
    assert not (target / ".venv").exists()
    info = inspect_png((target / "brand" / "brand.png").read_bytes())
    assert (info.width, info.height, info.has_alpha) == (512, 512, True)
    check_standard_ico((target / "brand" / "brand.ico").read_bytes())
    shortcut = result_of(result.stdout)
    assert shortcut["shortcut_file"] == "Work - work home.lnk"
    assert shortcut["shortcut_icon"] == str(target / "brand" / "brand.ico")


@pytest.mark.parametrize(
    "name",
    ['Say "hi"', "50% off", "R & D", "Работа", "it's ^ ok", "tail\\"],
)
def test_a_hostile_name_arrives_in_the_config_unchanged(
    home: Path, tmp_path: Path, name: str
) -> None:
    target = tmp_path / "t"

    result = run_deploy_cmd(
        home, tmp_path, "-Target", target.name, "-Yes", "-Name", name, "-Monogram", "H"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert load_brand(target / "config.toml").name == name


def test_a_relative_icon_path_is_resolved_against_the_callers_directory(
    home: Path, tmp_path: Path
) -> None:
    put(tmp_path / "pictures" / "logo.png", USER_PNG)
    target = tmp_path / "icon home"

    result = run_deploy_cmd(
        home,
        tmp_path,
        "-Target",
        target.name,
        "-Yes",
        "-Icon",
        "pictures\\logo.png",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (target / "brand-source" / "icon.png").read_bytes() == USER_PNG
    assert load_brand(target / "config.toml").icon == "brand-source/icon.png"
    assert (target / "brand" / "brand.ico").is_file()


def test_an_invalid_value_fails_with_the_key_and_creates_no_destination(
    home: Path, tmp_path: Path
) -> None:
    result = run_deploy_cmd(
        home, tmp_path, "-Target", "never", "-Yes", "-Monogram", "AB"
    )

    assert result.returncode == 1
    assert "ERROR: [brand].monogram must be exactly one" in result.stderr
    assert not (tmp_path / "never").exists()


def test_an_unusable_png_fails_before_the_destination_exists(
    home: Path, tmp_path: Path
) -> None:
    put(tmp_path / "bad.png", b"text")

    result = run_deploy_cmd(
        home, tmp_path, "-Target", "never", "-Yes", "-Icon", "bad.png"
    )

    assert result.returncode == 1
    assert "is not a PNG file (bad signature)" in result.stderr
    assert not (tmp_path / "never").exists()


def test_a_copy_inherits_overrides_and_resets_through_the_command(
    home: Path, tmp_path: Path
) -> None:
    put(
        home / "config.toml",
        '# mine\n[brand]\nname = "Work"\nmonogram = "W"\naccent = "#E0A03F"\n',
    )
    put(home / "brand" / "brand.png", GOOD_PNG)
    put(home / "brand" / "brand.ico", GOOD_ICO)

    inherited = run_deploy_cmd(
        home, tmp_path, "-Target", "inherited", "-Mode", "copy", "-Yes"
    )
    renamed = run_deploy_cmd(
        home, tmp_path, "-Target", "renamed", "-Mode", "copy", "-Yes", "-Name", "Home"
    )
    reset = run_deploy_cmd(
        home,
        tmp_path,
        "-Target",
        "reset",
        "-Mode",
        "copy",
        "-Yes",
        "-DefaultBrand",
    )

    for run in (inherited, renamed, reset):
        assert run.returncode == 0, run.stdout + run.stderr
    assert load_brand(tmp_path / "inherited" / "config.toml").name == "Work"
    assert (tmp_path / "inherited" / "brand" / "brand.png").read_bytes() == GOOD_PNG
    assert (tmp_path / "inherited" / "brand" / "brand.ico").read_bytes() == GOOD_ICO
    assert load_brand(tmp_path / "renamed" / "config.toml") == BrandSettings(
        "Home", "W", "#E0A03F"
    )
    assert (tmp_path / "renamed" / "brand" / "brand.ico").is_file()
    assert load_brand(tmp_path / "reset" / "config.toml") == BrandSettings()
    assert not (tmp_path / "reset" / "brand").exists()
    assert result_of(reset.stdout)["shortcut_file"] == "Jarvis - reset.lnk"


def test_resume_refuses_brand_parameters(home: Path, tmp_path: Path) -> None:
    target = tmp_path / "t"
    put(target / deployment.MANIFEST, "{}")

    result = run_deploy_cmd(
        home, tmp_path, "-Target", target.name, "-Resume", "-Yes", "-Name", "Late"
    )

    assert result.returncode == 1
    assert "cannot be changed while resuming" in result.stderr


def test_check_brand_answers_without_a_target_and_creates_nothing(
    home: Path, tmp_path: Path
) -> None:
    before = {path.name for path in tmp_path.iterdir()}

    result = run_deploy_cmd(home, tmp_path, "-CheckBrand", "-Name", "Work")

    assert result.returncode == 0, result.stdout + result.stderr
    line = result.stdout.strip().splitlines()[-1]
    assert line.startswith(BRAND_CHECK_PREFIX)
    assert json.loads(line.removeprefix(BRAND_CHECK_PREFIX))["brand"]["name"] == "Work"
    assert {path.name for path in tmp_path.iterdir()} - {"stale-env"} == before


@pytest.mark.parametrize("extra", ["-Target", "-Resume", "-Preview", "-Yes"])
def test_check_brand_cannot_be_combined_with_deployment_parameters(
    home: Path, tmp_path: Path, extra: str
) -> None:
    arguments = ["-CheckBrand", extra] + (["x"] if extra == "-Target" else [])

    result = run_deploy_cmd(home, tmp_path, *arguments)

    assert result.returncode != 0
    assert BRAND_CHECK_PREFIX not in result.stdout


@pytest.mark.parametrize("extra", ["-Resume", "-Preview", "-Yes"])
def test_rebrand_cannot_be_combined_with_deployment_parameters(
    home: Path, tmp_path: Path, extra: str
) -> None:
    result = run_deploy_cmd(home, tmp_path, "-Rebrand", "-Target", "x", extra)

    assert result.returncode != 0
    assert "JARVIS_DEPLOY_REBRAND:" not in result.stdout


def test_rebrand_needs_a_target(home: Path, tmp_path: Path) -> None:
    result = run_deploy_cmd(home, tmp_path, "-Rebrand", "-Name", "Lab")

    assert result.returncode != 0
    assert "JARVIS_DEPLOY_REBRAND:" not in result.stdout
