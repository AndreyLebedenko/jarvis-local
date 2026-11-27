"""Plan, write and generate the brand of a deployed Jarvis home."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from jarvis.core.brand import BRAND_DIRECTORY_NAME, BRAND_ICO_NAME, BRAND_PNG_NAME
from jarvis.core.brand_icon import (
    BrandIconError,
    ValidatedIcon,
    validate_icon_file,
    validate_icon_png,
)
from jarvis.core.brand_render import Renderer, regenerate_home_icons
from jarvis.core.config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_UI_CONFIG_PATH,
    BrandSettings,
    ConfigError,
    brand_from_table,
    load_brand,
)
from tools.deployment_plan import DeploymentMode, DeploymentPlanError
from tools.deployment_snapshot import check_directory_tree, copy_directory_by_value
from tools.deployment_toml import (
    parse_layer,
    remove_table,
    remove_table_strings,
    set_table_strings,
)

BRAND_ENVIRONMENT_VARIABLE = "JARVIS_DEPLOY_BRAND"
BRAND_TABLE = "brand"
ICON_SOURCE_PATH = "brand-source/icon.png"
_EXAMPLE_CONFIG = Path("config.example.toml")
_TEXT_OPTIONS = ("name", "monogram", "accent", "icon")
_SWITCH_OPTIONS = ("no_icon", "default_brand")
_OPTION_FLAGS = {
    "name": "-Name",
    "monogram": "-Monogram",
    "accent": "-Accent",
    "icon": "-Icon",
    "no_icon": "-NoIcon",
    "default_brand": "-DefaultBrand",
}


class BrandStageError(RuntimeError):
    """Generating the icons of a deployed home could not be attempted."""


@dataclass(frozen=True)
class BrandRequest:
    """What the owner asked for; a field left unset keeps what is stored."""

    name: str | None = None
    monogram: str | None = None
    accent: str | None = None
    icon: Path | None = None
    no_icon: bool = False
    default_brand: bool = False

    def __post_init__(self) -> None:
        if self.default_brand and self._others():
            raise DeploymentPlanError(
                "-DefaultBrand cannot be combined with other brand options"
            )
        if self.icon is not None and self.no_icon:
            raise DeploymentPlanError("-Icon and -NoIcon cannot be combined")

    def _others(self) -> list[str]:
        return [
            option
            for option in (*_TEXT_OPTIONS, "no_icon")
            if getattr(self, option) not in (None, False)
        ]

    @property
    def is_empty(self) -> bool:
        return not (self._others() or self.default_brand)


def request_from_json(text: str) -> BrandRequest:
    try:
        payload = json.loads(text)
    except ValueError as error:
        raise DeploymentPlanError(
            f"Brand options are not valid JSON: {error}"
        ) from None
    if not isinstance(payload, dict):
        raise DeploymentPlanError("Brand options must be a JSON object")
    unknown = sorted(set(payload) - {*_TEXT_OPTIONS, *_SWITCH_OPTIONS})
    if unknown:
        raise DeploymentPlanError(f"Unknown brand option(s): {', '.join(unknown)}")
    values: dict[str, object] = {}
    for option, value in payload.items():
        wanted = bool if option in _SWITCH_OPTIONS else str
        if not isinstance(value, wanted):
            raise DeploymentPlanError(
                f"{_OPTION_FLAGS[option]} must be a {wanted.__name__}, got {value!r}"
            )
        values[option] = Path(value) if option == "icon" else value
    return BrandRequest(**values)


def request_from_environment(environment: Mapping[str, str]) -> BrandRequest | None:
    text = environment.get(BRAND_ENVIRONMENT_VARIABLE)
    return request_from_json(text) if text else None


@dataclass(frozen=True)
class BrandPlan:
    """Everything the brand step needs, validated and read-only."""

    brand: BrandSettings
    table: dict[str, str]
    origin: str
    external_icon: Path | None = None
    carried_icon: Path | None = None
    carried_assets: Path | None = None

    @property
    def is_default(self) -> bool:
        return self.brand == BrandSettings()

    def preview(self) -> dict[str, object]:
        return {
            "name": self.brand.name,
            "monogram": self.brand.monogram,
            "accent": self.brand.accent,
            "icon": self.brand.icon,
            "is_default": self.is_default,
            "origin": self.origin,
        }


def _stored_table(source: Path) -> dict[str, str]:
    path = source / DEFAULT_CONFIG_PATH
    if not path.is_file():
        return {}
    layer = parse_layer(path.read_bytes().decode("utf-8"), path)
    table = layer.get(BRAND_TABLE, {})
    if not isinstance(table, dict):
        raise DeploymentPlanError(f"[brand] ({path}) must be a table")
    return table


def _merge(stored: dict[str, str], request: BrandRequest) -> dict[str, str]:
    if request.default_brand:
        return {}
    merged = dict(stored)
    for option in ("name", "monogram", "accent"):
        if (value := getattr(request, option)) is not None:
            merged[option] = value
    if request.icon is not None:
        merged["icon"] = ICON_SOURCE_PATH
    if request.no_icon:
        merged.pop("icon", None)
    return merged


def _validated_brand(table: dict[str, str]) -> BrandSettings:
    try:
        return brand_from_table(table)
    except ConfigError as error:
        raise DeploymentPlanError(str(error)) from None


def _checked_icon(validate: Callable[[], ValidatedIcon]) -> Path:
    try:
        return validate().path
    except BrandIconError as error:
        raise DeploymentPlanError(str(error)) from None


def _carried_assets(source: Path) -> Path | None:
    assets = source / BRAND_DIRECTORY_NAME
    if not assets.exists():
        return None
    if assets.resolve() != assets:
        raise DeploymentPlanError(f"Cannot copy a linked brand directory: {assets}")
    if not assets.is_dir():
        raise DeploymentPlanError(f"The brand path is not a directory: {assets}")
    try:
        check_directory_tree(assets)
    except OSError as error:
        raise DeploymentPlanError(f"Cannot read the brand directory: {error}") from None
    return assets


def _refuse_generated_file(source: Path, icon: Path, configured: str) -> None:
    generated = (
        os.path.normcase(str((source / BRAND_DIRECTORY_NAME / name).resolve()))
        for name in (BRAND_PNG_NAME, BRAND_ICO_NAME)
    )
    if os.path.normcase(str(icon)) in generated:
        raise DeploymentPlanError(
            f'[brand].icon "{configured}": is a generated brand file that the '
            "deployment replaces; keep the source PNG elsewhere, for example "
            "brand-source/icon.png"
        )


def _carried_icon(
    source: Path, stored: dict[str, str], brand: BrandSettings, request: BrandRequest
) -> Path | None:
    inherited = brand.icon is not None and brand.icon == stored.get("icon")
    if not inherited or request.icon is not None:
        return None
    if not request.is_empty:
        icon = _checked_icon(lambda: validate_icon_png(source, str(brand.icon)))
        _refuse_generated_file(source, icon, str(brand.icon))
        return icon
    icon = (source / str(brand.icon)).resolve()
    return icon if icon.is_file() and icon.is_relative_to(source.resolve()) else None


def _check_rewrite(
    source: Path, is_copy: bool, table: dict[str, str], brand: BrandSettings
) -> None:
    """Dry run of the destination rewrite on the text the destination will be
    made from, so an unsupported [brand] form is refused naming the source file
    before anything is written. Path rebasing never touches [brand]."""
    config = source / DEFAULT_CONFIG_PATH
    path = config if is_copy and config.is_file() else source / _EXAMPLE_CONFIG
    result = rewritten_config(path.read_bytes().decode("utf-8"), table, path)
    written = parse_layer(result, path).get(BRAND_TABLE, {})
    if not isinstance(written, dict) or _validated_brand(written) != brand:
        raise DeploymentPlanError(f"Cannot rewrite [brand] in {path}")


def plan_brand(
    source: Path, mode: DeploymentMode, request: BrandRequest | None
) -> BrandPlan:
    """Read-only: validates the request and everything it needs from disk."""
    request = request or BrandRequest()
    is_copy = mode is DeploymentMode.COPY
    stored = _stored_table(source) if is_copy else {}
    table = _merge(stored, request)
    brand = _validated_brand(table)
    _check_rewrite(source, is_copy, table, brand)
    external = request.icon
    faithful = is_copy and request.is_empty and brand != BrandSettings()
    if brand == BrandSettings():
        origin = "default"
    else:
        origin = "inherited" if request.is_empty else "requested"
    return BrandPlan(
        brand=brand,
        table=table,
        origin=origin,
        external_icon=(
            _checked_icon(lambda: validate_icon_file(external)) if external else None
        ),
        carried_icon=_carried_icon(source, stored, brand, request) if is_copy else None,
        carried_assets=_carried_assets(source) if faithful else None,
    )


def _destination_config(target: Path) -> str | None:
    for name in (DEFAULT_CONFIG_PATH, _EXAMPLE_CONFIG):
        path = target / name
        if path.is_file():
            return path.read_bytes().decode("utf-8")
    return None


def reject_ui_layer_brand(target: Path) -> None:
    path = target / DEFAULT_UI_CONFIG_PATH
    if path.is_file() and BRAND_TABLE in parse_layer(path.read_text("utf-8"), path):
        raise DeploymentPlanError(
            f"[brand] ({path}) belongs in config.toml: the Settings form "
            "rewrites this file and would drop it"
        )


def rewritten_config(content: str, table: dict[str, str], origin: Path) -> str:
    if not table:
        return remove_table(content, BRAND_TABLE, origin)
    current = parse_layer(content, origin).get(BRAND_TABLE, {})
    if not isinstance(current, dict):
        raise DeploymentPlanError(f"[brand] ({origin}) must be a table")
    result = remove_table_strings(
        content, BRAND_TABLE, [key for key in current if key not in table], origin
    )
    changed = {key: value for key, value in table.items() if current.get(key) != value}
    return (
        set_table_strings(result, BRAND_TABLE, changed, origin) if changed else result
    )


def _rewrite_config(target: Path, plan: BrandPlan) -> None:
    content = _destination_config(target)
    if content is None:
        return
    config = target / DEFAULT_CONFIG_PATH
    result = rewritten_config(content, plan.table, config)
    if result != content:
        config.write_bytes(result.encode("utf-8"))


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def apply_brand(plan: BrandPlan, target: Path) -> None:
    """Writes the destination brand. A faithful Copy changes nothing in the
    copied config; every failure is raised before the deployment is ready."""
    reject_ui_layer_brand(target)
    _rewrite_config(target, plan)
    if plan.carried_assets is not None:
        copy_directory_by_value(plan.carried_assets, target / BRAND_DIRECTORY_NAME)
    if plan.carried_icon is not None and plan.brand.icon is not None:
        _copy_file(plan.carried_icon, target / plan.brand.icon)
    if plan.external_icon is not None:
        _copy_file(plan.external_icon, target / ICON_SOURCE_PATH)
    _verify_destination(target, plan)


def _verify_destination(target: Path, plan: BrandPlan) -> None:
    config = target / DEFAULT_CONFIG_PATH
    if not config.is_file():
        return
    try:
        written = load_brand(config)
    except ConfigError as error:
        raise DeploymentPlanError(f"Invalid destination brand: {error}") from None
    if written != plan.brand:
        raise DeploymentPlanError(
            f"The destination brand does not match the request: {written}"
        )


def generate_missing_icons(home: Path, *, renderer: Renderer) -> str | None:
    """Generates the icons of a branded home that lacks either file. Existing
    files, even stale ones, are kept. Returns the generator's message, or None
    when nothing was needed."""
    if not home.is_dir():
        raise BrandStageError(f"The destination home does not exist: {home}")
    if load_brand(home / DEFAULT_CONFIG_PATH) == BrandSettings():
        return None
    assets = home / BRAND_DIRECTORY_NAME
    if all((assets / name).is_file() for name in (BRAND_PNG_NAME, BRAND_ICO_NAME)):
        return None
    return regenerate_home_icons(home, renderer=renderer).message
