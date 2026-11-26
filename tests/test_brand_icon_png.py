import os
import struct
import subprocess
import zlib
from pathlib import Path

import pytest
from conftest import assert_stdlib_only_imports
from png_fixtures import PNG_SIGNATURE, chunk, ihdr, make_png

from jarvis.core.brand_icon import (
    MASTER_SIDE,
    BrandIconError,
    FitRectangle,
    fit_inside_square,
    inspect_png,
    validate_icon_file,
    validate_icon_png,
)

KEY = '[brand].icon "logo.png": '


def write_icon(home, data, name="logo.png"):
    path = home / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def rejection(home, value="logo.png") -> str:
    with pytest.raises(BrandIconError) as error:
        validate_icon_png(home, value)
    return str(error.value)


def test_a_valid_square_png_is_accepted_and_described(tmp_path):
    write_icon(tmp_path, make_png(256, 256))

    icon = validate_icon_png(tmp_path, "logo.png")

    assert icon.path == (tmp_path / "logo.png").resolve()
    assert (icon.info.width, icon.info.height) == (256, 256)
    assert icon.info.has_alpha


@pytest.mark.parametrize(
    ("color_type", "bit_depth", "transparency", "expected_alpha"),
    [
        (6, 8, False, True),
        (4, 8, False, True),
        (2, 8, True, True),
        (2, 8, False, False),
    ],
)
def test_transparency_is_accepted_in_every_png_form(
    tmp_path, color_type, bit_depth, transparency, expected_alpha
):
    write_icon(
        tmp_path,
        make_png(
            100,
            100,
            color_type=color_type,
            bit_depth=bit_depth,
            transparency=transparency,
        ),
    )

    assert validate_icon_png(tmp_path, "logo.png").info.has_alpha is expected_alpha


@pytest.mark.parametrize(
    ("color_type", "bit_depth"), [(0, 1), (0, 16), (2, 16), (3, 4), (4, 16), (6, 16)]
)
def test_every_legal_colour_type_and_bit_depth_pair_is_accepted(
    tmp_path, color_type, bit_depth
):
    write_icon(tmp_path, make_png(80, 80, color_type=color_type, bit_depth=bit_depth))

    validate_icon_png(tmp_path, "logo.png")


def test_an_interlaced_png_is_accepted(tmp_path):
    write_icon(tmp_path, make_png(80, 80, interlace=1))

    validate_icon_png(tmp_path, "logo.png")


@pytest.mark.parametrize(
    ("width", "height", "message"),
    [
        (63, 100, "is 63x100; the shorter side must be at least 64 px"),
        (100, 63, "is 100x63; the shorter side must be at least 64 px"),
        (2049, 2049, "is 2049x2049; the longer side must be at most 2048 px"),
        (
            64,
            129,
            "is 64x129; it must be at most twice as wide as high (or the reverse)",
        ),
        (
            129,
            64,
            "is 129x64; it must be at most twice as wide as high (or the reverse)",
        ),
    ],
)
def test_size_and_aspect_limits_are_rejected_with_the_dimensions(
    tmp_path, width, height, message
):
    write_icon(tmp_path, make_png(width, height))

    assert rejection(tmp_path) == KEY + message


@pytest.mark.parametrize(
    ("width", "height"), [(64, 64), (2048, 2048), (64, 128), (128, 64)]
)
def test_limits_are_inclusive(tmp_path, width, height):
    write_icon(tmp_path, make_png(width, height))

    validate_icon_png(tmp_path, "logo.png")


def test_a_huge_declared_size_is_rejected_from_the_header_alone(tmp_path):
    data = (
        PNG_SIGNATURE
        + chunk(b"IHDR", ihdr(100_000, 100_000))
        + chunk(b"IDAT", b"x")
        + chunk(b"IEND")
    )
    write_icon(tmp_path, data)

    assert "the longer side must be at most 2048 px" in rejection(tmp_path)


def test_a_file_over_the_size_cap_is_rejected_before_it_is_read(tmp_path):
    path = write_icon(tmp_path, make_png(64, 64))
    with path.open("r+b") as stream:
        stream.truncate(8 * 1024 * 1024 + 1)

    assert rejection(tmp_path) == KEY + "is 8.0 MiB; the limit is 8 MiB"


