"""Brand icon source validation, dimension math and ICO verification.

Pure logic over bytes and paths (stdlib only): a user PNG is checked before any
image library sees it, and generated or hand-placed ICO files are checked
before Win32 or Tk load them.
"""

import struct
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MIN_ICON_SIDE = 64
MAX_ICON_SIDE = 2048
MAX_ICON_ASPECT = 2
MAX_ICON_FILE_BYTES = 8 * 1024 * 1024
MASTER_SIDE = 512
ICO_FRAME_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

_LEGAL_BIT_DEPTHS = {
    0: (1, 2, 4, 8, 16),
    2: (8, 16),
    3: (1, 2, 4, 8),
    4: (8, 16),
    6: (8, 16),
}
_ALPHA_COLOR_TYPES = (4, 6)
_IHDR_LENGTH = 13
_IHDR_CHUNK_END = len(PNG_SIGNATURE) + 4 + 4 + _IHDR_LENGTH + 4
_MAX_DECODED_BYTES = 256 * 1024 * 1024
_ADAM7_PASSES = (
    (0, 0, 8, 8),
    (4, 0, 8, 8),
    (0, 4, 4, 8),
    (2, 0, 4, 4),
    (0, 2, 2, 4),
    (1, 0, 2, 2),
    (0, 1, 1, 2),
)
_SAMPLES_PER_PIXEL = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
_MAX_CHUNK_LENGTH = 2**31 - 1
_ICO_HEADER = struct.Struct("<HHH")
_ICO_ENTRY = struct.Struct("<BBBBHHII")


class BrandIconError(ValueError):
    """An icon file cannot be used; the message says why."""


@dataclass(frozen=True)
class PngInfo:
    width: int
    height: int
    color_type: int
    bit_depth: int
    has_alpha: bool
    interlaced: bool = False


@dataclass(frozen=True)
class ValidatedIcon:
    path: Path
    info: PngInfo


@dataclass(frozen=True)
class FitRectangle:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class IcoFrame:
    width: int
    height: int
    offset: int
    length: int
    is_png: bool


def _corrupt(detail: str) -> BrandIconError:
    return BrandIconError(f"is truncated or corrupt ({detail})")


def _read_ihdr(data: bytes) -> PngInfo:
    header_error = BrandIconError("has no valid PNG header (IHDR)")
    if len(data) < 8 + 8 + _IHDR_LENGTH + 4:
        raise header_error
    length, kind = struct.unpack_from(">I4s", data, 8)
    body = data[16 : 16 + _IHDR_LENGTH]
    (checksum,) = struct.unpack_from(">I", data, 16 + _IHDR_LENGTH)
    if kind != b"IHDR" or length != _IHDR_LENGTH or zlib.crc32(kind + body) != checksum:
        raise header_error
    width, height, bit_depth, color_type, compression, filtering, interlace = (
        struct.unpack(">IIBBBBB", body)
    )
    problem = _ihdr_problem(
        width, height, bit_depth, color_type, compression, filtering, interlace
    )
    if problem is not None:
        raise BrandIconError(f"has an unsupported PNG header: {problem}")
    return PngInfo(
        width,
        height,
        color_type,
        bit_depth,
        color_type in _ALPHA_COLOR_TYPES,
        interlace == 1,
    )


def _ihdr_problem(
    width: int,
    height: int,
    bit_depth: int,
    color_type: int,
    compression: int,
    filtering: int,
    interlace: int,
) -> str | None:
    if width == 0 or height == 0 or max(width, height) > _MAX_CHUNK_LENGTH:
        return f"size {width}x{height}"
    if bit_depth not in _LEGAL_BIT_DEPTHS.get(color_type, ()):
        return f"colour type {color_type}, bit depth {bit_depth}"
    if compression != 0:
        return f"compression method {compression}"
    if filtering != 0:
        return f"filter method {filtering}"
    if interlace not in (0, 1):
        return f"interlace method {interlace}"
    return None


