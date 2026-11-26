"""Real System.Drawing renders; skipped where Windows PowerShell is absent."""

import os
import zlib
from pathlib import Path

import pytest
from png_fixtures import PNG_SIGNATURE, chunk, ihdr
from png_pixels import pixel, read_rgba

from jarvis.core import brand_render
from jarvis.core.brand_icon import (
    ICO_FRAME_SIZES,
    FitRectangle,
    check_standard_ico,
)
from jarvis.core.brand_render import generate_brand_assets
from jarvis.core.config import BrandSettings

pytestmark = pytest.mark.skipif(
    os.name != "nt" or not Path(brand_render._powershell_executable()).is_file(),
    reason="needs Windows PowerShell with System.Drawing",
)

ACCENT = (0xE0, 0xA0, 0x3F, 255)
GRAPHITE = (0x0A, 0x0D, 0x14, 255)


def solid_png(width, height, rgba, *, transparent_columns=0) -> bytes:
    """A real RGBA8 PNG; the first columns are fully transparent."""
    row = (
        b"\x00"
        + (bytes((0, 0, 0, 0)) * transparent_columns)
        + bytes(rgba) * (width - transparent_columns)
    )
    header = ihdr(width, height)
    return (
        PNG_SIGNATURE
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND")
    )


def render(tmp_path, brand):
    assets = generate_brand_assets(tmp_path, brand)
    rows = read_rgba(assets.png.read_bytes())
    return assets, rows


@pytest.mark.parametrize("monogram", ["W", "Ж", "7"])
def test_a_monogram_is_a_transparent_cornered_accent_disc_with_the_letter(
    tmp_path, monogram
):
    brand = BrandSettings(name="Work", monogram=monogram, accent="#E0A03F")

    assets, (width, height, rows) = render(tmp_path, brand)

    assert (width, height) == (512, 512)
    assert pixel(rows, 0, 0)[3] == 0
    assert pixel(rows, 511, 511)[3] == 0
    assert pixel(rows, 60, 256) == ACCENT
    assert pixel(rows, 256, 440) == ACCENT
    glyph_pixels = sum(
        1
        for row in rows[128:384]
        for x in range(128, 384)
        if tuple(row[x * 4 : x * 4 + 4]) == GRAPHITE
    )
    assert glyph_pixels > 2000
    assert len(check_standard_ico(assets.ico.read_bytes())) == len(ICO_FRAME_SIZES)


def test_a_dark_accent_gets_a_white_letter(tmp_path):
    brand = BrandSettings(name="Night", monogram="N", accent="#0000FF")

    _, (_, _, rows) = render(tmp_path, brand)

    assert pixel(rows, 60, 256) == (0, 0, 255, 255)
    assert any(
        tuple(rows[y][x * 4 : x * 4 + 4]) == (255, 255, 255, 255)
        for y in range(128, 384)
        for x in range(128, 384)
    )


def test_the_default_icon_frames_are_not_touched_by_a_render(tmp_path):
    before = (
        brand_render.RENDER_SCRIPT.parent.parent
        / "src/jarvis/launcher/assets/jarvis.ico"
    ).read_bytes()

    render(tmp_path, BrandSettings(name="Work", monogram="W"))

    after = (
        brand_render.RENDER_SCRIPT.parent.parent
        / "src/jarvis/launcher/assets/jarvis.ico"
    ).read_bytes()
    assert before == after


def test_a_non_square_transparent_user_png_is_centred_and_undistorted(tmp_path):
    (tmp_path / "logo.png").write_bytes(
        solid_png(200, 100, (200, 30, 30, 255), transparent_columns=20)
    )
    brand = BrandSettings(name="Work", monogram="W", icon="logo.png")

    assets, (width, height, rows) = render(tmp_path, brand)

    assert (width, height) == (512, 512)
    assert pixel(rows, 256, 5)[3] == 0
    assert pixel(rows, 256, 506)[3] == 0
    assert pixel(rows, 300, 256) == (200, 30, 30, 255)
    assert pixel(rows, 10, 256)[3] == 0
    assert pixel(rows, 500, 256) == (200, 30, 30, 255)
    check_standard_ico(assets.ico.read_bytes())


def test_a_square_user_png_fills_the_whole_canvas(tmp_path):
    (tmp_path / "logo.png").write_bytes(solid_png(100, 100, (10, 200, 10, 255)))
    brand = BrandSettings(name="Work", monogram="W", icon="logo.png")

    _, (_, _, rows) = render(tmp_path, brand)

    assert pixel(rows, 2, 2) == (10, 200, 10, 255)
    assert pixel(rows, 509, 509) == (10, 200, 10, 255)


def test_a_non_ascii_path_in_a_renderer_message_reaches_python_intact(tmp_path):
    missing = tmp_path / "Работа" / "logo.png"
    request = brand_render.ImageRequest(missing, FitRectangle(0, 0, 512, 512))

    with pytest.raises(brand_render.ImageDecodeError) as error:
        brand_render.run_powershell_renderer(
            request, tmp_path / "a.png", tmp_path / "a.ico"
        )

    assert "Работа" in str(error.value)