def test_a_file_exactly_at_the_size_cap_is_not_rejected_for_its_size(tmp_path):
    path = write_icon(tmp_path, make_png(64, 64))
    with path.open("r+b") as stream:
        stream.truncate(8 * 1024 * 1024)

    assert "MiB" not in rejection(tmp_path)


def test_an_empty_file_is_rejected(tmp_path):
    write_icon(tmp_path, b"")

    assert rejection(tmp_path) == KEY + "is empty"


def test_a_missing_file_names_where_it_was_looked_for(tmp_path):
    expected = KEY + f"file not found: {(tmp_path / 'logo.png').resolve()}"

    assert rejection(tmp_path) == expected


def test_a_directory_is_not_an_icon(tmp_path):
    (tmp_path / "logo.png").mkdir()

    assert rejection(tmp_path) == KEY + "is not a file"


def test_a_path_resolving_outside_the_home_is_rejected(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / "outside.png").write_bytes(make_png(64, 64))

    assert rejection(home, "sub/../../outside.png") == (
        '[brand].icon "sub/../../outside.png": resolves outside the app home'
    )


def test_a_text_file_renamed_to_png_is_rejected_by_its_signature(tmp_path):
    write_icon(tmp_path, b"not an image at all, just text\n" * 10)

    assert rejection(tmp_path) == KEY + "is not a PNG file (bad signature)"


def test_a_jpeg_renamed_to_png_is_rejected_by_its_signature(tmp_path):
    write_icon(tmp_path, b"\xff\xd8\xff\xe0" + bytes(200))

    assert "bad signature" in rejection(tmp_path)


def test_a_signature_without_a_header_chunk_is_rejected(tmp_path):
    write_icon(tmp_path, PNG_SIGNATURE + chunk(b"IDAT", b"x") + chunk(b"IEND"))

    assert rejection(tmp_path) == KEY + "has no valid PNG header (IHDR)"


def test_a_header_with_a_wrong_checksum_is_rejected(tmp_path):
    data = (
        PNG_SIGNATURE
        + chunk(b"IHDR", ihdr(100, 100), crc=1)
        + chunk(b"IDAT", b"x")
        + chunk(b"IEND")
    )
    write_icon(tmp_path, data)

    assert rejection(tmp_path) == KEY + "has no valid PNG header (IHDR)"


@pytest.mark.parametrize(
    ("fields", "detail"),
    [
        ({"color_type": 6, "bit_depth": 4}, "colour type 6, bit depth 4"),
        ({"color_type": 5}, "colour type 5, bit depth 8"),
        ({"compression": 1}, "compression method 1"),
        ({"filter_method": 1}, "filter method 1"),
        ({"interlace": 2}, "interlace method 2"),
    ],
)
def test_an_illegal_header_field_is_rejected_with_the_detail(tmp_path, fields, detail):
    data = (
        PNG_SIGNATURE
        + chunk(b"IHDR", ihdr(100, 100, **fields))
        + chunk(b"IDAT", b"x")
        + chunk(b"IEND")
    )
    write_icon(tmp_path, data)

    assert rejection(tmp_path) == KEY + f"has an unsupported PNG header: {detail}"


def test_a_zero_dimension_is_rejected(tmp_path):
    data = (
        PNG_SIGNATURE
        + chunk(b"IHDR", ihdr(0, 100))
        + chunk(b"IDAT", b"x")
        + chunk(b"IEND")
    )
    write_icon(tmp_path, data)

    assert "unsupported PNG header: size 0x100" in rejection(tmp_path)


def test_a_truncated_file_is_rejected(tmp_path):
    write_icon(tmp_path, make_png(100, 100)[:-30])

    assert rejection(tmp_path).startswith(KEY + "is truncated or corrupt (")


def test_a_file_cut_before_the_end_chunk_is_rejected(tmp_path):
    write_icon(tmp_path, make_png(100, 100)[:-12])

    assert rejection(tmp_path) == KEY + "is truncated or corrupt (IEND chunk missing)"


