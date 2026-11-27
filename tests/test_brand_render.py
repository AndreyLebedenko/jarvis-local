import ast
import subprocess
import sys
from pathlib import Path

import pytest
from png_fixtures import make_ico, make_png

import jarvis.core.brand_render as render
from jarvis.core.brand_icon import ICO_FRAME_SIZES, BrandIconError, FitRectangle
from jarvis.core.brand_render import (
    DEFAULT_IDENTITY_MESSAGE,
    GLYPH_GRAPHITE,
    GLYPH_WHITE,
    ImageDecodeError,
    ImageRequest,
    MonogramStyle,
    build_request,
    command_line,
    generate_brand_assets,
    main,
    monogram_style,
    regenerate_home_icons,
    run_powershell_renderer,
)
from jarvis.core.config import BrandSettings, ConfigError

GOOD_PNG = make_png(512, 512)
GOOD_ICO = make_ico([(side, make_png(side, side)) for side in ICO_FRAME_SIZES])
WORK = BrandSettings(name="Work", monogram="W", accent="#E0A03F")


class FakeRenderer:
    def __init__(self, png=GOOD_PNG, ico=GOOD_ICO, error=None):
        self.png, self.ico, self.error = png, ico, error
        self.requests = []
        self.staging = []

    def __call__(self, request, output_png, output_ico):
        self.requests.append(request)
        self.staging.append(output_png.parent)
        if self.error is not None:
            raise self.error
        output_png.write_bytes(self.png)
        output_ico.write_bytes(self.ico)


def write_config(home: Path, text: str) -> None:
    (home / "config.toml").write_text(text, encoding="utf-8")


@pytest.mark.parametrize(
    ("accent", "glyph"),
    [
        ("#3FE0D0", GLYPH_GRAPHITE),
        ("#E0A03F", GLYPH_GRAPHITE),
        ("#FFFFFF", GLYPH_GRAPHITE),
        ("#808080", GLYPH_GRAPHITE),
        ("#FF0000", GLYPH_GRAPHITE),
        ("#000000", GLYPH_WHITE),
        ("#0000FF", GLYPH_WHITE),
        ("#1F3A93", GLYPH_WHITE),
        ("#0A0D14", GLYPH_WHITE),
    ],
)
def test_the_letter_colour_is_whichever_contrasts_more_with_the_accent(accent, glyph):
    brand = BrandSettings(accent=accent)

    assert monogram_style(brand).glyph == glyph


@pytest.mark.parametrize(
    ("monogram", "code_point"),
    [("W", 0x57), ("Ж", 0x416), ("7", 0x37), ("ё".upper(), 0x401)],
)
def test_the_monogram_travels_as_a_code_point(monogram, code_point):
    style = monogram_style(BrandSettings(name="X", monogram=monogram))

    assert style.code_point == code_point


def test_the_disc_is_the_accent_and_the_art_constants_are_fixed():
    style = monogram_style(WORK)

    assert style.disc == "#E0A03F"
    assert (style.canvas, style.disc_margin) == (512, 8)
    assert (style.glyph_height_ratio, style.glyph_width_ratio) == (0.5, 0.62)


def test_a_brand_without_an_icon_builds_a_monogram_request(tmp_path):
    assert build_request(tmp_path, WORK) == monogram_style(WORK)


def test_a_brand_with_an_icon_builds_a_fitted_image_request(tmp_path):
    (tmp_path / "logo.png").write_bytes(make_png(200, 100))
    brand = BrandSettings(name="Work", monogram="W", icon="logo.png")

    request = build_request(tmp_path, brand)

    assert request == ImageRequest(
        (tmp_path / "logo.png").resolve(), FitRectangle(0, 128, 512, 256), 512
    )


def test_building_a_request_rejects_an_invalid_icon_with_the_key(tmp_path):
    (tmp_path / "logo.png").write_bytes(b"text")
    brand = BrandSettings(name="Work", monogram="W", icon="logo.png")

    with pytest.raises(
        BrandIconError, match=r'\[brand\]\.icon "logo.png": is not a PNG'
    ):
        build_request(tmp_path, brand)


def arguments_of(command: list[str]) -> dict[str, str]:
    values = command[command.index("-File") + 2 :]
    return dict(zip(values[::2], values[1::2], strict=True))


