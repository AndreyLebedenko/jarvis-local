"""Change the identity of an existing Jarvis home in place.

The same planner as deployment (`plan_brand`, Copy semantics with the home as its
own source), then an all-or-nothing write: the new icons are rendered and verified
before the first file of the home is touched.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from jarvis.core.brand import BRAND_DIRECTORY_NAME, BRAND_ICO_NAME, BRAND_PNG_NAME
from jarvis.core.brand_icon import BrandIconError
from jarvis.core.brand_render import Renderer, generate_brand_assets
from jarvis.core.brand_render import run_powershell_renderer as _real_renderer
from jarvis.core.config import DEFAULT_CONFIG_PATH
from tools.deployment_brand import (
    ICON_SOURCE_PATH,
    BrandPlan,
    BrandRequest,
    BrandStageError,
    plan_brand,
    reject_ui_layer_brand,
    rewritten_config,
)
from tools.deployment_brand_check import Answer, check_brand_environment, rejected
from tools.deployment_plan import DeploymentMode, DeploymentPlanError

REBRAND_PREFIX = "JARVIS_DEPLOY_REBRAND:"
RECOVERY_COMMAND = "python -m jarvis.core.brand_render --home"
BRAND_MODULE = Path("src/jarvis/core/brand.py")
_ICON_FILES = (
    f"{BRAND_DIRECTORY_NAME}/{BRAND_PNG_NAME}",
    f"{BRAND_DIRECTORY_NAME}/{BRAND_ICO_NAME}",
)

__all__ = [
    "REBRAND_PREFIX",
    "RECOVERY_COMMAND",
    "BrandStageError",
    "RebrandResult",
    "check_home_brand",
    "rebrand_home",
]


@dataclass(frozen=True)
class RebrandResult:
    brand: dict[str, object]
    files: tuple[str, ...]


def _eligible_home(home: Path) -> None:
    if not home.is_dir():
        raise DeploymentPlanError(f"The Jarvis home does not exist: {home}")
    if not (home / DEFAULT_CONFIG_PATH).is_file():
        raise DeploymentPlanError(
            f"{home} has no {DEFAULT_CONFIG_PATH}; choose an installed Jarvis home"
        )
    if not (home / BRAND_MODULE).is_file():
        raise DeploymentPlanError(
            f"{home} predates instance branding ({BRAND_MODULE} is missing); "
            "update this home first, because its Jarvis would not read [brand]"
        )


def _check_request(request: BrandRequest | None) -> BrandRequest:
    if request is None or request.is_empty:
        raise DeploymentPlanError(
            "Nothing to change: give at least one of -Name, -Monogram, -Accent, "
            "-Icon, -NoIcon or -DefaultBrand. To rebuild the icons from the current "
            "[brand], use Regenerate icons in the launcher Settings or "
            f"{RECOVERY_COMMAND} <home>"
        )
    return request


def _replace_file(path: Path, data: bytes) -> None:
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=".rebrand-")
    temporary = Path(name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _install_icon_source(source: Path, destination: Path) -> bool:
    if destination.exists() and os.path.samefile(source, destination):
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    _replace_file(destination, source.read_bytes())
    return True


def _writer(
    home: Path, plan: BrandPlan, content: str, written: str
) -> Callable[[], list[str]]:
    config = home / DEFAULT_CONFIG_PATH

    def write() -> list[str]:
        files: list[str] = []
        if plan.external_icon is not None and _install_icon_source(
            plan.external_icon, home / ICON_SOURCE_PATH
        ):
            files.append(ICON_SOURCE_PATH)
        if written != content:
            _replace_file(config, written.encode("utf-8"))
            files.append(DEFAULT_CONFIG_PATH.as_posix())
        return files

    return write


def _incomplete(home: Path, error: Exception) -> BrandStageError:
    return BrandStageError(
        f"The identity was not applied completely: {error}. Check [brand] in "
        f"{home / DEFAULT_CONFIG_PATH}, then rebuild the icons with: "
        f"{RECOVERY_COMMAND} {home}"
    )


def rebrand_home(
    home: Path,
    request: BrandRequest | None,
    *,
    renderer: Renderer = _real_renderer,
) -> RebrandResult:
    _eligible_home(home)
    request = _check_request(request)
    reject_ui_layer_brand(home)
    plan = plan_brand(home, DeploymentMode.COPY, request)
    config = home / DEFAULT_CONFIG_PATH
    content = config.read_bytes().decode("utf-8")
    written = rewritten_config(content, plan.table, config)
    write = _writer(home, plan, content, written)
    if plan.is_default:
        try:
            files = write()
        except OSError as error:
            raise _incomplete(home, error) from None
        return RebrandResult(plan.preview(), tuple(files))
    return _render_and_write(home, plan, renderer, write)


@dataclass
class _Progress:
    writing: bool = False
    files: tuple[str, ...] = ()


def _render_and_write(
    home: Path,
    plan: BrandPlan,
    renderer: Renderer,
    write: Callable[[], list[str]],
) -> RebrandResult:
    progress = _Progress()

    def before_publish() -> None:
        progress.writing = True
        progress.files = tuple(write())

    try:
        generate_brand_assets(
            home,
            plan.brand,
            renderer=renderer,
            image=plan.external_icon,
            before_publish=before_publish,
        )
    except (BrandIconError, OSError) as error:
        if progress.writing:
            raise _incomplete(home, error) from None
        if isinstance(error, BrandIconError):
            raise DeploymentPlanError(str(error)) from None
        raise
    return RebrandResult(plan.preview(), (*progress.files, *_ICON_FILES))


def check_home_brand(home: Path, environment: Mapping[str, str]) -> Answer:
    """Read-only: what a rebrand of this home would resolve to, or why it cannot.
    An empty request is a valid question (it answers the stored brand)."""
    try:
        _eligible_home(home)
        reject_ui_layer_brand(home)
    except DeploymentPlanError as error:
        return rejected(str(error))
    return check_brand_environment(home, DeploymentMode.COPY, environment)
