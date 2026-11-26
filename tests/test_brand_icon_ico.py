import struct
from pathlib import Path

import pytest
from png_fixtures import make_ico, make_png

from jarvis.core.brand import PACKAGE_ASSETS
from jarvis.core.brand_icon import (
    ICO_FRAME_SIZES,
    BrandIconError,
    check_standard_ico,
    read_ico_frames,
)


def standard_ico() -> bytes:
    return make_ico([(side, make_png(side, side)) for side in ICO_FRAME_SIZES])


def test_the_shipped_default_icon_is_a_valid_standard_icon():
    data = (PACKAGE_ASSETS / "jarvis.ico").read_bytes()

    frames = check_standard_ico(data)

    assert [frame.width for frame in frames] == list(ICO_FRAME_SIZES)


def test_a_generated_style_icon_reads_back_every_frame():
    frames = read_ico_frames(standard_ico())

    assert [(frame.width, frame.height) for frame in frames] == [
        (side, side) for side in ICO_FRAME_SIZES
    ]
    assert all(frame.is_png for frame in frames)


def test_a_dib_frame_is_bounds_checked_but_accepted():
    dib = struct.pack("<I", 40) + bytes(60)

    frames = read_ico_frames(make_ico([(32, dib)]))

    assert not frames[0].is_png


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "too short"),
        (struct.pack("<HHH", 0, 2, 1) + bytes(16), "bad header"),
        (struct.pack("<HHH", 1, 1, 1) + bytes(16), "bad header"),
        (struct.pack("<HHH", 0, 1, 0), "no frames"),
        (struct.pack("<HHH", 0, 1, 3) + bytes(16), "directory is cut short"),
    ],
)
def test_a_broken_container_is_rejected(data, message):
    with pytest.raises(BrandIconError, match=message):
        read_ico_frames(data)


def test_a_frame_beyond_the_end_of_the_file_is_rejected():
    data = bytearray(make_ico([(16, make_png(16, 16))]))
    data[-1:] = b""

    with pytest.raises(BrandIconError, match="frame 0 lies outside the file"):
        read_ico_frames(bytes(data))


def test_a_png_frame_that_disagrees_with_its_directory_entry_is_rejected():
    with pytest.raises(
        BrandIconError, match="is 32x32 but its directory entry says 16"
    ):
        read_ico_frames(make_ico([(16, make_png(32, 32))]))


def test_a_corrupt_png_frame_is_rejected():
    with pytest.raises(BrandIconError, match="frame 0 is truncated or corrupt"):
        read_ico_frames(make_ico([(16, make_png(16, 16)[:-20])]))


def test_a_classic_icon_with_other_sizes_is_valid_but_not_standard():
    data = make_ico([(16, make_png(16, 16)), (32, make_png(32, 32))])

    read_ico_frames(data)
    with pytest.raises(BrandIconError, match="standard square PNG frames"):
        check_standard_ico(data)


def test_a_standard_icon_missing_one_size_is_rejected():
    frames = [(side, make_png(side, side)) for side in ICO_FRAME_SIZES[:-1]]

    with pytest.raises(BrandIconError, match="standard square PNG frames"):
        check_standard_ico(make_ico(frames))


def test_the_package_asset_directory_exists_for_the_default_icon():
    assert Path(PACKAGE_ASSETS / "jarvis.ico").is_file()
