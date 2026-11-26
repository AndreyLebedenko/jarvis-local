from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from brand_deployment_support import (
    EXAMPLE_CONFIG,
    GOOD_ICO,
    GOOD_PNG,
    USER_PNG,
    FakeRenderer,
    make_source_home,
    put,
)
from png_fixtures import make_png

from jarvis.core.config import BrandSettings, load_brand
from tools.deployment_brand import (
    BRAND_ENVIRONMENT_VARIABLE,
    ICON_SOURCE_PATH,
    BrandRequest,
    BrandStageError,
    apply_brand,
    generate_missing_icons,
    plan_brand,
    request_from_environment,
    request_from_json,
)
from tools.deployment_plan import DeploymentMode, DeploymentPlanError, plan_deployment
from tools.deployment_snapshot import snapshot_layers

CLEAN, COPY = DeploymentMode.CLEAN, DeploymentMode.COPY
WORK_TABLE = (
    '# identity\n[brand]  # who\nname = "Work"\nmonogram = "W"\n'
    'accent = "#E0A03F"\nicon = "brand-source/work.png"\n'
)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return make_source_home(tmp_path / "source")


@pytest.fixture
def branded_source(source: Path) -> Path:
    put(source / "config.toml", "[ui]\nlanguage = 'ru'\n" + WORK_TABLE)
    put(source / "brand-source" / "work.png", USER_PNG)
    put(source / "brand" / "brand.png", b"stale png")
    put(source / "brand" / "brand.ico", b"hand-placed ico")
    return source


def link_directory(link: Path, target: Path) -> None:
    if os.name == "nt":
        subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
        )
    else:
        link.symlink_to(target, target_is_directory=True)


def snapshot(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


def refused(call, pattern: str) -> None:
    with pytest.raises(DeploymentPlanError, match=pattern):
        call()


# --- the request -----------------------------------------------------------


def test_a_request_is_read_from_json_with_every_option() -> None:
    request = request_from_json(
        json.dumps(
            {"name": 'Say "hi"', "monogram": "S", "accent": "#112233", "icon": "a.png"}
        )
    )

    assert request == BrandRequest(
        name='Say "hi"', monogram="S", accent="#112233", icon=Path("a.png")
    )
    assert request_from_json('{"default_brand": true}').default_brand
    assert request_from_json('{"no_icon": true}').no_icon


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{broken", "not valid JSON"),
        ("[]", "must be a JSON object"),
        ('{"colour": "red"}', r"Unknown brand option\(s\): colour"),
        ('{"name": 5}', "-Name must be a str, got 5"),
        ('{"no_icon": "yes"}', "-NoIcon must be a bool"),
        ('{"default_brand": true, "name": "W"}', "-DefaultBrand cannot be combined"),
        ('{"icon": "a.png", "no_icon": true}', "-Icon and -NoIcon cannot be combined"),
    ],
)
def test_a_malformed_or_conflicting_request_is_refused(text: str, message: str) -> None:
    refused(lambda: request_from_json(text), message)


def test_the_environment_variable_carries_the_request_and_absence_means_none() -> None:
    assert request_from_environment({}) is None
    assert request_from_environment({BRAND_ENVIRONMENT_VARIABLE: ""}) is None
    assert request_from_environment(
        {BRAND_ENVIRONMENT_VARIABLE: '{"name": "Работа"}'}
    ) == BrandRequest(name="Работа")


def test_an_empty_request_is_the_absence_of_flags() -> None:
    assert BrandRequest().is_empty
    assert not BrandRequest(default_brand=True).is_empty
    assert not BrandRequest(no_icon=True).is_empty


# --- planning --------------------------------------------------------------


def test_clean_without_flags_is_the_default_brand_and_reads_no_source_config(
    source: Path,
) -> None:
    put(source / "config.toml", "[broken")

    plan = plan_brand(source, CLEAN, None)

    assert plan.is_default
    assert plan.table == {}
    assert plan.origin == "default"
    assert (plan.external_icon, plan.carried_icon, plan.carried_assets) == (
        None,
        None,
        None,
    )


