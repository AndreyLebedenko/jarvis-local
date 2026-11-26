"""Shared fixtures for the brand deployment tests (not a test module)."""

from __future__ import annotations

from pathlib import Path

from png_fixtures import make_ico, make_png

from jarvis.core.brand_icon import ICO_FRAME_SIZES
from tools.deployment_plan import APPLICATION_FILES, PACKAGE_DIR

GOOD_PNG = make_png(512, 512)
GOOD_ICO = make_ico([(side, make_png(side, side)) for side in ICO_FRAME_SIZES])
USER_PNG = make_png(256, 128)
EXAMPLE_CONFIG = '# Example configuration\n[ui]\nlanguage = "en"\n'


class FakeRenderer:
    """Writes a valid master PNG and ICO, like the real renderer would."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.requests: list[object] = []

    def __call__(self, request: object, output_png: Path, output_ico: Path) -> None:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        output_png.write_bytes(GOOD_PNG)
        output_ico.write_bytes(GOOD_ICO)


def make_source_home(home: Path) -> Path:
    for name in (*APPLICATION_FILES, PACKAGE_DIR / "__init__.py"):
        path = home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            EXAMPLE_CONFIG if name == Path("config.example.toml") else str(name),
            encoding="utf-8",
        )
    return home


def put(path: Path, data: bytes | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8", newline="")
    else:
        path.write_bytes(data)
    return path