def test_the_monogram_command_line_names_every_parameter(tmp_path):
    command = command_line(monogram_style(WORK), tmp_path / "a.png", tmp_path / "a.ico")

    assert command[0].lower().endswith("powershell.exe")
    assert command[1:6] == [
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
    ]
    assert command[6] == str(render.RENDER_SCRIPT)
    assert arguments_of(command) == {
        "-OutputPng": str(tmp_path / "a.png"),
        "-OutputIco": str(tmp_path / "a.ico"),
        "-CodePoint": "87",
        "-DiscColor": "#E0A03F",
        "-GlyphColor": GLYPH_GRAPHITE,
        "-GlyphHeightRatio": "0.5",
        "-GlyphWidthRatio": "0.62",
        "-DiscMargin": "8",
        "-Canvas": "512",
    }


def test_the_image_command_line_carries_the_source_and_the_fit(tmp_path):
    request = ImageRequest(tmp_path / "logo.png", FitRectangle(1, 2, 3, 4), 512)

    command = command_line(request, tmp_path / "a.png", tmp_path / "a.ico")

    assert arguments_of(command) == {
        "-OutputPng": str(tmp_path / "a.png"),
        "-OutputIco": str(tmp_path / "a.ico"),
        "-Source": str(tmp_path / "logo.png"),
        "-FitX": "1",
        "-FitY": "2",
        "-FitWidth": "3",
        "-FitHeight": "4",
        "-Canvas": "512",
    }


def test_the_renderer_script_is_part_of_the_repository():
    assert render.RENDER_SCRIPT.is_file()
    assert (render.RENDER_SCRIPT.parent / "build_launcher_icon.ps1").is_file()


def test_generation_publishes_both_files_and_leaves_no_staging(tmp_path):
    renderer = FakeRenderer()

    assets = generate_brand_assets(tmp_path, WORK, renderer=renderer)

    assert assets.png == tmp_path / "brand" / "brand.png"
    assert assets.ico == tmp_path / "brand" / "brand.ico"
    assert assets.png.read_bytes() == GOOD_PNG
    assert assets.ico.read_bytes() == GOOD_ICO
    assert sorted(entry.name for entry in (tmp_path / "brand").iterdir()) == [
        "brand.ico",
        "brand.png",
    ]
    assert not renderer.staging[0].exists()
    assert renderer.requests == [monogram_style(WORK)]


def test_generation_twice_replaces_the_files_atomically(tmp_path):
    generate_brand_assets(tmp_path, WORK, renderer=FakeRenderer())
    newer = make_png(512, 512, pixel=b"\x01\x02\x03\x04")

    assets = generate_brand_assets(tmp_path, WORK, renderer=FakeRenderer(png=newer))

    assert assets.png.read_bytes() == newer


def test_a_failing_renderer_keeps_the_previous_files_and_removes_staging(tmp_path):
    generate_brand_assets(tmp_path, WORK, renderer=FakeRenderer())
    failing = FakeRenderer(error=BrandIconError("renderer exploded"))

    with pytest.raises(BrandIconError, match="renderer exploded"):
        generate_brand_assets(tmp_path, WORK, renderer=failing)

    assert (tmp_path / "brand" / "brand.png").read_bytes() == GOOD_PNG
    assert (tmp_path / "brand" / "brand.ico").read_bytes() == GOOD_ICO
    assert sorted(entry.name for entry in (tmp_path / "brand").iterdir()) == [
        "brand.ico",
        "brand.png",
    ]


def test_before_publish_runs_after_rendering_and_before_any_file_is_replaced(tmp_path):
    generate_brand_assets(tmp_path, WORK, renderer=FakeRenderer())
    seen = []
    newer = make_png(512, 512, pixel=b"\x01\x02\x03\x04")

    generate_brand_assets(
        tmp_path,
        WORK,
        renderer=FakeRenderer(png=newer),
        before_publish=lambda: seen.append(
            (tmp_path / "brand" / "brand.png").read_bytes()
        ),
    )

    assert seen == [GOOD_PNG]
    assert (tmp_path / "brand" / "brand.png").read_bytes() == newer


def test_a_failing_before_publish_keeps_the_previous_files(tmp_path):
    generate_brand_assets(tmp_path, WORK, renderer=FakeRenderer())

    def refuse():
        raise OSError("no room")

    with pytest.raises(OSError, match="no room"):
        generate_brand_assets(
            tmp_path, WORK, renderer=FakeRenderer(), before_publish=refuse
        )

    assert (tmp_path / "brand" / "brand.png").read_bytes() == GOOD_PNG
    assert sorted(entry.name for entry in (tmp_path / "brand").iterdir()) == [
        "brand.ico",
        "brand.png",
    ]