def test_clean_ignores_the_brand_of_a_branded_source(branded_source: Path) -> None:
    plan = plan_brand(branded_source, CLEAN, BrandRequest(accent="#112233"))

    assert plan.table == {"accent": "#112233"}
    assert plan.brand == BrandSettings(accent="#112233")
    assert plan.carried_icon is None
    assert plan.carried_assets is None
    assert plan_brand(branded_source, CLEAN, None).is_default


def test_clean_with_flags_is_requested_and_summarised_for_the_preview(
    source: Path,
) -> None:
    plan = plan_brand(source, CLEAN, BrandRequest(name="Work", accent="#e0a03f"))

    assert plan.table == {"name": "Work", "accent": "#e0a03f"}
    assert plan.preview() == {
        "name": "Work",
        "monogram": "W",
        "accent": "#E0A03F",
        "icon": None,
        "is_default": False,
        "origin": "requested",
    }


def test_clean_with_a_user_icon_records_the_home_relative_path(
    source: Path, tmp_path: Path
) -> None:
    picture = put(tmp_path / "pictures" / "logo.png", USER_PNG)

    plan = plan_brand(source, CLEAN, BrandRequest(icon=picture))

    assert plan.table == {"icon": ICON_SOURCE_PATH}
    assert plan.brand.icon == "brand-source/icon.png"
    assert plan.external_icon == picture.resolve()


def test_copy_without_flags_inherits_everything_by_value(
    branded_source: Path,
) -> None:
    plan = plan_brand(branded_source, COPY, None)

    assert plan.brand == BrandSettings("Work", "W", "#E0A03F", "brand-source/work.png")
    assert plan.origin == "inherited"
    assert plan.carried_assets == branded_source / "brand"
    assert plan.carried_icon == (branded_source / "brand-source/work.png").resolve()


def test_copy_of_a_default_brand_carries_nothing_even_if_a_brand_directory_exists(
    source: Path,
) -> None:
    put(source / "config.toml", "[ui]\nlanguage = 'ru'\n")
    put(source / "brand" / "brand.png", b"leftover")

    plan = plan_brand(source, COPY, None)

    assert plan.is_default
    assert plan.carried_assets is None


def test_copy_tolerates_a_referenced_icon_that_is_missing_when_nothing_is_regenerated(
    branded_source: Path,
) -> None:
    (branded_source / "brand-source/work.png").unlink()

    assert plan_brand(branded_source, COPY, None).carried_icon is None


def test_copy_with_flags_replaces_only_the_given_keys_and_drops_old_icons(
    branded_source: Path,
) -> None:
    plan = plan_brand(branded_source, COPY, BrandRequest(accent="#112233"))

    assert plan.table == {
        "name": "Work",
        "monogram": "W",
        "accent": "#112233",
        "icon": "brand-source/work.png",
    }
    assert plan.origin == "requested"
    assert plan.carried_assets is None
    assert plan.carried_icon == (branded_source / "brand-source/work.png").resolve()


def test_a_stored_name_without_a_monogram_follows_the_new_name(source: Path) -> None:
    put(source / "config.toml", '[brand]\nname = "Work"\n')

    plan = plan_brand(source, COPY, BrandRequest(name="Zed"))

    assert plan.table == {"name": "Zed"}
    assert plan.brand.monogram == "Z"


def test_a_stored_monogram_survives_a_rename(branded_source: Path) -> None:
    plan = plan_brand(branded_source, COPY, BrandRequest(name="Home"))

    assert plan.brand.name == "Home"
    assert plan.brand.monogram == "W"


def test_a_new_icon_replaces_the_inherited_one(
    branded_source: Path, tmp_path: Path
) -> None:
    picture = put(tmp_path / "new.png", make_png(300, 300))

    plan = plan_brand(branded_source, COPY, BrandRequest(icon=picture))

    assert plan.table["icon"] == ICON_SOURCE_PATH
    assert plan.carried_icon is None
    assert plan.external_icon == picture.resolve()


def test_no_icon_drops_only_the_icon(branded_source: Path) -> None:
    plan = plan_brand(branded_source, COPY, BrandRequest(no_icon=True))

    assert plan.brand == BrandSettings("Work", "W", "#E0A03F", None)
    assert "icon" not in plan.table
    assert plan.carried_icon is None
    assert plan.carried_assets is None