def test_data_after_the_end_chunk_is_rejected(tmp_path):
    write_icon(tmp_path, make_png(100, 100) + b"trailing")

    assert rejection(tmp_path) == KEY + "is truncated or corrupt (data after IEND)"


def test_a_corrupt_data_chunk_checksum_is_rejected(tmp_path):
    good = make_png(100, 100)
    marker = good.index(b"IDAT")
    corrupt = good[: marker + 4] + b"\xff" + good[marker + 5 :]
    write_icon(tmp_path, corrupt)

    assert (
        rejection(tmp_path) == KEY + "is truncated or corrupt (bad CRC in IDAT chunk)"
    )


def test_a_png_without_image_data_is_rejected(tmp_path):
    data = PNG_SIGNATURE + chunk(b"IHDR", ihdr(100, 100)) + chunk(b"IEND")
    write_icon(tmp_path, data)

    assert rejection(tmp_path) == KEY + "is truncated or corrupt (IDAT chunk missing)"


def test_a_palette_png_without_a_palette_is_rejected(tmp_path):
    data = (
        PNG_SIGNATURE
        + chunk(b"IHDR", ihdr(100, 100, color_type=3))
        + chunk(b"IDAT", b"x")
        + chunk(b"IEND")
    )
    write_icon(tmp_path, data)

    assert rejection(tmp_path) == KEY + "is truncated or corrupt (PLTE chunk missing)"


def test_a_chunk_longer_than_the_file_is_rejected(tmp_path):
    data = make_png(100, 100)[:33] + struct.pack(">I", 2**30) + b"IDAT" + b"x" * 8
    write_icon(tmp_path, data)

    assert "IDAT chunk is cut short" in rejection(tmp_path)


def test_a_hostile_value_is_quoted_not_interpreted(tmp_path):
    message = rejection(tmp_path, 'a"b%s{x}.png')

    assert message.startswith('[brand].icon "a"b%s{x}.png": ')


def test_inspect_png_reports_the_header_of_valid_bytes():
    info = inspect_png(make_png(300, 200, color_type=2))

    assert (info.width, info.height, info.color_type, info.bit_depth) == (
        300,
        200,
        2,
        8,
    )
    assert not info.has_alpha


def test_inspect_png_errors_carry_no_key_prefix():
    with pytest.raises(BrandIconError) as error:
        inspect_png(b"nope")

    assert str(error.value) == "is not a PNG file (bad signature)"


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (512, 512, FitRectangle(0, 0, 512, 512)),
        (100, 100, FitRectangle(0, 0, 512, 512)),
        (200, 100, FitRectangle(0, 128, 512, 256)),
        (100, 200, FitRectangle(128, 0, 256, 512)),
        (100, 60, FitRectangle(0, 102, 512, 307)),
        (2048, 1024, FitRectangle(0, 128, 512, 256)),
        (3, 1, FitRectangle(0, 170, 512, 171)),
    ],
)
def test_a_non_square_image_is_fitted_and_centred_without_distortion(
    width, height, expected
):
    assert fit_inside_square(width, height, MASTER_SIDE) == expected


