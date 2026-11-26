from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

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

from jarvis.core.brand_icon import BrandIconError
from jarvis.core.brand_render import ImageRequest, MonogramStyle
from jarvis.core.config import BrandSettings, load_brand
from tools import deployment
from tools.deployment_brand import BrandRequest
from tools.deployment_plan import DeploymentMode, DeploymentPlanError

CLEAN, COPY = DeploymentMode.CLEAN, DeploymentMode.COPY
WORK_TABLE = (
    '# identity\n[brand]  # who\nname = "Work"\nmonogram = "W"\n'
    'accent = "#E0A03F"\nicon = "brand-source/work.png"\n'
)


@pytest.fixture(autouse=True)
def runtime_mutex(monkeypatch: pytest.MonkeyPatch) -> str:
    name = f"Local\\Jarvis.BrandDeployTest.{uuid4().hex}"
    monkeypatch.setattr(deployment, "MUTEX_NAME", name)
    return name


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


def manifest_phase(target: Path) -> str:
    return json.loads((target / deployment.MANIFEST).read_text(encoding="utf-8"))[
        "phase"
    ]


def result_line(output: str) -> dict[str, str]:
    lines = [
        line
        for line in output.splitlines()
        if line.startswith(deployment.RESULT_PREFIX)
    ]
    assert len(lines) == 1, output
    return json.loads(lines[0].removeprefix(deployment.RESULT_PREFIX))


class RecordingInstaller:
    """Records what the home looked like when the installer ran."""

    def __init__(self, code: int = 0) -> None:
        self.code = code
        self.homes: list[Path] = []
        self.config: list[str | None] = []
        self.icons: list[bool] = []

    def __call__(self, target: Path, assume_yes: bool) -> int:
        self.homes.append(target)
        config = target / "config.toml"
        self.config.append(
            config.read_text(encoding="utf-8") if config.exists() else None
        )
        self.icons.append((target / "brand" / "brand.ico").is_file())
        return self.code


def run(
    source: Path,
    target: Path,
    *,
    mode: DeploymentMode = CLEAN,
    brand: BrandRequest | None = None,
    renderer: FakeRenderer | None = None,
    installer: RecordingInstaller | None = None,
    resume: bool = False,
) -> int:
    return deployment.deploy(
        source,
        target,
        mode=mode,
        brand=brand,
        resume=resume,
        renderer=renderer or FakeRenderer(),
        installer=installer or RecordingInstaller(),
    )


# --- Clean ---------------------------------------------------------------------


