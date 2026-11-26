"""Test-only reader for 8-bit RGBA, non-interlaced PNGs (what GDI+ writes)."""

import struct
import zlib

Pixel = tuple[int, int, int, int]


def read_rgba(data: bytes) -> tuple[int, int, list[bytes]]:
    width, height, depth, color_type, _, _, interlace = struct.unpack_from(
        ">IIBBBBB", data, 16
    )
    assert (depth, color_type, interlace) == (8, 6, 0), "RGBA8 non-interlaced only"
    position, compressed = 8, b""
    while position < len(data):
        length, kind = struct.unpack_from(">I4s", data, position)
        if kind == b"IDAT":
            compressed += data[position + 8 : position + 8 + length]
        position += 12 + length
    raw = zlib.decompress(compressed)
    stride = width * 4
    rows: list[bytes] = []
    previous = bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        method, line = raw[start], bytearray(raw[start + 1 : start + 1 + stride])
        _unfilter(method, line, previous)
        rows.append(bytes(line))
        previous = line
    return width, height, rows


def _unfilter(method: int, line: bytearray, previous: bytearray) -> None:
    for i in range(len(line)):
        left = line[i - 4] if i >= 4 else 0
        up = previous[i]
        corner = previous[i - 4] if i >= 4 else 0
        if method == 1:
            line[i] = (line[i] + left) & 255
        elif method == 2:
            line[i] = (line[i] + up) & 255
        elif method == 3:
            line[i] = (line[i] + (left + up) // 2) & 255
        elif method == 4:
            estimate = left + up - corner
            distances = (
                abs(estimate - left),
                abs(estimate - up),
                abs(estimate - corner),
            )
            best = distances.index(min(distances))
            line[i] = (line[i] + (left, up, corner)[best]) & 255


def pixel(rows: list[bytes], x: int, y: int) -> Pixel:
    return tuple(rows[y][x * 4 : x * 4 + 4])  # type: ignore[return-value]
