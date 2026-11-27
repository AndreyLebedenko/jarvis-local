"""The native preview against the real icon renderer (offscreen, no window)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

import pytest
from png_pixels import pixel, read_rgba
from wizard_ps_support import json_lines, run_snippet

from jarvis.core import brand_render
from jarvis.core.brand_render import generate_brand_assets, monogram_style
from jarvis.core.config import BrandSettings

windows = pytest.mark.skipif(
    os.name != "nt" or not Path(brand_render._powershell_executable()).is_file(),
    reason="needs Windows PowerShell with WPF and System.Drawing",
)
ASSEMBLIES = (
    "Add-Type -AssemblyName PresentationCore, PresentationFramework, WindowsBase\n"
)
SAVE_PNG = r"""
function Save-DrawingPng($Image, [string]$Path, [int]$Side) {
    $visual = New-Object Windows.Media.DrawingVisual
    $context = $visual.RenderOpen()
    $context.DrawImage($Image, (New-Object Windows.Rect 0, 0, $Side, $Side))
    $context.Close()
    $format = [Windows.Media.PixelFormats]::Pbgra32
    $target = New-Object Windows.Media.Imaging.RenderTargetBitmap `
        $Side, $Side, 96, 96, $format
    $target.Render($visual)
    $encoder = New-Object Windows.Media.Imaging.PngBitmapEncoder
    $encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($target))
    $stream = [IO.File]::Create($Path)
    try { $encoder.Save($stream) } finally { $stream.Dispose() }
}
"""


def glyph_box(
    rows: list[bytes], glyph: tuple[int, int, int]
) -> tuple[int, int, int, int, int]:
    """Bounding box and pixel count of the pixels that are closer to the glyph
    colour than to anything else in the disc (anti-aliased edges included)."""
    xs, ys, count = [], [], 0
    for y, row in enumerate(rows):
        for x in range(len(row) // 4):
            red, green, blue, alpha = row[x * 4 : x * 4 + 4]
            if alpha == 255 and (
                abs(red - glyph[0]) + abs(green - glyph[1]) + abs(blue - glyph[2]) < 120
            ):
                xs.append(x)
                ys.append(y)
                count += 1
    return min(xs), min(ys), max(xs), max(ys), count


def wpf_render(tmp_path: Path, art: dict) -> list[bytes]:
    output = tmp_path / "wpf.png"
    body = (
        ASSEMBLIES
        + SAVE_PNG
        + "$art = $env:ART | ConvertFrom-Json\n"
        + "Save-DrawingPng (New-MonogramDrawing $art) $env:OUT 512\n"
    )
    result = run_snippet(
        tmp_path,
        body,
        "wizard_preview.ps1",
        env={"ART": json.dumps(art), "OUT": str(output)},
        sta=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return read_rgba(output.read_bytes())[2]


@windows
@pytest.mark.parametrize(
    ("monogram", "accent"),
    [("W", "#E0A03F"), ("Ж", "#3FE0D0"), ("7", "#2060E0"), ("J", "#102030")],
)
def test_the_native_drawing_matches_the_generated_icon(
    tmp_path: Path, monogram: str, accent: str
) -> None:
    brand = BrandSettings(name="Work", monogram=monogram, accent=accent)
    style = monogram_style(brand)
    generated = generate_brand_assets(tmp_path / "home", brand)
    real = read_rgba(generated.png.read_bytes())[2]

    drawn = wpf_render(tmp_path, asdict(style))

    disc = tuple(int(accent[i : i + 2], 16) for i in (1, 3, 5))
    for rows in (real, drawn):
        assert pixel(rows, 0, 0)[3] == 0 and pixel(rows, 511, 511)[3] == 0
        assert pixel(rows, 60, 256)[:3] == disc
        assert pixel(rows, 256, 440)[:3] == disc
    glyph = tuple(int(style.glyph[i : i + 2], 16) for i in (1, 3, 5))
    real_box, drawn_box = glyph_box(real, glyph), glyph_box(drawn, glyph)
    for real_edge, drawn_edge in zip(real_box[:4], drawn_box[:4], strict=True):
        assert abs(real_edge - drawn_edge) <= 2, (real_box, drawn_box)
    assert abs(real_box[4] - drawn_box[4]) <= 0.06 * real_box[4], (real_box, drawn_box)


@windows
def test_the_layout_fits_the_tighter_of_the_two_limits_and_centres_the_glyph(
    tmp_path: Path,
) -> None:
    body = r"""
$art = [pscustomobject]@{
    canvas = 512; disc_margin = 8; glyph_height_ratio = 0.5; glyph_width_ratio = 0.62
}
$tall = Get-MonogramLayout $art 2 3 60 70
$wide = Get-MonogramLayout $art 0 0 200 50
@($tall, $wide) | ConvertTo-Json -Compress
"""
    result = run_snippet(tmp_path, body, "wizard_preview.ps1")

    (layouts,) = json_lines(result)
    tall, wide = layouts
    assert (tall["DiscX"], tall["Diameter"]) == (8, 496)
    assert tall["Scale"] == pytest.approx(0.5 * 496 / 70)
    assert (tall["ShiftX"], tall["ShiftY"]) == (-32, -38)
    assert (tall["CenterX"], tall["CenterY"]) == (256, 256)
    assert wide["Scale"] == pytest.approx(0.62 * 496 / 200)


@windows
def test_a_file_preview_is_the_scaled_image_and_failures_give_nothing(
    tmp_path: Path,
) -> None:
    from png_fixtures import make_png

    picture = tmp_path / "logo.png"
    picture.write_bytes(make_png(256, 128))
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    body = (
        ASSEMBLIES
        + r"""
$image = New-FilePreview $env:GOOD 64
$missing = New-FilePreview $env:BROKEN 64
$none = New-IdentityPreviewImage ([pscustomobject]@{ Kind = 'none' })
[ordered]@{
    width = $image.PixelWidth; broken = ($null -eq $missing); none = ($null -eq $none)
} | ConvertTo-Json -Compress
"""
    )
    result = run_snippet(
        tmp_path,
        body,
        "wizard_preview.ps1",
        env={"GOOD": str(picture), "BROKEN": str(broken)},
        sta=True,
    )

    assert json_lines(result) == [{"width": 64, "broken": True, "none": True}]
