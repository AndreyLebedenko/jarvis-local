from __future__ import annotations

from pathlib import Path

import pytest
from brand_deployment_support import GOOD_ICO, GOOD_PNG, USER_PNG, FakeRenderer, put

from jarvis.core.brand_icon import BrandIconError
from jarvis.core.brand_render import ImageRequest, MonogramStyle
from jarvis.core.config import BrandSettings, load_brand
from tools.deployment_brand import BrandRequest
from tools.deployment_plan import DeploymentPlanError
from tools.deployment_rebrand import (
    RECOVERY_COMMAND,
    BrandStageError,
    check_home_brand,
    rebrand_home,
)

WORK_CONFIG = (
    "# my settings\n"
    "[ui]\n"
    "language = 'ru'\n"
    "\n"
    "# identity\n"
    "[brand]  # who\n"
    'name = "Work"\n'
    'monogram = "W"\n'
    'accent = "#E0A03F"\n'
    'icon = "brand-source/icon.png"\n'
    "\n"
    "[tts]\n"
    "enabled = true\n"
)
BRAND_MODULE = "src/jarvis/core/brand.py"


@pytest.fixture
def home(tmp_path: Path) -> Path:
    root = tmp_path / "work home"
    put(root / "config.toml", WORK_CONFIG)
    put(root / BRAND_MODULE, "# marker")
    put(root / "brand-source" / "icon.png", USER_PNG)
    put(root / "brand" / "brand.png", b"old png")
    put(root / "brand" / "brand.ico", b"old ico")
    put(root / "journal" / "today.jsonl", b"memory")
    return root


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def changed(before: dict[str, bytes], after: dict[str, bytes]) -> set[str]:
    return {
        name
        for name in before.keys() | after.keys()
        if before.get(name) != after.get(name)
    }


# --- what a rebrand writes ------------------------------------------------------


def test_a_rename_changes_the_name_and_nothing_else_in_the_config(home: Path) -> None:
    before = snapshot(home)

    result = rebrand_home(home, BrandRequest(name="Lab"), renderer=FakeRenderer())

    after = snapshot(home)
    expected = WORK_CONFIG.replace('name = "Work"', 'name = "Lab"')
    assert after["config.toml"].decode("utf-8") == expected
    assert changed(before, after) == {
        "config.toml",
        "brand/brand.png",
        "brand/brand.ico",
    }
    assert after["brand/brand.png"] == GOOD_PNG
    assert after["brand/brand.ico"] == GOOD_ICO
    assert result.brand["name"] == "Lab"
    assert result.brand["origin"] == "requested"
    assert result.files == ("config.toml", "brand/brand.png", "brand/brand.ico")


def test_a_rebrand_leaves_no_temporary_file_in_the_home(home: Path) -> None:
    rebrand_home(home, BrandRequest(name="Lab"), renderer=FakeRenderer())

    assert sorted(path.name for path in home.iterdir()) == [
        "brand",
        "brand-source",
        "config.toml",
        "journal",
        "src",
    ]
    assert sorted(path.name for path in (home / "brand").iterdir()) == [
        "brand.ico",
        "brand.png",
    ]


def test_a_new_png_replaces_the_source_png_and_is_what_gets_rendered(
    home: Path, tmp_path: Path
) -> None:
    chosen = put(tmp_path / "elsewhere" / "logo.png", GOOD_PNG)
    renderer = FakeRenderer()

    result = rebrand_home(home, BrandRequest(icon=chosen), renderer=renderer)

    assert (home / "brand-source" / "icon.png").read_bytes() == GOOD_PNG
    assert [type(request) for request in renderer.requests] == [ImageRequest]
    assert renderer.requests[0].source == chosen.resolve()
    assert result.files == (
        "brand-source/icon.png",
        "brand/brand.png",
        "brand/brand.ico",
    )
    assert chosen.read_bytes() == GOOD_PNG


def test_choosing_the_homes_own_source_png_changes_nothing_about_it(
    home: Path,
) -> None:
    own = home / "brand-source" / "icon.png"

    result = rebrand_home(home, BrandRequest(icon=own), renderer=FakeRenderer())

    assert own.read_bytes() == USER_PNG
    assert "brand-source/icon.png" not in result.files