def test_clean_without_flags_is_unchanged_by_the_brand_work(
    source: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "new home"
    installer, renderer = RecordingInstaller(), FakeRenderer()

    assert run(source, target, installer=installer, renderer=renderer) == 0

    assert installer.config == [None]
    assert not (target / "config.toml").exists()
    assert not (target / "brand").exists()
    assert not (target / "brand-source").exists()
    assert renderer.requests == []
    assert result_line(capsys.readouterr().out) == {
        "target": str(target),
        "shortcut_file": "Jarvis - new home.lnk",
        "shortcut_icon": str(target / "src/jarvis/launcher/assets/jarvis.ico"),
    }


def test_clean_from_a_branded_source_inherits_nothing(
    branded_source: Path, tmp_path: Path
) -> None:
    target = tmp_path / "clean"
    installer = RecordingInstaller()

    assert run(branded_source, target, installer=installer) == 0

    assert installer.config == [None]
    for name in ("brand", "brand-source", "config.toml"):
        assert not (target / name).exists()


def test_clean_with_flags_is_the_example_plus_the_brand_with_icons_before_install(
    source: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "work home"
    installer, renderer = RecordingInstaller(), FakeRenderer()
    request = BrandRequest(name="Work", monogram="W", accent="#E0A03F")

    assert (
        run(source, target, brand=request, installer=installer, renderer=renderer) == 0
    )

    assert installer.config == [
        EXAMPLE_CONFIG
        + ('\n[brand]\nname = "Work"\nmonogram = "W"\naccent = "#E0A03F"\n')
    ]
    assert installer.icons == [True]
    assert (target / "brand" / "brand.png").read_bytes() == GOOD_PNG
    assert (target / "brand" / "brand.ico").read_bytes() == GOOD_ICO
    assert isinstance(renderer.requests[0], MonogramStyle)
    assert load_brand(target / "config.toml") == BrandSettings("Work", "W", "#E0A03F")
    assert manifest_phase(target) == "complete"
    shortcut = result_line(capsys.readouterr().out)
    assert shortcut["shortcut_file"] == "Work - work home.lnk"
    assert shortcut["shortcut_icon"] == str(target / "brand" / "brand.ico")


def test_clean_with_a_user_png_copies_it_and_renders_that_image(
    source: Path, tmp_path: Path
) -> None:
    picture = put(tmp_path / "pictures" / "logo.png", USER_PNG)
    target = tmp_path / "icon home"
    renderer = FakeRenderer()

    assert run(source, target, brand=BrandRequest(icon=picture), renderer=renderer) == 0

    assert (target / "brand-source" / "icon.png").read_bytes() == USER_PNG
    assert load_brand(target / "config.toml").icon == "brand-source/icon.png"
    assert isinstance(renderer.requests[0], ImageRequest)
    assert (
        renderer.requests[0].source == (target / "brand-source" / "icon.png").resolve()
    )


@pytest.mark.parametrize(
    "request_",
    [
        BrandRequest(name="x" * 33),
        BrandRequest(monogram="AB"),
        BrandRequest(accent="red"),
    ],
)
def test_an_invalid_request_fails_before_the_destination_exists(
    source: Path, tmp_path: Path, request_: BrandRequest
) -> None:
    target = tmp_path / "never"
    installer = RecordingInstaller()

    with pytest.raises(DeploymentPlanError, match=r"\[brand\]\."):
        run(source, target, brand=request_, installer=installer)

    assert not target.exists()
    assert installer.homes == []


def test_an_unusable_user_png_fails_before_the_destination_exists(
    source: Path, tmp_path: Path
) -> None:
    picture = put(tmp_path / "bad.png", b"not a png")
    target = tmp_path / "never"

    with pytest.raises(DeploymentPlanError, match=r"\[brand\]\.icon .*bad\.png"):
        run(source, target, brand=BrandRequest(icon=picture))

    assert not target.exists()


def test_an_invalid_copy_override_fails_before_the_destination_exists(
    branded_source: Path, tmp_path: Path
) -> None:
    target = tmp_path / "never"

    with pytest.raises(DeploymentPlanError, match=r"\[brand\]\.accent"):
        run(branded_source, target, mode=COPY, brand=BrandRequest(accent="nope"))

    assert not target.exists()


# --- Copy ----------------------------------------------------------------------


def test_a_faithful_copy_keeps_a_stale_brand_directory_and_never_regenerates(
    branded_source: Path, tmp_path: Path
) -> None:
    target = tmp_path / "copy"
    renderer = FakeRenderer()

    assert run(branded_source, target, mode=COPY, renderer=renderer) == 0

    assert (target / "config.toml").read_bytes() == (
        branded_source / "config.toml"
    ).read_bytes()
    assert (target / "brand" / "brand.png").read_bytes() == b"stale png"
    assert (target / "brand" / "brand.ico").read_bytes() == b"hand-placed ico"
    assert (target / "brand-source" / "work.png").read_bytes() == USER_PNG
    assert renderer.requests == []


def test_a_faithful_copy_of_a_brand_that_was_never_generated_gets_its_icons(
    branded_source: Path, tmp_path: Path
) -> None:
    for child in (branded_source / "brand").iterdir():
        child.unlink()
    (branded_source / "brand").rmdir()
    target = tmp_path / "copy"
    renderer = FakeRenderer()

    assert run(branded_source, target, mode=COPY, renderer=renderer) == 0

    assert (target / "brand" / "brand.ico").read_bytes() == GOOD_ICO
    assert len(renderer.requests) == 1


def test_a_copy_override_regenerates_and_does_not_carry_the_source_icons(
    branded_source: Path, tmp_path: Path
) -> None:
    target = tmp_path / "copy"
    installer, renderer = RecordingInstaller(), FakeRenderer()

    assert (
        run(
            branded_source,
            target,
            mode=COPY,
            brand=BrandRequest(name="Home"),
            installer=installer,
            renderer=renderer,
        )
        == 0
    )

    assert (target / "brand" / "brand.ico").read_bytes() == GOOD_ICO
    assert isinstance(renderer.requests[0], ImageRequest)
    assert load_brand(target / "config.toml") == BrandSettings(
        "Home", "W", "#E0A03F", "brand-source/work.png"
    )
    assert (target / "brand-source" / "work.png").read_bytes() == USER_PNG
    assert (
        (target / "config.toml")
        .read_text(encoding="utf-8")
        .startswith(
            "[ui]\nlanguage = 'ru'\n# identity\n[brand]  # who\nname = \"Home\"\n"
        )
    )


def test_a_copy_can_be_reset_to_the_default_brand(
    branded_source: Path, tmp_path: Path
) -> None:
    target = tmp_path / "copy"
    renderer = FakeRenderer()

    assert (
        run(
            branded_source,
            target,
            mode=COPY,
            brand=BrandRequest(default_brand=True),
            renderer=renderer,
        )
        == 0
    )

    assert load_brand(target / "config.toml") == BrandSettings()
    for name in ("brand", "brand-source"):
        assert not (target / name).exists()
    assert renderer.requests == []


def test_the_source_is_never_modified_by_a_branded_copy(
    branded_source: Path, tmp_path: Path
) -> None:
    before = {
        path: path.read_bytes() for path in branded_source.rglob("*") if path.is_file()
    }

    run(branded_source, tmp_path / "copy", mode=COPY, brand=BrandRequest(name="Home"))

    assert before == {
        path: path.read_bytes() for path in branded_source.rglob("*") if path.is_file()
    }


UNSUPPORTED_BRAND_FORMS = {
    "inline-table": 'brand = {name = "Work", monogram = "W"}\n',
    "dotted-keys": 'brand.name = "Work"\nbrand.monogram = "W"\n',
}


@pytest.fixture(params=sorted(UNSUPPORTED_BRAND_FORMS))
def unsupported_source(request: pytest.FixtureRequest, source: Path) -> Path:
    put(
        source / "config.toml",
        UNSUPPORTED_BRAND_FORMS[request.param] + "[ui]\nlanguage = 'ru'\n",
    )
    return source


@pytest.mark.parametrize(
    "request_",
    [BrandRequest(name="Home"), BrandRequest(default_brand=True)],
    ids=["override", "default-brand"],
)
def test_an_unsupported_source_brand_form_is_refused_before_the_destination_exists(
    unsupported_source: Path, tmp_path: Path, request_: BrandRequest
) -> None:
    target = tmp_path / "never"
    installer = RecordingInstaller()

    with pytest.raises(
        DeploymentPlanError, match=r"Cannot rewrite \[brand\] in .*source.config\.toml"
    ):
        run(unsupported_source, target, mode=COPY, brand=request_, installer=installer)

    assert not target.exists()
    assert installer.homes == []
    with pytest.raises(DeploymentPlanError, match=r"Cannot rewrite \[brand\]"):
        deployment.preview_deployment(
            unsupported_source, target, COPY, resume=False, brand=request_
        )
    assert not target.exists()


def test_a_faithful_copy_of_an_unsupported_brand_form_still_works(
    unsupported_source: Path, tmp_path: Path
) -> None:
    target = tmp_path / "copy"

    assert run(unsupported_source, target, mode=COPY) == 0

    assert (target / "config.toml").read_bytes() == (
        unsupported_source / "config.toml"
    ).read_bytes()
    assert load_brand(target / "config.toml").name == "Work"


# --- the icon stage in the state machine -----------------------------------------


@pytest.mark.parametrize("mode", [CLEAN, COPY], ids=["clean", "copy"])
def test_a_failed_icon_stage_is_resumable_without_recopying_or_the_source(
    source: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mode: DeploymentMode,
) -> None:
    put(source / "journal" / "events.jsonl", b"history")
    target = tmp_path / "new"
    installer = RecordingInstaller()
    failing = FakeRenderer(error=BrandIconError("The icon renderer failed (exit 1): x"))
    request = BrandRequest(name="Work")

    code = run(
        source, target, mode=mode, brand=request, renderer=failing, installer=installer
    )

    assert code == 1
    output = capsys.readouterr().out
    assert (
        "[failed] Generate brand icons: The icon renderer failed (exit 1): x" in output
    )
    assert "Use -Resume after addressing the error." in output
    assert installer.homes == []
    assert manifest_phase(target) == "ready"
    assert not (target / "brand" / "brand.ico").exists()
    assert deployment.RESULT_PREFIX not in output
    prepared = (target / "config.toml").read_bytes()
    assert (target / "journal" / "events.jsonl").exists() == (mode is COPY)
    shutil.rmtree(source)

    resumed = run(
        source,
        target,
        mode=mode,
        resume=True,
        renderer=FakeRenderer(),
        installer=installer,
    )

    assert resumed == 0
    assert (target / "config.toml").read_bytes() == prepared
    assert (target / "brand" / "brand.ico").read_bytes() == GOOD_ICO
    if mode is COPY:
        assert (target / "journal" / "events.jsonl").read_bytes() == b"history"
    assert installer.homes == [target]
    assert manifest_phase(target) == "complete"
    assert result_line(capsys.readouterr().out)["shortcut_file"] == "Work - new.lnk"


def test_a_rejected_png_in_the_destination_is_reported_at_the_stage_and_retried(
    source: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    picture = put(tmp_path / "logo.png", USER_PNG)
    target = tmp_path / "new"
    run(
        source,
        target,
        brand=BrandRequest(icon=picture),
        installer=RecordingInstaller(7),
    )
    (target / "brand-source" / "icon.png").write_bytes(b"replaced by text")
    for child in (target / "brand").iterdir():
        child.unlink()
    capsys.readouterr()

    assert run(source, target, resume=True) == 1

    assert (
        '[failed] Generate brand icons: [brand].icon "brand-source/icon.png": '
        "is not a PNG file (bad signature)"
    ) in capsys.readouterr().out
    assert manifest_phase(target) == "ready"

    (target / "brand-source" / "icon.png").write_bytes(USER_PNG)
    assert run(source, target, resume=True) == 0
    assert manifest_phase(target) == "complete"


def test_a_resume_after_an_installer_failure_does_not_generate_again(
    source: Path, tmp_path: Path
) -> None:
    target = tmp_path / "new"
    first = FakeRenderer()
    assert (
        run(
            source,
            target,
            brand=BrandRequest(name="Work"),
            renderer=first,
            installer=RecordingInstaller(7),
        )
        == 7
    )
    assert len(first.requests) == 1
    assert manifest_phase(target) == "ready"

    second = FakeRenderer()
    assert run(source, target, resume=True, renderer=second) == 0

    assert second.requests == []


def test_a_default_brand_never_reaches_the_renderer_in_any_mode(
    source: Path, tmp_path: Path
) -> None:
    renderer = FakeRenderer()

    run(source, tmp_path / "clean", renderer=renderer)
    run(source, tmp_path / "copy", mode=COPY, renderer=renderer)

    assert renderer.requests == []


def test_resume_refuses_brand_options_and_leaves_the_destination_alone(
    source: Path, tmp_path: Path
) -> None:
    target = tmp_path / "new"
    run(source, target, installer=RecordingInstaller(7))
    marker = (target / deployment.MANIFEST).read_bytes()

    with pytest.raises(deployment.DeploymentError, match="cannot be changed while"):
        run(source, target, resume=True, brand=BrandRequest(name="Late"))

    assert (target / deployment.MANIFEST).read_bytes() == marker
    assert run(source, target, resume=True, brand=BrandRequest()) == 0


def test_the_stage_stops_for_a_destination_home_that_does_not_exist(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    renderer = FakeRenderer()

    code = deployment._install_prepared(
        tmp_path / "absent", CLEAN, False, RecordingInstaller(), renderer
    )

    assert code == 1
    assert "destination home does not exist" in capsys.readouterr().out
    assert renderer.requests == []


# --- preview and entry point ---------------------------------------------------------


def test_the_preview_validates_and_describes_the_brand_without_writing(
    branded_source: Path, tmp_path: Path
) -> None:
    target = tmp_path / "preview"

    preview = deployment.preview_deployment(
        branded_source, target, COPY, resume=False, brand=BrandRequest(name="Home")
    )

    assert preview["brand"] == {
        "name": "Home",
        "monogram": "W",
        "accent": "#E0A03F",
        "icon": "brand-source/work.png",
        "is_default": False,
        "origin": "requested",
    }
    assert not target.exists()
    with pytest.raises(DeploymentPlanError, match=r"\[brand\]\.monogram"):
        deployment.preview_deployment(
            branded_source,
            target,
            COPY,
            resume=False,
            brand=BrandRequest(monogram="AB"),
        )


def test_a_preview_of_a_default_clean_deployment_reports_the_default_brand(
    source: Path, tmp_path: Path
) -> None:
    preview = deployment.preview_deployment(
        source, tmp_path / "preview", CLEAN, resume=False
    )

    assert preview["brand"] == {
        "name": "Jarvis",
        "monogram": "J",
        "accent": "#3FE0D0",
        "icon": None,
        "is_default": True,
        "origin": "default",
    }


def test_the_resume_preview_refuses_brand_options(source: Path, tmp_path: Path) -> None:
    with pytest.raises(deployment.DeploymentError, match="cannot be changed while"):
        deployment.preview_deployment(
            source, tmp_path / "x", CLEAN, resume=True, brand=BrandRequest(name="W")
        )


def test_main_reads_the_brand_from_the_environment(
    source: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "JARVIS_DEPLOY_BRAND", json.dumps({"name": 'Say "hi"', "monogram": "S"})
    )
    arguments = ["--source", str(source), "--target", str(tmp_path / "t")]

    assert deployment.main([*arguments, "--preview"]) == 0

    line = capsys.readouterr().out.strip().removeprefix(deployment.PREVIEW_PREFIX)
    assert json.loads(line)["brand"]["name"] == 'Say "hi"'


def test_main_reports_a_bad_brand_as_an_error_line_and_exit_code_one(
    source: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("JARVIS_DEPLOY_BRAND", '{"monogram": "AB"}')

    code = deployment.main(
        ["--source", str(source), "--target", str(tmp_path / "t"), "--preview"]
    )

    assert code == 1
    assert "ERROR: [brand].monogram must be exactly one" in capsys.readouterr().err
    assert not (tmp_path / "t").exists()


def test_the_installer_does_not_inherit_the_brand_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JARVIS_DEPLOY_BRAND", '{"name": "Work"}')
    seen: dict[str, str] = {}

    def fake_run(args, *, cwd, env, check):
        seen.update(env)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(deployment.subprocess, "run", fake_run)

    assert deployment._run_installer(tmp_path, False) == 0
    assert "JARVIS_DEPLOY_BRAND" not in seen
