import struct
from pathlib import Path


def test_desktop_and_tray_icon_contains_valid_alpha_png_frames_at_windows_sizes():
    icon = (
        Path(__file__).resolve().parents[1] / "src/jarvis/launcher/assets/jarvis.ico"
    ).read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", icon)
    assert (reserved, kind) == (0, 1)
    dimensions = set()
    for index in range(count):
        width, height, _, _, planes, depth, length, offset = struct.unpack_from(
            "<BBBBHHII", icon, 6 + index * 16
        )
        frame = icon[offset : offset + length]
        assert frame.startswith(b"\x89PNG\r\n\x1a\n")
        assert (planes, depth) == (1, 32)
        size = struct.unpack_from(">II", frame, 16)
        assert size == (width or 256, height or 256)
        assert frame[25] == 6  # RGBA, preserving transparency around the tile.
        dimensions.add(size[0])
    assert {16, 20, 24, 32, 40, 48, 64, 128, 256} <= dimensions