def test_remove_png_switches_to_the_monogram_and_keeps_the_source_file(
    home: Path,
) -> None:
    renderer = FakeRenderer()

    rebrand_home(home, BrandRequest(no_icon=True), renderer=renderer)

    assert load_brand(home / "config.toml").icon is None
    assert [type(request) for request in renderer.requests] == [MonogramStyle]
    assert (home / "brand-source" / "icon.png").read_bytes() == USER_PNG


def test_an_unchanged_request_still_renders_so_it_repairs_stale_icons(
    home: Path,
) -> None:
    renderer = FakeRenderer()

    rebrand_home(home, BrandRequest(name="Work"), renderer=renderer)

    assert len(renderer.requests) == 1
    assert (home / "brand" / "brand.png").read_bytes() == GOOD_PNG


def test_a_hostile_name_survives_the_toml(home: Path) -> None:
    name = 'Wo"rk \\ # [x] = 1'

    rebrand_home(home, BrandRequest(name=name), renderer=FakeRenderer())

    assert load_brand(home / "config.toml").name == name


def test_the_default_brand_removes_the_table_generates_nothing_and_deletes_nothing(
    home: Path,
) -> None:
    before = snapshot(home)
    renderer = FakeRenderer()

    result = rebrand_home(home, BrandRequest(default_brand=True), renderer=renderer)

    after = snapshot(home)
    assert load_brand(home / "config.toml") == BrandSettings()
    assert renderer.requests == []
    assert changed(before, after) == {"config.toml"}
    assert "[brand]" not in after["config.toml"].decode("utf-8")
    assert result.brand["is_default"] is True
    assert result.files == ("config.toml",)


# --- what a rebrand refuses -----------------------------------------------------


@pytest.mark.parametrize(
    "request_, message",
    [
        (BrandRequest(accent="red"), "[brand].accent"),
        (BrandRequest(monogram="!"), "[brand].monogram"),
        (BrandRequest(name=""), "[brand].name"),
        (BrandRequest(name="x" * 33), "[brand].name"),
    ],
)
def test_every_rejection_names_the_key_and_leaves_the_home_untouched(
    home: Path, request_: BrandRequest, message: str
) -> None:
    before = snapshot(home)

    with pytest.raises(DeploymentPlanError, match=message.replace("[", r"\[")):
        rebrand_home(home, request_, renderer=FakeRenderer())

    assert snapshot(home) == before


def test_a_png_that_is_not_a_png_is_refused_before_anything_is_written(
    home: Path, tmp_path: Path
) -> None:
    chosen = put(tmp_path / "bad.png", b"not a png")
    before = snapshot(home)

    with pytest.raises(DeploymentPlanError, match=r"\[brand\]\.icon"):
        rebrand_home(home, BrandRequest(icon=chosen), renderer=FakeRenderer())

    assert snapshot(home) == before


def test_an_empty_request_is_refused_and_points_at_regeneration(home: Path) -> None:
    before = snapshot(home)

    with pytest.raises(DeploymentPlanError, match="Nothing to change"):
        rebrand_home(home, BrandRequest(), renderer=FakeRenderer())
    with pytest.raises(DeploymentPlanError, match="Nothing to change"):
        rebrand_home(home, None, renderer=FakeRenderer())

    assert snapshot(home) == before


def test_a_renderer_failure_leaves_the_home_byte_identical(home: Path) -> None:
    before = snapshot(home)

    with pytest.raises(DeploymentPlanError, match="boom"):
        rebrand_home(
            home,
            BrandRequest(name="Lab"),
            renderer=FakeRenderer(error=BrandIconError("boom")),
        )

    assert snapshot(home) == before
    assert not list((home / "brand").glob(".render-*"))