def test_default_brand_resets_everything(branded_source: Path) -> None:
    plan = plan_brand(branded_source, COPY, BrandRequest(default_brand=True))

    assert plan.is_default
    assert plan.table == {}
    assert plan.origin == "default"
    assert (plan.carried_icon, plan.carried_assets) == (None, None)


def test_default_brand_in_clean_mode_is_a_harmless_no_op(source: Path) -> None:
    assert plan_brand(source, CLEAN, BrandRequest(default_brand=True)).is_default


@pytest.mark.parametrize(
    ("request_", "message"),
    [
        (BrandRequest(name=""), r"\[brand\]\.name must not be empty"),
        (BrandRequest(name="x" * 33), r"\[brand\]\.name must be at most 32"),
        (BrandRequest(name="a\u0007b"), r"\[brand\]\.name must not contain control"),
        (BrandRequest(monogram="AB"), r"\[brand\]\.monogram must be exactly one"),
        (BrandRequest(accent="red"), r"\[brand\]\.accent must be a #RRGGBB"),
        (BrandRequest(name="!bang"), r"\[brand\]\.monogram cannot be taken from"),
    ],
)
def test_invalid_values_name_the_brand_key(
    source: Path, request_: BrandRequest, message: str
) -> None:
    refused(lambda: plan_brand(source, CLEAN, request_), message)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        pytest.param(b"text, not an image", "is not a PNG file", id="text"),
        pytest.param(
            make_png(32, 32), "shorter side must be at least 64 px", id="tiny"
        ),
        pytest.param(
            make_png(3000, 3000), "longer side must be at most 2048 px", id="huge"
        ),
        pytest.param(
            make_png(500, 100), "must be at most twice as wide as high", id="sliver"
        ),
        pytest.param(make_png(64, 64)[:-40], "is truncated or corrupt", id="cut"),
        pytest.param(b"", "is empty", id="empty"),
    ],
)
def test_an_unusable_user_icon_is_refused_before_anything_is_planned(
    source: Path, tmp_path: Path, data: bytes, message: str
) -> None:
    picture = put(tmp_path / "bad.png", data)

    refused(
        lambda: plan_brand(source, CLEAN, BrandRequest(icon=picture)),
        rf"\[brand\]\.icon \".*bad\.png\": .*{message}",
    )


def test_a_missing_user_icon_is_refused(source: Path, tmp_path: Path) -> None:
    refused(
        lambda: plan_brand(source, CLEAN, BrandRequest(icon=tmp_path / "gone.png")),
        r"\[brand\]\.icon .*file not found",
    )


def test_a_missing_inherited_icon_is_refused_when_a_regeneration_will_happen(
    branded_source: Path,
) -> None:
    (branded_source / "brand-source/work.png").unlink()

    refused(
        lambda: plan_brand(branded_source, COPY, BrandRequest(accent="#112233")),
        r"\[brand\]\.icon \"brand-source/work\.png\": file not found",
    )


def test_a_brand_in_the_source_ui_layer_is_not_something_a_copy_can_start_from(
    source: Path,
) -> None:
    put(source / "config.toml", WORK_TABLE)
    put(source / "config.ui.toml", '[brand]\nname = "Hidden"\n')
    refused(
        lambda: plan_deployment(source, source.parent / "new", COPY),
        r"\[brand\].*belongs in config\.toml",
    )


def test_planning_writes_nothing(branded_source: Path, tmp_path: Path) -> None:
    before = snapshot(tmp_path)

    plan_brand(branded_source, COPY, BrandRequest(name="Home"))
    plan_brand(branded_source, COPY, None)
    plan_brand(branded_source, CLEAN, BrandRequest(name="Home"))

    assert snapshot(tmp_path) == before


def test_a_linked_brand_directory_is_refused(
    branded_source: Path, tmp_path: Path
) -> None:
    real = tmp_path / "elsewhere"
    put(real / "brand.png", b"x")
    for child in (branded_source / "brand").iterdir():
        child.unlink()
    (branded_source / "brand").rmdir()
    link_directory(branded_source / "brand", real)

    refused(
        lambda: plan_brand(branded_source, COPY, None),
        "Cannot copy a linked brand directory",
    )