def _chunks(data: bytes) -> Iterator[tuple[bytes, bytes]]:
    """Yields (type, body) for each chunk after IHDR, verifying lengths, CRCs
    and that nothing follows IEND."""
    position = _IHDR_CHUNK_END
    while position < len(data):
        if position + 8 > len(data):
            raise _corrupt("chunk header is cut short")
        length, kind = struct.unpack_from(">I4s", data, position)
        name = kind.decode("latin-1")
        end = position + 8 + length + 4
        if length > _MAX_CHUNK_LENGTH or end > len(data):
            raise _corrupt(f"{name} chunk is cut short")
        body = data[position + 8 : position + 8 + length]
        (checksum,) = struct.unpack_from(">I", data, end - 4)
        if zlib.crc32(kind + body) != checksum:
            raise _corrupt(f"bad CRC in {name} chunk")
        yield kind, body
        position = end
        if kind == b"IEND":
            if position != len(data):
                raise _corrupt("data after IEND")
            return


def _walk_png(data: bytes) -> tuple[PngInfo, bytes]:
    if not data.startswith(PNG_SIGNATURE):
        raise BrandIconError("is not a PNG file (bad signature)")
    info = _read_ihdr(data)
    seen: set[bytes] = set()
    image_data: list[bytes] = []
    for kind, body in _chunks(data):
        seen.add(kind)
        if kind == b"IDAT":
            image_data.append(body)
    for required in _required_chunks(info):
        if required not in seen:
            raise _corrupt(f"{required.decode('ascii')} chunk missing")
    info = replace(info, has_alpha=info.has_alpha or b"tRNS" in seen)
    return info, b"".join(image_data)


