"""The read-only brand check the wizard asks while the owner types."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest
from brand_deployment_support import (
    USER_PNG,
    make_source_home,
    put,
)
from png_fixtures import make_png

from jarvis.core.brand_render import monogram_style
from jarvis.core.config import BrandSettings
from tools import deployment
from tools.deployment_brand import BrandRequest
from tools.deployment_brand_check import (
    BRAND_CHECK_PREFIX,
    check_brand,
    check_brand_environment,
)
from tools.deployment_plan import DeploymentMode

CLEAN, COPY = DeploymentMode.CLEAN, DeploymentMode.COPY
WORK_TABLE = (
    '[brand]\nname = "Work"\nmonogram = "W"\naccent = "#E0A03F"\n'
    'icon = "brand-source/work.png"\n'
)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return make_source_home(tmp_path / "source")


def tree(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


def test_clean_without_a_request_answers_the_default_brand_with_the_packaged_icon(
    source: Path,
) -> None:
    answer = check_brand(source, CLEAN, None)

    assert answer["ok"] is True
    assert answer["brand"] == {
        "name": "Jarvis",
        "monogram": "J",
        "accent": "#3FE0D0",
        "icon": None,
        "is_default": True,
        "origin": "default",
    }
    packaged = source / "src" / "jarvis" / "launcher" / "assets" / "jarvis.png"
    assert answer["icon_preview"] == {"kind": "packaged", "path": str(packaged)}


def test_a_requested_name_answers_the_renderers_own_monogram_style(
    source: Path,
) -> None:
    answer = check_brand(source, CLEAN, BrandRequest(name="Work", accent="#E0A03F"))

    brand = BrandSettings("Work", "W", "#E0A03F")
    assert answer["ok"] is True
    assert answer["brand"]["origin"] == "requested"
    assert answer["brand"]["monogram"] == "W"
    assert answer["icon_preview"] == {
        "kind": "monogram",
        "art": asdict(monogram_style(brand)),
    }


def test_a_dark_accent_gets_the_white_glyph_the_renderer_would_choose(
    source: Path,
) -> None:
    answer = check_brand(source, CLEAN, BrandRequest(accent="#102030"))

    assert answer["icon_preview"]["art"]["glyph"] == "#FFFFFF"


@pytest.mark.parametrize(
    ("request_", "field", "message"),
    [
        (
            BrandRequest(monogram="AB"),
            "monogram",
            "[brand].monogram must be exactly one Latin or Cyrillic letter or digit, "
            "got 'AB'",
        ),
        (
            BrandRequest(name="1" * 33),
            "name",
            "[brand].name must be at most 32 characters, got 33",
        ),
        (
            BrandRequest(accent="red"),
            "accent",
            "[brand].accent must be a #RRGGBB colour, got 'red'",
        ),
        (
            BrandRequest(name="!Bang"),
            "monogram",
            "[brand].monogram cannot be taken from [brand].name '!Bang': its first "
            "character is not a Latin or Cyrillic letter or digit; set the monogram "
            "explicitly",
        ),
    ],
)
def test_a_rejected_request_is_an_answer_naming_the_field(
    source: Path, request_: BrandRequest, field: str, message: str
) -> None:
    assert check_brand(source, CLEAN, request_) == {
        "ok": False,
        "field": field,
        "message": message,
    }


def test_an_empty_name_is_an_answer_not_a_crash(source: Path) -> None:
    answer = check_brand(source, CLEAN, BrandRequest(name=""))

    assert answer["ok"] is False
    assert answer["field"] == "name"
    assert answer["message"].startswith("[brand].name")


@pytest.mark.parametrize(
    ("content", "pattern"),
    [
        (b"text", "is not a PNG file"),
        (make_png(32, 32), "is 32x32; the shorter side must be at least 64 px"),
    ],
)
def test_an_unusable_icon_file_names_the_icon_field(
    source: Path, tmp_path: Path, content: bytes, pattern: str
) -> None:
    picture = put(tmp_path / "pictures" / "logo.png", content)

    answer = check_brand(source, CLEAN, BrandRequest(icon=picture))

    assert answer["ok"] is False
    assert answer["field"] == "icon"
    assert pattern in answer["message"]
    assert f'[brand].icon "{picture}"' in answer["message"]


def test_a_missing_icon_file_names_the_icon_field(source: Path, tmp_path: Path) -> None:
    answer = check_brand(source, CLEAN, BrandRequest(icon=tmp_path / "gone.png"))

    assert answer["field"] == "icon"
    assert "file not found" in answer["message"]


def test_a_valid_icon_file_is_previewed_as_that_image(
    source: Path, tmp_path: Path
) -> None:
    picture = put(tmp_path / "pictures" / "logo.png", USER_PNG)

    answer = check_brand(source, CLEAN, BrandRequest(icon=picture))

    assert answer["ok"] is True
    assert answer["brand"]["icon"] == "brand-source/icon.png"
    assert answer["icon_preview"] == {"kind": "image", "path": str(picture.resolve())}


def test_a_copy_without_a_request_answers_the_inherited_brand(source: Path) -> None:
    put(source / "config.toml", WORK_TABLE)
    put(source / "brand-source" / "work.png", USER_PNG)

    answer = check_brand(source, COPY, None)

    assert answer["ok"] is True
    assert answer["brand"] == {
        "name": "Work",
        "monogram": "W",
        "accent": "#E0A03F",
        "icon": "brand-source/work.png",
        "is_default": False,
        "origin": "inherited",
    }
    assert answer["icon_preview"] == {
        "kind": "image",
        "path": str((source / "brand-source" / "work.png").resolve()),
    }


def test_a_copy_with_an_override_keeps_the_other_inherited_values(
    source: Path,
) -> None:
    put(
        source / "config.toml", WORK_TABLE.replace('icon = "brand-source/work.png"', "")
    )

    answer = check_brand(source, COPY, BrandRequest(name="Home"))

    assert answer["brand"]["name"] == "Home"
    assert answer["brand"]["monogram"] == "W"
    assert answer["brand"]["origin"] == "requested"


def test_a_copy_reset_answers_the_default_brand(source: Path) -> None:
    put(source / "config.toml", WORK_TABLE)

    answer = check_brand(source, COPY, BrandRequest(default_brand=True))

    assert answer["brand"]["is_default"] is True
    assert answer["icon_preview"]["kind"] == "packaged"


def test_a_copy_without_the_png_drops_only_the_icon(source: Path) -> None:
    put(source / "config.toml", WORK_TABLE)

    answer = check_brand(source, COPY, BrandRequest(no_icon=True))

    assert answer["brand"]["icon"] is None
    assert answer["brand"]["name"] == "Work"
    assert answer["icon_preview"]["kind"] == "monogram"


def test_an_invalid_stored_brand_is_an_answer_so_the_owner_can_reset_it(
    source: Path,
) -> None:
    put(source / "config.toml", '[brand]\nname = "' + "x" * 40 + '"\n')

    broken = check_brand(source, COPY, None)
    reset = check_brand(source, COPY, BrandRequest(default_brand=True))

    assert broken["ok"] is False
    assert broken["field"] == "name"
    assert reset["ok"] is True


def test_an_unsupported_source_form_has_no_field_and_names_the_source_file(
    source: Path,
) -> None:
    put(source / "config.toml", 'brand = { name = "Work" }\n')

    answer = check_brand(source, COPY, BrandRequest(name="Home"))

    assert answer["ok"] is False
    assert answer["field"] is None
    assert "Cannot rewrite [brand]" in answer["message"]
    assert str(source / "config.toml") in answer["message"]


def test_clean_never_reads_the_source_config(source: Path) -> None:
    put(source / "config.toml", "this is not toml [[[")

    assert check_brand(source, CLEAN, None)["ok"] is True


def test_a_check_writes_nothing_and_needs_no_runtime_lock(
    source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    put(source / "config.toml", WORK_TABLE)
    put(source / "brand-source" / "work.png", USER_PNG)
    before = tree(source)

    def refuse() -> None:
        raise AssertionError("a brand check must not take the runtime lock")

    monkeypatch.setattr(deployment, "_pause_runtime_for_copy", refuse)
    check_brand(source, COPY, BrandRequest(name="Home"))

    assert tree(source) == before


@pytest.mark.parametrize(
    "name", ['Say "hi"', "50% off", "R & D", "<b>x</b>", "Работа", "tail\\", "it's"]
)
def test_a_hostile_name_survives_the_json_line(source: Path, name: str) -> None:
    answer = check_brand(source, CLEAN, BrandRequest(name=name, monogram="H"))

    line = BRAND_CHECK_PREFIX + json.dumps(answer)
    assert json.loads(line.removeprefix(BRAND_CHECK_PREFIX))["brand"]["name"] == name


def test_the_environment_form_reads_the_same_json_as_a_deployment(
    source: Path,
) -> None:
    answer = check_brand_environment(
        source, CLEAN, {"JARVIS_DEPLOY_BRAND": '{"name": "Work"}'}
    )

    assert answer["brand"]["name"] == "Work"
    assert check_brand_environment(source, CLEAN, {})["brand"]["is_default"] is True


def test_a_malformed_or_conflicting_environment_is_an_answer(source: Path) -> None:
    broken = check_brand_environment(source, CLEAN, {"JARVIS_DEPLOY_BRAND": "{"})
    conflict = check_brand_environment(
        source,
        CLEAN,
        {"JARVIS_DEPLOY_BRAND": '{"default_brand": true, "name": "x"}'},
    )

    assert broken["ok"] is False and broken["field"] is None
    assert conflict == {
        "ok": False,
        "field": None,
        "message": "-DefaultBrand cannot be combined with other brand options",
    }


def test_main_prints_one_check_line_without_a_target(
    source: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_DEPLOY_BRAND", '{"monogram": "AB"}')

    code = deployment.main(["--source", str(source), "--brand-check"])

    out = capsys.readouterr().out.strip()
    assert code == 0
    assert out.startswith(BRAND_CHECK_PREFIX)
    answer = json.loads(out.removeprefix(BRAND_CHECK_PREFIX))
    assert answer["ok"] is False and answer["field"] == "monogram"


def test_main_still_requires_a_target_for_everything_else(
    source: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        deployment.main(["--source", str(source), "--preview"])

    assert exit_info.value.code == 2
    assert "--target" in capsys.readouterr().err