def test_fitted_rectangles_stay_inside_the_canvas_for_every_allowed_shape():
    for width in range(64, 2049, 97):
        for height in range(max(64, width // 2), min(2048, width * 2) + 1, 89):
            fit = fit_inside_square(width, height, MASTER_SIDE)
            assert fit.x >= 0
            assert fit.y >= 0
            assert fit.x + fit.width <= MASTER_SIDE
            assert fit.y + fit.height <= MASTER_SIDE
            assert max(fit.width, fit.height) == MASTER_SIDE


def test_the_icon_validation_module_is_stdlib_only():
    assert_stdlib_only_imports("src/jarvis/core/brand_icon.py")


def png_with_data(width, height, image_data, **fields):
    return (
        PNG_SIGNATURE
        + chunk(b"IHDR", ihdr(width, height, **fields))
        + chunk(b"IDAT", image_data)
        + chunk(b"IEND")
    )


DOES_NOT_DECODE = "is truncated or corrupt (image data does not decode)"


@pytest.mark.parametrize(
    "image_data",
    [
        b"this is not zlib data",
        zlib.compress(bytes(100 * (1 + 400)))[:-8],
        zlib.compress(bytes(100 * (1 + 400) - 1)),
        zlib.compress(bytes(100 * (1 + 400) + 1)),
        zlib.compress(bytes(50 * 1024 * 1024)),
    ],
    ids=["garbage", "cut-short", "one-byte-short", "one-byte-long", "bomb"],
)
def test_image_data_that_does_not_decode_to_the_declared_size_is_rejected(
    tmp_path, image_data
):
    write_icon(tmp_path, png_with_data(100, 100, image_data))

    assert rejection(tmp_path) == KEY + DOES_NOT_DECODE


def test_a_declared_size_beyond_any_sane_decode_is_rejected_without_decoding():
    data = png_with_data(100_000, 100_000, zlib.compress(bytes(100)))

    with pytest.raises(BrandIconError, match="image data does not decode"):
        inspect_png(data)


def test_the_size_limit_is_reported_before_the_image_data_is_checked(tmp_path):
    write_icon(tmp_path, png_with_data(63, 100, b"garbage"))

    assert "the shorter side must be at least 64 px" in rejection(tmp_path)


def test_the_chunk_structure_is_checked_before_the_size_limits(tmp_path):
    write_icon(tmp_path, make_png(32, 32)[:-30])

    assert rejection(tmp_path).startswith(KEY + "is truncated or corrupt (")


@pytest.mark.skipif(os.name != "nt", reason="directory junctions are Windows-only")
def test_a_junction_inside_the_home_pointing_outside_is_rejected(tmp_path):
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    home.mkdir()
    outside.mkdir()
    (outside / "logo.png").write_bytes(make_png(64, 64))
    junction = home / "link"
    subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
        check=True,
        capture_output=True,
    )
    try:
        message = rejection(home, "link/logo.png")
    finally:
        os.rmdir(junction)

    assert message == '[brand].icon "link/logo.png": resolves outside the app home'
    assert (outside / "logo.png").is_file()


@pytest.mark.parametrize("operation", ["exists", "stat", "read_bytes"])
def test_a_file_system_failure_is_a_prefixed_icon_error_not_a_raw_oserror(
    tmp_path, monkeypatch, operation
):
    write_icon(tmp_path, make_png(64, 64))
    denied = PermissionError(13, "Access is denied")

    def fail(self, *args, **kwargs):
        raise denied

    monkeypatch.setattr(Path, operation, fail)

    assert rejection(tmp_path) == KEY + "cannot be read: Access is denied"


def test_a_file_anywhere_on_disk_is_validated_without_a_home(tmp_path):
    path = write_icon(tmp_path / "pictures", make_png(256, 128), "wide.png")

    icon = validate_icon_file(path)

    assert icon.path == path.resolve()
    assert (icon.info.width, icon.info.height) == (256, 128)


@pytest.mark.parametrize(
    ("data", "problem"),
    [
        (b"", "is empty"),
        (b"this is text", "is not a PNG file (bad signature)"),
        (make_png(32, 32), "is 32x32; the shorter side must be at least 64 px"),
        (
            make_png(500, 100),
            "is 500x100; it must be at most twice as wide as high (or the reverse)",
        ),
    ],
)
def test_an_outside_file_gets_the_same_messages_naming_the_given_path(
    tmp_path, data, problem
):
    path = write_icon(tmp_path, data, "any.png")

    with pytest.raises(BrandIconError) as error:
        validate_icon_file(path)

    assert str(error.value) == f'[brand].icon "{path}": {problem}'


def test_a_missing_outside_file_names_where_it_was_looked_for(tmp_path):
    path = tmp_path / "absent.png"

    with pytest.raises(BrandIconError) as error:
        validate_icon_file(path)

    assert str(error.value) == (
        f'[brand].icon "{path}": file not found: {path.resolve()}'
    )


def test_an_outside_file_may_be_reached_through_a_link_to_elsewhere(tmp_path):
    real = write_icon(tmp_path / "real", make_png(64, 64), "icon.png")
    link = tmp_path / "link.png"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("symbolic links are not permitted here")

    assert validate_icon_file(link).path == real.resolve()
