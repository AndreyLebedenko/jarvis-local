"""Generates `<home>/brand/brand.png` and `brand.ico` from a validated brand.

Every art decision is made here in Python; the PowerShell script only draws.
The renderer is a seam so orchestration runs on any platform; the real one
needs Windows PowerShell 5.1 with System.Drawing.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from jarvis.core.brand import (
    BRAND_ICO_NAME,
    BRAND_PNG_NAME,
    BrandAssets,
    brand_asset_directory,
)
from jarvis.core.brand_icon import (
    MASTER_SIDE,
    BrandIconError,
    FitRectangle,
    check_standard_ico,
    fit_inside_square,
    inspect_png,
    validate_icon_file,
    validate_icon_png,
)
from jarvis.core.config import BrandSettings, ConfigError, load_brand

GLYPH_GRAPHITE = "#0A0D14"
GLYPH_WHITE = "#FFFFFF"
GLYPH_HEIGHT_RATIO = 0.5
GLYPH_WIDTH_RATIO = 0.62
DISC_MARGIN = 8
RENDER_TIMEOUT_SECONDS = 30
DECODE_FAILURE_EXIT_CODE = 2
DEFAULT_IDENTITY_MESSAGE = "Default identity: nothing to generate"
RENDER_SCRIPT = (
    Path(__file__).resolve().parents[3] / "tools" / "generate_brand_icons.ps1"
)


class ImageDecodeError(BrandIconError):
    """The renderer could not decode the user image."""


@dataclass(frozen=True)
class MonogramStyle:
    code_point: int
    disc: str
    glyph: str
    glyph_height_ratio: float = GLYPH_HEIGHT_RATIO
    glyph_width_ratio: float = GLYPH_WIDTH_RATIO
    disc_margin: int = DISC_MARGIN
    canvas: int = MASTER_SIDE


@dataclass(frozen=True)
class ImageRequest:
    source: Path
    fit: FitRectangle
    canvas: int = MASTER_SIDE


RenderRequest = MonogramStyle | ImageRequest
Renderer = Callable[[RenderRequest, Path, Path], None]


@dataclass(frozen=True)
class GenerationOutcome:
    assets: BrandAssets | None
    message: str


def _luminance(colour: str) -> float:
    def linear(channel: int) -> float:
        value = channel / 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (int(colour[index : index + 2], 16) for index in (1, 3, 5))
    return 0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue)


def contrast_ratio(first: str, second: str) -> float:
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def monogram_style(brand: BrandSettings) -> MonogramStyle:
    glyph = max(
        (GLYPH_GRAPHITE, GLYPH_WHITE),
        key=lambda candidate: contrast_ratio(brand.accent, candidate),
    )
    return MonogramStyle(ord(brand.monogram), brand.accent, glyph)


def build_request(
    home: Path, brand: BrandSettings, *, image: Path | None = None
) -> RenderRequest:
    """`image` is a PNG not yet in the home (a rebrand renders it before copying it)."""
    if brand.icon is None:
        return monogram_style(brand)
    icon = (
        validate_icon_file(image)
        if image is not None
        else validate_icon_png(home, brand.icon)
    )
    return ImageRequest(
        icon.path, fit_inside_square(icon.info.width, icon.info.height, MASTER_SIDE)
    )


def _powershell_executable() -> str:
    root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    return str(
        PureWindowsPath(root)
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )


def _script_arguments(request: RenderRequest) -> list[str]:
    if isinstance(request, MonogramStyle):
        pairs = {
            "-CodePoint": request.code_point,
            "-DiscColor": request.disc,
            "-GlyphColor": request.glyph,
            "-GlyphHeightRatio": format(request.glyph_height_ratio, "g"),
            "-GlyphWidthRatio": format(request.glyph_width_ratio, "g"),
            "-DiscMargin": request.disc_margin,
            "-Canvas": request.canvas,
        }
    else:
        pairs = {
            "-Source": request.source,
            "-FitX": request.fit.x,
            "-FitY": request.fit.y,
            "-FitWidth": request.fit.width,
            "-FitHeight": request.fit.height,
            "-Canvas": request.canvas,
        }
    return [part for name, value in pairs.items() for part in (name, str(value))]


def command_line(
    request: RenderRequest, output_png: Path, output_ico: Path
) -> list[str]:
    return [
        _powershell_executable(),
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(RENDER_SCRIPT),
        "-OutputPng",
        str(output_png),
        "-OutputIco",
        str(output_ico),
        *_script_arguments(request),
    ]


def _last_line(*texts: str) -> str:
    for text in texts:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            return lines[-1]
    return "no output"


def run_powershell_renderer(
    request: RenderRequest,
    output_png: Path,
    output_ico: Path,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    command = command_line(request, output_png, output_ico)
    if not Path(command[0]).is_file():
        raise BrandIconError(
            f"Windows PowerShell was not found at {command[0]}; "
            "icons can only be generated on Windows"
        )
    if not RENDER_SCRIPT.is_file():
        raise BrandIconError(f"The icon renderer script is missing: {RENDER_SCRIPT}")
    try:
        result = run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=RENDER_TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        raise BrandIconError(
            f"The icon renderer did not finish within {RENDER_TIMEOUT_SECONDS} s"
        ) from None
    except OSError as error:
        raise BrandIconError(
            f"The icon renderer could not be started: {error}"
        ) from None
    if result.returncode == DECODE_FAILURE_EXIT_CODE:
        raise ImageDecodeError(_last_line(result.stderr, result.stdout))
    if result.returncode != 0:
        raise BrandIconError(
            f"The icon renderer failed (exit {result.returncode}): "
            f"{_last_line(result.stderr, result.stdout)}"
        )


def _verify_output(png: Path, ico: Path) -> None:
    try:
        info = inspect_png(png.read_bytes())
    except (OSError, BrandIconError) as error:
        raise BrandIconError(
            f"The icon renderer produced an unusable brand.png: {error}"
        ) from None
    if (info.width, info.height) != (MASTER_SIDE, MASTER_SIDE):
        raise BrandIconError(
            f"The icon renderer produced an unusable brand.png: is "
            f"{info.width}x{info.height} but must be {MASTER_SIDE}x{MASTER_SIDE}"
        )
    if not info.has_alpha:
        raise BrandIconError(
            "The icon renderer produced an unusable brand.png: has no alpha channel"
        )
    try:
        check_standard_ico(ico.read_bytes())
    except (OSError, BrandIconError) as error:
        raise BrandIconError(
            f"The icon renderer produced an unusable brand.ico: {error}"
        ) from None


def _render_to(
    request: RenderRequest, brand: BrandSettings, renderer: Renderer, staging: Path
) -> tuple[Path, Path]:
    png, ico = staging / BRAND_PNG_NAME, staging / BRAND_ICO_NAME
    try:
        renderer(request, png, ico)
    except ImageDecodeError:
        raise BrandIconError(
            f'[brand].icon "{brand.icon}": could not be decoded as an image'
        ) from None
    _verify_output(png, ico)
    return png, ico


def generate_brand_assets(
    home: Path,
    brand: BrandSettings,
    *,
    renderer: Renderer = run_powershell_renderer,
    image: Path | None = None,
    before_publish: Callable[[], None] | None = None,
) -> BrandAssets:
    """Renders into a staging directory, verifies, then replaces each published
    file atomically: a failure before publishing leaves the old files alone.
    `before_publish` runs once the staged files are verified and before the first
    replacement, so a caller can write what the icons belong to."""
    home = home.resolve()
    request = build_request(home, brand, image=image)
    directory = brand_asset_directory(home)
    directory.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".render-", dir=directory))
    try:
        png, ico = _render_to(request, brand, renderer, staging)
        if before_publish is not None:
            before_publish()
        published = BrandAssets(directory / BRAND_PNG_NAME, directory / BRAND_ICO_NAME)
        os.replace(png, published.png)
        os.replace(ico, published.ico)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return published


def regenerate_home_icons(
    home: Path, *, renderer: Renderer = run_powershell_renderer
) -> GenerationOutcome:
    """The one entry point for the CLI, the launcher button and deployment."""
    brand = load_brand(home / "config.toml")
    if brand == BrandSettings():
        return GenerationOutcome(None, DEFAULT_IDENTITY_MESSAGE)
    assets = generate_brand_assets(home, brand, renderer=renderer)
    return GenerationOutcome(assets, f"Generated brand icons in {assets.png.parent}")


def main(
    argv: list[str] | None = None, *, renderer: Renderer = run_powershell_renderer
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m jarvis.core.brand_render",
        description="Generate brand.png and brand.ico from the [brand] section "
        "of <home>/config.toml.",
    )
    parser.add_argument("--home", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        outcome = regenerate_home_icons(arguments.home, renderer=renderer)
    except (ConfigError, BrandIconError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    print(outcome.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
