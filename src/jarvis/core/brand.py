"""Brand asset locations: `<home>/brand/` files win, per file, over the tracked
package defaults. Path logic only; nothing is read or written."""

from dataclasses import dataclass
from pathlib import Path

BRAND_DIRECTORY_NAME = "brand"
BRAND_PNG_NAME = "brand.png"
BRAND_ICO_NAME = "brand.ico"
PACKAGE_ASSETS = Path(__file__).resolve().parent.parent / "launcher" / "assets"
_PACKAGE_PNG_NAME = "jarvis.png"
_PACKAGE_ICO_NAME = "jarvis.ico"


@dataclass(frozen=True)
class BrandAssets:
    png: Path
    ico: Path


def brand_asset_directory(home: Path) -> Path:
    return home / BRAND_DIRECTORY_NAME


def resolve_brand_assets(home: Path) -> BrandAssets:
    directory = brand_asset_directory(home)
    return BrandAssets(
        png=_prefer(directory / BRAND_PNG_NAME, PACKAGE_ASSETS / _PACKAGE_PNG_NAME),
        ico=_prefer(directory / BRAND_ICO_NAME, PACKAGE_ASSETS / _PACKAGE_ICO_NAME),
    )


def _prefer(candidate: Path, fallback: Path) -> Path:
    return candidate if candidate.is_file() else fallback