def test_an_explicit_image_is_rendered_instead_of_the_homes_icon_path(tmp_path):
    chosen = make_png(256, 128)
    (tmp_path / "chosen.png").write_bytes(chosen)
    brand = BrandSettings(name="Work", monogram="W", accent="#E0A03F", icon="icon.png")
    renderer = FakeRenderer()

    generate_brand_assets(
        tmp_path, brand, renderer=renderer, image=tmp_path / "chosen.png"
    )

    assert renderer.requests[0].source == (tmp_path / "chosen.png").resolve()


@pytest.mark.parametrize(
    ("png", "ico", "message"),
    [
        (b"junk", GOOD_ICO, "unusable brand.png: is not a PNG file"),
        (make_png(256, 256), GOOD_ICO, "unusable brand.png: is 256x256"),
        (
            make_png(512, 512, color_type=2),
            GOOD_ICO,
            "unusable brand.png: has no alpha channel",
        ),
        (GOOD_PNG, b"junk", "unusable brand.ico: ICO file is too short"),
        (
            GOOD_PNG,
            make_ico([(16, make_png(16, 16))]),
            "unusable brand.ico: ICO file does not hold the standard",
        ),
    ],
)
def test_unusable_renderer_output_is_never_published(tmp_path, png, ico, message):
    renderer = FakeRenderer(png=png, ico=ico)

    with pytest.raises(BrandIconError, match=message):
        generate_brand_assets(tmp_path, WORK, renderer=renderer)

    assert not (tmp_path / "brand" / "brand.png").exists()
    assert not (tmp_path / "brand" / "brand.ico").exists()
    assert not renderer.staging[0].exists()


def test_an_undecodable_user_image_is_reported_with_the_key_and_value(tmp_path):
    (tmp_path / "logo.png").write_bytes(make_png(100, 100))
    brand = BrandSettings(name="Work", monogram="W", icon="logo.png")
    renderer = FakeRenderer(error=ImageDecodeError("raw"))

    with pytest.raises(BrandIconError) as error:
        generate_brand_assets(tmp_path, brand, renderer=renderer)

    assert str(error.value) == (
        '[brand].icon "logo.png": could not be decoded as an image'
    )


def test_an_invalid_user_icon_is_rejected_before_the_renderer_runs(tmp_path):
    brand = BrandSettings(name="Work", monogram="W", icon="missing.png")
    renderer = FakeRenderer()

    with pytest.raises(BrandIconError, match="file not found"):
        generate_brand_assets(tmp_path, brand, renderer=renderer)

    assert renderer.requests == []


def test_the_default_brand_generates_nothing_and_deletes_nothing(tmp_path):
    generate_brand_assets(tmp_path, WORK, renderer=FakeRenderer())
    renderer = FakeRenderer()

    outcome = regenerate_home_icons(tmp_path, renderer=renderer)

    assert outcome.assets is None
    assert (
        outcome.message
        == DEFAULT_IDENTITY_MESSAGE
        == ("Default identity: nothing to generate")
    )
    assert renderer.requests == []
    assert (tmp_path / "brand" / "brand.ico").read_bytes() == GOOD_ICO


def test_a_home_with_a_brand_section_is_generated_from_its_config(tmp_path):
    write_config(
        tmp_path, '[brand]\nname = "Work"\nmonogram = "w"\naccent = "#e0a03f"\n'
    )
    renderer = FakeRenderer()

    outcome = regenerate_home_icons(tmp_path, renderer=renderer)

    assert outcome.assets is not None
    assert outcome.message == f"Generated brand icons in {tmp_path / 'brand'}"
    assert renderer.requests == [monogram_style(WORK)]


def test_regeneration_is_idempotent(tmp_path):
    write_config(tmp_path, '[brand]\nname = "Work"\n')

    first = regenerate_home_icons(tmp_path, renderer=FakeRenderer())
    second = regenerate_home_icons(tmp_path, renderer=FakeRenderer())

    assert first == second


def test_an_invalid_brand_section_raises_the_config_error_naming_the_key(tmp_path):
    write_config(tmp_path, '[brand]\nmonogram = "AB"\n')

    with pytest.raises(ConfigError, match=r"\[brand\]\.monogram"):
        regenerate_home_icons(tmp_path, renderer=FakeRenderer())


def test_the_cli_reports_success_and_failure_with_exit_codes(tmp_path, capsys):
    write_config(tmp_path, '[brand]\nname = "Work"\nmonogram = "W"\n')
    assert main(["--home", str(tmp_path)], renderer=FakeRenderer()) == 0
    assert "Generated brand icons in" in capsys.readouterr().out

    write_config(tmp_path, '[brand]\nmonogram = "AB"\n')
    assert main(["--home", str(tmp_path)], renderer=FakeRenderer()) == 1
    captured = capsys.readouterr()
    assert "[brand].monogram" in captured.err
    assert captured.out == ""