def test_a_nested_link_inside_the_brand_directory_is_refused(
    branded_source: Path, tmp_path: Path
) -> None:
    real = tmp_path / "elsewhere"
    real.mkdir()
    link_directory(branded_source / "brand" / "nested", real)

    refused(
        lambda: plan_brand(branded_source, COPY, None),
        r"Cannot copy a nested linked path: .*nested",
    )


# --- writing the destination -------------------------------------------------


@pytest.fixture
def target(tmp_path: Path) -> Path:
    home = tmp_path / "target"
    put(home / "config.example.toml", EXAMPLE_CONFIG)
    return home


def test_clean_without_flags_writes_no_config_and_no_files(
    source: Path, target: Path
) -> None:
    before = snapshot(target)

    apply_brand(plan_brand(source, CLEAN, None), target)

    assert snapshot(target) == before
    assert not (target / "config.toml").exists()


def test_clean_with_flags_is_the_example_plus_the_brand_table(
    source: Path, target: Path
) -> None:
    apply_brand(plan_brand(source, CLEAN, BrandRequest(name="Work")), target)

    assert (target / "config.toml").read_text(encoding="utf-8") == (
        EXAMPLE_CONFIG + '\n[brand]\nname = "Work"\n'
    )
    assert load_brand(target / "config.toml") == BrandSettings("Work", "W")
    assert (target / "config.example.toml").read_text(
        encoding="utf-8"
    ) == EXAMPLE_CONFIG


def test_clean_default_brand_writes_nothing(source: Path, target: Path) -> None:
    apply_brand(plan_brand(source, CLEAN, BrandRequest(default_brand=True)), target)

    assert not (target / "config.toml").exists()


def test_a_user_icon_is_copied_by_value_next_to_the_recorded_path(
    source: Path, target: Path, tmp_path: Path
) -> None:
    picture = put(tmp_path / "pictures" / "logo.png", USER_PNG)

    apply_brand(plan_brand(source, CLEAN, BrandRequest(icon=picture)), target)

    assert (target / "brand-source" / "icon.png").read_bytes() == USER_PNG
    assert load_brand(target / "config.toml").icon == "brand-source/icon.png"
    assert picture.read_bytes() == USER_PNG


def prepare_copy(source: Path, target: Path, request: BrandRequest | None) -> bytes:
    """What the snapshot step leaves: the source config verbatim."""
    config = (source / "config.toml").read_bytes()
    (target / "config.toml").write_bytes(config)
    apply_brand(plan_brand(source, COPY, request), target)
    return config


def test_a_faithful_copy_keeps_the_config_bytes_and_carries_files_by_value(
    branded_source: Path, target: Path
) -> None:
    config = prepare_copy(branded_source, target, None)

    assert (target / "config.toml").read_bytes() == config
    assert (target / "brand" / "brand.png").read_bytes() == b"stale png"
    assert (target / "brand" / "brand.ico").read_bytes() == b"hand-placed ico"
    assert (target / "brand-source/work.png").read_bytes() == USER_PNG


def test_an_override_changes_only_its_keys_and_keeps_comments_and_other_tables(
    branded_source: Path, target: Path
) -> None:
    prepare_copy(branded_source, target, BrandRequest(name="Home", accent="#112233"))

    assert (target / "config.toml").read_text(encoding="utf-8") == (
        "[ui]\nlanguage = 'ru'\n"
        '# identity\n[brand]  # who\nname = "Home"\nmonogram = "W"\n'
        'accent = "#112233"\nicon = "brand-source/work.png"\n'
    )
    assert not (target / "brand").exists()
    assert (target / "brand-source/work.png").read_bytes() == USER_PNG


def test_no_icon_removes_the_key_and_the_file_is_not_carried(
    branded_source: Path, target: Path
) -> None:
    prepare_copy(branded_source, target, BrandRequest(no_icon=True))

    assert "icon" not in (target / "config.toml").read_text(encoding="utf-8")
    assert not (target / "brand-source").exists()
    assert load_brand(target / "config.toml") == BrandSettings("Work", "W", "#E0A03F")


def test_default_brand_removes_the_table_and_everything_it_referenced(
    branded_source: Path, target: Path
) -> None:
    prepare_copy(branded_source, target, BrandRequest(default_brand=True))

    assert (target / "config.toml").read_text(encoding="utf-8") == (
        "[ui]\nlanguage = 'ru'\n# identity\n"
    )
    assert not (target / "brand").exists()
    assert not (target / "brand-source").exists()
    assert load_brand(target / "config.toml") == BrandSettings()