def _decoded_size(info: PngInfo) -> int:
    bits = _SAMPLES_PER_PIXEL[info.color_type] * info.bit_depth
    if not info.interlaced:
        return info.height * (1 + (info.width * bits + 7) // 8)
    total = 0
    for x_start, y_start, x_step, y_step in _ADAM7_PASSES:
        columns = (info.width - x_start + x_step - 1) // x_step
        rows = (info.height - y_start + y_step - 1) // y_step
        if columns > 0 and rows > 0:
            total += rows * (1 + (columns * bits + 7) // 8)
    return total


def _check_image_data(info: PngInfo, image_data: bytes) -> None:
    """GDI+ draws a corrupt stream as a blank image without an error, so the
    zlib stream must be proven complete here, with its output size bounded."""
    expected = _decoded_size(info)
    broken = _corrupt("image data does not decode")
    if expected > _MAX_DECODED_BYTES:
        raise broken
    stream = zlib.decompressobj()
    try:
        decoded = stream.decompress(image_data, expected + 1)
    except zlib.error:
        raise broken from None
    if len(decoded) != expected or not stream.eof:
        raise broken


def inspect_png(data: bytes) -> PngInfo:
    """Checks the chunk structure and that the image data decodes to the size
    the header promises. Error messages carry no key prefix, so a caller can
    attach its own."""
    info, image_data = _walk_png(data)
    _check_image_data(info, image_data)
    return info


def _required_chunks(info: PngInfo) -> tuple[bytes, ...]:
    palette = (b"PLTE",) if info.color_type == 3 else ()
    return (*palette, b"IDAT", b"IEND")


def _icon_limit_problem(info: PngInfo) -> str | None:
    shorter, longer = sorted((info.width, info.height))
    size = f"{info.width}x{info.height}"
    if shorter < MIN_ICON_SIDE:
        return f"is {size}; the shorter side must be at least {MIN_ICON_SIDE} px"
    if longer > MAX_ICON_SIDE:
        return f"is {size}; the longer side must be at most {MAX_ICON_SIDE} px"
    if longer > shorter * MAX_ICON_ASPECT:
        return f"is {size}; it must be at most twice as wide as high (or the reverse)"
    return None


def _icon_file_problem(home: Path, relative_icon: str) -> tuple[Path, str | None]:
    path = (home / relative_icon).resolve()
    if not path.is_relative_to(home.resolve()):
        return path, "resolves outside the app home"
    if not path.exists():
        return path, f"file not found: {path}"
    if not path.is_file():
        return path, "is not a file"
    size = path.stat().st_size
    if size == 0:
        return path, "is empty"
    if size > MAX_ICON_FILE_BYTES:
        mebibytes = size / (1024 * 1024)
        limit = MAX_ICON_FILE_BYTES // (1024 * 1024)
        return path, f"is {mebibytes:.1f} MiB; the limit is {limit} MiB"
    return path, None


def validate_icon_png(
    home: Path, relative_icon: str, key: str = "[brand].icon"
) -> ValidatedIcon:
    """Validates a user icon before any rendering. The messages name the key
    and the configured value."""
    prefix = f'{key} "{relative_icon}": '
    try:
        path, problem = _icon_file_problem(home, relative_icon)
        if problem is not None:
            raise BrandIconError(problem)
        info, image_data = _walk_png(path.read_bytes())
        problem = _icon_limit_problem(info)
        if problem is not None:
            raise BrandIconError(problem)
        _check_image_data(info, image_data)
    except OSError as error:
        raise BrandIconError(
            prefix + f"cannot be read: {error.strerror or error}"
        ) from None
    except BrandIconError as error:
        raise BrandIconError(prefix + str(error)) from None
    return ValidatedIcon(path, info)


def fit_inside_square(width: int, height: int, side: int) -> FitRectangle:
    """The largest rectangle with the image's aspect ratio inside a square
    canvas, centred on both axes; integer maths, no cropping or stretching."""
    longer = max(width, height)
    fitted_width = max(1, (side * width + longer // 2) // longer)
    fitted_height = max(1, (side * height + longer // 2) // longer)
    return FitRectangle(
        (side - fitted_width) // 2,
        (side - fitted_height) // 2,
        fitted_width,
        fitted_height,
    )


def read_ico_frames(data: bytes) -> tuple[IcoFrame, ...]:
    """Checks the ICO container and the header of every PNG frame."""
    if len(data) < _ICO_HEADER.size:
        raise BrandIconError("ICO file is too short")
    reserved, kind, count = _ICO_HEADER.unpack_from(data)
    if (reserved, kind) != (0, 1):
        raise BrandIconError("ICO file has a bad header")
    if count == 0:
        raise BrandIconError("ICO file has no frames")
    directory_end = _ICO_HEADER.size + count * _ICO_ENTRY.size
    if directory_end > len(data):
        raise BrandIconError("ICO frame directory is cut short")
    return tuple(_read_ico_frame(data, index) for index in range(count))


def _read_ico_frame(data: bytes, index: int) -> IcoFrame:
    entry = _ICO_HEADER.size + index * _ICO_ENTRY.size
    width, height, _, _, _, _, length, offset = _ICO_ENTRY.unpack_from(data, entry)
    width, height = width or 256, height or 256
    if length == 0 or offset + length > len(data):
        raise BrandIconError(f"ICO frame {index} lies outside the file")
    frame = data[offset : offset + length]
    is_png = frame.startswith(PNG_SIGNATURE)
    if is_png:
        try:
            info = inspect_png(frame)
        except BrandIconError as error:
            raise BrandIconError(f"ICO frame {index} {error}") from None
        if (info.width, info.height) != (width, height):
            raise BrandIconError(
                f"ICO frame {index} is {info.width}x{info.height} but its "
                f"directory entry says {width}x{height}"
            )
    return IcoFrame(width, height, offset, length, is_png)


def check_standard_ico(data: bytes) -> tuple[IcoFrame, ...]:
    """The generated icon: exactly the nine standard PNG frames."""
    frames = read_ico_frames(data)
    if sorted(frame.width for frame in frames) != list(ICO_FRAME_SIZES) or not all(
        frame.is_png and frame.width == frame.height for frame in frames
    ):
        raise BrandIconError(
            "ICO file does not hold the standard square PNG frames "
            f"{', '.join(map(str, ICO_FRAME_SIZES))}"
        )
    return frames