def test_a_failure_while_publishing_names_the_recovery_command(home: Path) -> None:
    (home / "brand" / "brand.png").unlink()
    (home / "brand" / "brand.png").mkdir()

    with pytest.raises(BrandStageError) as caught:
        rebrand_home(home, BrandRequest(name="Lab"), renderer=FakeRenderer())

    assert RECOVERY_COMMAND in str(caught.value)
    assert str(home) in str(caught.value)
    assert load_brand(home / "config.toml").name == "Lab"


def test_a_folder_without_a_config_is_refused(home: Path) -> None:
    (home / "config.toml").unlink()

    with pytest.raises(DeploymentPlanError, match="config.toml"):
        rebrand_home(home, BrandRequest(name="Lab"), renderer=FakeRenderer())


def test_a_home_that_predates_branding_is_refused_and_told_to_update(
    home: Path,
) -> None:
    (home / BRAND_MODULE).unlink()
    before = snapshot(home)

    with pytest.raises(DeploymentPlanError, match="update"):
        rebrand_home(home, BrandRequest(name="Lab"), renderer=FakeRenderer())

    assert snapshot(home) == before


def test_a_missing_folder_is_refused(tmp_path: Path) -> None:
    with pytest.raises(DeploymentPlanError, match="does not exist"):
        rebrand_home(
            tmp_path / "nowhere", BrandRequest(name="Lab"), renderer=FakeRenderer()
        )


def test_a_brand_table_in_the_ui_layer_is_refused(home: Path) -> None:
    put(home / "config.ui.toml", '[brand]\nname = "Ui"\n')
    before = snapshot(home)

    with pytest.raises(DeploymentPlanError, match=r"config\.toml"):
        rebrand_home(home, BrandRequest(name="Lab"), renderer=FakeRenderer())

    assert snapshot(home) == before


def test_a_home_without_a_brand_table_gets_one(home: Path) -> None:
    put(home / "config.toml", "[ui]\nlanguage = 'ru'\n")
    (home / "brand").rename(home.parent / "moved")

    rebrand_home(home, BrandRequest(name="Lab"), renderer=FakeRenderer())

    brand = load_brand(home / "config.toml")
    assert (brand.name, brand.monogram) == ("Lab", "L")
    assert (home / "brand" / "brand.ico").read_bytes() == GOOD_ICO


# --- the read-only check of an existing home ------------------------------------


def test_checking_a_home_with_no_request_answers_with_its_stored_brand(
    home: Path,
) -> None:
    before = snapshot(home)

    answer = check_home_brand(home, {})

    assert answer["ok"] is True
    assert answer["brand"] == {
        "name": "Work",
        "monogram": "W",
        "accent": "#E0A03F",
        "icon": "brand-source/icon.png",
        "is_default": False,
        "origin": "inherited",
    }
    assert answer["icon_preview"] == {
        "kind": "image",
        "path": str((home / "brand-source" / "icon.png").resolve()),
    }
    assert snapshot(home) == before


def test_checking_a_home_applies_the_request_on_top_of_the_stored_brand(
    home: Path,
) -> None:
    answer = check_home_brand(home, {"JARVIS_DEPLOY_BRAND": '{"name": "Lab"}'})

    assert answer["ok"] is True
    assert answer["brand"]["name"] == "Lab"  # type: ignore[index]
    assert answer["brand"]["monogram"] == "W"  # type: ignore[index]


def test_checking_a_home_gives_the_planners_message_and_field(home: Path) -> None:
    answer = check_home_brand(home, {"JARVIS_DEPLOY_BRAND": '{"accent": "red"}'})

    assert answer["ok"] is False
    assert answer["field"] == "accent"
    assert "[brand].accent" in str(answer["message"])


def test_checking_a_home_that_cannot_be_rebranded_says_why(home: Path) -> None:
    (home / BRAND_MODULE).unlink()

    answer = check_home_brand(home, {})

    assert answer["ok"] is False
    assert answer["field"] is None
    assert "update this home first" in str(answer["message"])


def test_checking_a_home_with_a_ui_layer_brand_says_where_it_belongs(
    home: Path,
) -> None:
    put(home / "config.ui.toml", '[brand]\nname = "Ui"\n')

    answer = check_home_brand(home, {})

    assert answer["ok"] is False
    assert "config.toml" in str(answer["message"])