def test_a_copy_of_a_source_without_a_config_starts_from_the_example(
    source: Path, target: Path
) -> None:
    apply_brand(plan_brand(source, COPY, BrandRequest(name="Home")), target)

    assert (target / "config.toml").read_text(encoding="utf-8") == (
        EXAMPLE_CONFIG + '\n[brand]\nname = "Home"\n'
    )


def test_a_hostile_name_reaches_the_destination_unchanged(
    source: Path, target: Path
) -> None:
    name = 'R&D "50%" \\ <b>Ж</b>'

    apply_brand(
        plan_brand(source, CLEAN, BrandRequest(name=name, monogram="R")), target
    )

    assert load_brand(target / "config.toml").name == name


def test_a_brand_in_the_destination_ui_layer_stops_the_deployment(
    source: Path, target: Path
) -> None:
    put(target / "config.ui.toml", '[brand]\nname = "Hidden"\n')

    refused(
        lambda: apply_brand(plan_brand(source, CLEAN, BrandRequest(name="W")), target),
        r"\[brand\].*belongs in config\.toml",
    )
    assert not (target / "config.toml").exists()


def test_an_unsupported_destination_form_is_refused_and_nothing_is_written(
    branded_source: Path, target: Path
) -> None:
    original = b'brand = {name = "Work"}\n'
    put(target / "config.toml", original)
    plan = plan_brand(branded_source, COPY, BrandRequest(name="Home"))

    refused(
        lambda: apply_brand(plan, target), r"Cannot rewrite \[brand\].*config\.toml"
    )
    assert (target / "config.toml").read_bytes() == original


# --- the icon stage ---------------------------------------------------------


def test_a_default_brand_never_reaches_the_generator(target: Path) -> None:
    renderer = FakeRenderer()
    put(target / "config.toml", "[ui]\nlanguage = 'en'\n")

    assert generate_missing_icons(target, renderer=renderer) is None
    assert renderer.requests == []


def test_a_missing_config_is_the_default_brand(target: Path) -> None:
    renderer = FakeRenderer()

    assert generate_missing_icons(target, renderer=renderer) is None
    assert renderer.requests == []


def test_a_missing_home_is_refused_before_the_generator_is_called(
    tmp_path: Path,
) -> None:
    renderer = FakeRenderer()

    with pytest.raises(BrandStageError, match="destination home does not exist"):
        generate_missing_icons(tmp_path / "absent", renderer=renderer)
    assert renderer.requests == []


def test_a_branded_home_without_icons_gets_both_files(target: Path) -> None:
    put(
        target / "config.toml",
        WORK_TABLE.replace('icon = "brand-source/work.png"\n', ""),
    )
    renderer = FakeRenderer()

    message = generate_missing_icons(target, renderer=renderer)

    assert message == f"Generated brand icons in {target / 'brand'}"
    assert (target / "brand" / "brand.png").read_bytes() == GOOD_PNG
    assert (target / "brand" / "brand.ico").read_bytes() == GOOD_ICO
    assert len(renderer.requests) == 1


@pytest.mark.parametrize("missing", ["brand.png", "brand.ico"])
def test_a_home_missing_either_file_is_completed(target: Path, missing: str) -> None:
    put(target / "config.toml", '[brand]\nname = "Work"\n')
    put(target / "brand" / "brand.png", b"old")
    put(target / "brand" / "brand.ico", b"old")
    (target / "brand" / missing).unlink()

    generate_missing_icons(target, renderer=FakeRenderer())

    assert (target / "brand" / "brand.png").read_bytes() == GOOD_PNG
    assert (target / "brand" / "brand.ico").read_bytes() == GOOD_ICO


def test_existing_icons_are_kept_even_when_stale(target: Path) -> None:
    put(target / "config.toml", '[brand]\nname = "Work"\n')
    put(target / "brand" / "brand.png", b"stale")
    put(target / "brand" / "brand.ico", b"hand-placed")
    renderer = FakeRenderer()

    assert generate_missing_icons(target, renderer=renderer) is None
    assert renderer.requests == []
    assert (target / "brand" / "brand.ico").read_bytes() == b"hand-placed"