def test_the_cli_prints_the_default_identity_message(tmp_path, capsys):
    assert main(["--home", str(tmp_path)], renderer=FakeRenderer()) == 0
    assert capsys.readouterr().out.strip() == DEFAULT_IDENTITY_MESSAGE


class FakeRun:
    def __init__(self, returncode=0, stderr="", stdout="", error=None):
        self.result = subprocess.CompletedProcess([], returncode, stdout, stderr)
        self.error = error
        self.calls = []

    def __call__(self, command, **options):
        self.calls.append((command, options))
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def powershell(monkeypatch, tmp_path):
    executable = tmp_path / "powershell.exe"
    executable.write_text("", encoding="utf-8")
    monkeypatch.setattr(render, "_powershell_executable", lambda: str(executable))


def run_renderer(tmp_path, fake):
    request = monogram_style(WORK)
    run_powershell_renderer(request, tmp_path / "a.png", tmp_path / "a.ico", run=fake)


def test_the_renderer_process_has_no_console_no_stdin_and_a_timeout(
    powershell, tmp_path
):
    fake = FakeRun()

    run_renderer(tmp_path, fake)

    (_, options) = fake.calls[0]
    assert options["stdin"] is subprocess.DEVNULL
    assert options["timeout"] == render.RENDER_TIMEOUT_SECONDS
    assert options["capture_output"] is True
    assert options["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)


def test_exit_code_two_means_the_image_could_not_be_decoded(powershell, tmp_path):
    with pytest.raises(ImageDecodeError):
        run_renderer(tmp_path, FakeRun(returncode=2, stderr="bad image"))


def test_another_failure_reports_the_last_line_of_the_renderer_output(
    powershell, tmp_path
):
    fake = FakeRun(returncode=1, stderr="first line\nFont not found\n\n")

    with pytest.raises(BrandIconError) as error:
        run_renderer(tmp_path, fake)

    assert str(error.value) == "The icon renderer failed (exit 1): Font not found"


def test_a_renderer_timeout_is_reported(powershell, tmp_path):
    fake = FakeRun(error=subprocess.TimeoutExpired("powershell", 30))

    with pytest.raises(BrandIconError, match="did not finish within 30 s"):
        run_renderer(tmp_path, fake)


def test_a_renderer_that_cannot_start_is_reported(powershell, tmp_path):
    with pytest.raises(BrandIconError, match="could not be started: denied"):
        run_renderer(tmp_path, FakeRun(error=OSError("denied")))


def test_a_missing_powershell_says_icons_need_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(
        render, "_powershell_executable", lambda: str(tmp_path / "none.exe")
    )

    with pytest.raises(BrandIconError, match="Windows PowerShell was not found"):
        run_renderer(tmp_path, FakeRun())


def test_the_render_module_imports_only_the_standard_library_and_jarvis_core():
    tree = ast.parse(Path(render.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in (node.names if isinstance(node, ast.Import) else [None])
        if not (isinstance(node, ast.ImportFrom) and node.level)
    }
    foreign = {
        name
        for name in imported
        if name.split(".")[0] not in sys.stdlib_module_names
        and not name.startswith("jarvis.core")
    }
    assert not foreign


def test_the_monogram_style_is_a_frozen_value():
    with pytest.raises(AttributeError):
        monogram_style(WORK).disc = "#000000"  # type: ignore[misc]
    assert isinstance(monogram_style(WORK), MonogramStyle)


def test_the_renderer_scripts_ship_in_the_deployment_inventory():
    from tools.deployment_plan import APPLICATION_FILES

    assert Path("tools/generate_brand_icons.ps1") in APPLICATION_FILES
    assert Path("tools/build_launcher_icon.ps1") in APPLICATION_FILES


def test_the_status_console_mark_is_the_circle_the_generated_icon_mirrors():
    stylesheet = (
        Path(render.__file__).resolve().parents[1] / "ui/status_console_ui/style.css"
    ).read_text(encoding="utf-8")

    assert '.brand-mark[data-brand="custom"] { border-radius: 50%; }' in stylesheet


def test_a_relative_home_is_reported_and_published_by_absolute_path(
    tmp_path, monkeypatch, capsys
):
    write_config(tmp_path, '[brand]\nname = "Work"\nmonogram = "W"\n')
    monkeypatch.chdir(tmp_path)

    assert main(["--home", "."], renderer=FakeRenderer()) == 0

    expected = f"Generated brand icons in {(tmp_path / 'brand').resolve()}"
    assert capsys.readouterr().out.strip() == expected
    assert (tmp_path / "brand" / "brand.ico").is_file()
