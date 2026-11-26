"""The launcher's view of the selected home's brand: a name and an icon.

Stdlib-only and engine-free. Reading never writes and never raises, so a
broken brand can only cost the launcher its custom look.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from jarvis.core.brand import PACKAGE_ASSETS, resolve_brand_assets
from jarvis.core.brand_icon import MAX_ICON_FILE_BYTES, BrandIconError, read_ico_frames
from jarvis.core.config import DEFAULT_BRAND_NAME, BrandSettings, load_brand

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LauncherIdentity:
    name: str
    icon: Path


DEFAULT_IDENTITY = LauncherIdentity(DEFAULT_BRAND_NAME, PACKAGE_ASSETS / "jarvis.ico")


def _usable_icon(home: Path) -> Path:
    icon = resolve_brand_assets(home).ico
    try:
        if icon.stat().st_size > MAX_ICON_FILE_BYTES:
            raise BrandIconError("ICO file is too large")
        read_ico_frames(icon.read_bytes())
    except (OSError, BrandIconError) as error:
        logger.warning(
            "Brand icon %s is not usable (%s); using the default", icon, error
        )
        return DEFAULT_IDENTITY.icon
    return icon


def load_launcher_identity(home: Path) -> LauncherIdentity:
    try:
        brand = load_brand(home / "config.toml")
    except Exception as error:
        # Deliberately broad: branding is cosmetic and no config failure,
        # including RecursionError or MemoryError from tomllib, may stop the launcher.
        logger.warning("Brand of %s is not usable (%s); using the default", home, error)
        return DEFAULT_IDENTITY
    if brand == BrandSettings():
        return DEFAULT_IDENTITY
    return LauncherIdentity(brand.name, _usable_icon(home))
