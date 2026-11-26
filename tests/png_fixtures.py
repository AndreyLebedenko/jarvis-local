"""Builds PNG and ICO bytes for tests; no binary fixture files are committed."""

import struct
import zlib

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


_ADAM7 = (
    (0, 0, 8, 8),
    (4, 0, 8, 8),
    (0, 4, 4, 8),
    (2, 0, 4, 4),
    (0, 2, 2, 4),
    (1, 0, 2, 2),
    (0, 1, 1, 2),
)


def _adam7_size(width: int, height: int, bits: int) -> int:
    total = 0
    for x0, y0, dx, dy in _ADAM7:
        columns, rows = -(-(width - x0) // dx), -(-(height - y0) // dy)
        if columns > 0 and rows > 0:
            total += rows * (1 + (columns * bits + 7) // 8)
    return total


def chunk(kind: bytes, data: bytes = b"", *, crc: int | None = None) -> bytes:
    checksum = zlib.crc32(kind + data) if crc is None else crc
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def ihdr(
    width: int,
    height: int,
    *,
    color_type: int = 6,
    bit_depth: int = 8,
    compression: int = 0,
    filter_method: int = 0,
    interlace: int = 0,
) -> bytes:
    return struct.pack(
        ">IIBBBBB",
        width,
        height,
        bit_depth,
        color_type,
        compression,
        filter_method,
        interlace,
    )


def make_png(
    width: int,
    height: int,
    *,
    color_type: int = 6,
    bit_depth: int = 8,
    interlace: int = 0,
    transparency: bool = False,
    pixel: bytes | None = None,
) -> bytes:
    """A PNG whose image data decodes to the size its header promises: rows are
    filter 0 and one colour (interlaced images are all zero bytes)."""
    channels = _CHANNELS[color_type]
    bits_per_pixel = channels * bit_depth
    row_bytes = (width * bits_per_pixel + 7) // 8
    row = (
        bytes(row_bytes)
        if pixel is None
        else (pixel * (row_bytes // len(pixel) + 1))[:row_bytes]
    )
    raw = (
        bytes(_adam7_size(width, height, bits_per_pixel))
        if interlace
        else (b"\x00" + row) * height
    )
    parts = [
        PNG_SIGNATURE,
        chunk(
            b"IHDR",
            ihdr(
                width,
                height,
                color_type=color_type,
                bit_depth=bit_depth,
                interlace=interlace,
            ),
        ),
    ]
    if color_type == 3:
        parts.append(chunk(b"PLTE", b"\x00\x00\x00\xff\xff\xff"))
    if transparency:
        parts.append(chunk(b"tRNS", b"\x00"))
    parts.append(chunk(b"IDAT", zlib.compress(raw)))
    parts.append(chunk(b"IEND"))
    return b"".join(parts)


def make_ico(frames: list[tuple[int, bytes]]) -> bytes:
    """An ICO whose frames are (side, data); side 256 is stored as 0."""
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    entries = b""
    for side, data in frames:
        stored = 0 if side == 256 else side
        entries += struct.pack(
            "<BBBBHHII", stored, stored, 0, 0, 1, 32, len(data), offset
        )
        offset += len(data)
    return header + entries + b"".join(data for _, data in frames)