# --- refusals decided in planning ---------------------------------------------


def commute_source(home: Path, config: str) -> Path:
    make_source_home(home)
    put(home / "config.toml", config)
    put(home / "brand-source" / "work.png", USER_PNG)
    return home


def rebased_config(source: Path) -> str:
    plan = plan_deployment(source, source.parent / f"new-{source.name}", COPY)
    layers = {
        name: content for name, content, _ in snapshot_layers(source, plan.snapshot)
    }
    return layers[Path("config.toml")]


def test_path_rebasing_and_the_brand_rewrite_give_the_same_text_in_either_order(
    tmp_path: Path,
) -> None:
    config = (
        "# top\n"
        f"[journal]\nroot = {json.dumps(str(tmp_path / 'outside'))}  # absolute\n"
        + WORK_TABLE
        + "[memory]\nroot = 'mem'\n"
    )
    request = BrandRequest(name="Home", accent="#112233")
    rebase_first = commute_source(tmp_path / "rebase-first", config)
    plan = plan_brand(rebase_first, COPY, request)
    target = tmp_path / "target"
    put(target / "config.toml", rebased_config(rebase_first))
    apply_brand(plan, target)

    brand_first = commute_source(tmp_path / "brand-first", config)
    scratch = tmp_path / "scratch"
    put(scratch / "config.toml", config)
    apply_brand(plan_brand(brand_first, COPY, request), scratch)
    put(brand_first / "config.toml", (scratch / "config.toml").read_text("utf-8"))

    assert (target / "config.toml").read_text("utf-8") == rebased_config(brand_first)
    assert '"journal"' in rebased_config(brand_first)
    assert 'name = "Home"' in rebased_config(brand_first)


@pytest.mark.parametrize(
    "brand_text",
    ['brand = {name = "Work"}\n', 'brand.name = "Work"\n'],
    ids=["inline-table", "dotted-keys"],
)
@pytest.mark.parametrize(
    "request_",
    [BrandRequest(name="Home"), BrandRequest(default_brand=True)],
    ids=["override", "default-brand"],
)
def test_an_unsupported_source_form_is_refused_naming_the_source_file(
    source: Path, brand_text: str, request_: BrandRequest
) -> None:
    put(source / "config.toml", brand_text + "[ui]\nlanguage = 'ru'\n")

    refused(
        lambda: plan_brand(source, COPY, request_),
        r"Cannot rewrite \[brand\] in .*source.config\.toml",
    )


def test_a_faithful_copy_of_an_unsupported_form_is_still_planned(source: Path) -> None:
    put(source / "config.toml", 'brand = {name = "Work"}\n')

    assert plan_brand(source, COPY, None).brand.name == "Work"


def test_clean_never_reads_the_source_config_for_the_dry_run(source: Path) -> None:
    put(source / "config.toml", 'brand = {name = "Work"}\n')

    assert plan_brand(source, CLEAN, BrandRequest(name="Home")).brand.name == "Home"


def test_an_unsupported_brand_form_in_the_example_is_refused_for_clean(
    source: Path,
) -> None:
    put(source / "config.example.toml", 'brand = {name = "Example"}\n')

    refused(
        lambda: plan_brand(source, CLEAN, BrandRequest(name="Home")),
        r"Cannot rewrite \[brand\] in .*config\.example\.toml",
    )


def test_an_icon_cannot_be_named_like_a_managed_file(source: Path) -> None:
    put(source / "config.toml", '[brand]\nicon = "config.toml"\n')

    refused(
        lambda: plan_brand(source, COPY, None),
        r"\[brand\]\.icon must name a \.png file",
    )


def test_an_icon_that_is_a_generated_brand_file_is_refused_when_regenerating(
    source: Path,
) -> None:
    put(source / "config.toml", '[brand]\nname = "Work"\nicon = "brand/brand.png"\n')
    put(source / "brand" / "brand.png", USER_PNG)

    refused(
        lambda: plan_brand(source, COPY, BrandRequest(accent="#112233")),
        r'\[brand\]\.icon "brand/brand\.png": is a generated brand file',
    )
    assert plan_brand(source, COPY, None).brand.icon == "brand/brand.png"
