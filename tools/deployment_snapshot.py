"""Copy Jarvis state and keep the destination's paths inside its own home."""

from __future__ import annotations

import filecmp
import hashlib
import os
import shutil
import stat
from collections.abc import Iterator
from dataclasses import dataclass, fields
from pathlib import Path, PureWindowsPath

from jarvis.core.config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_UI_CONFIG_PATH,
    ConfigError,
    PersonalProxySettings,
    SoundCueSettings,
    TtsSettings,
    load_settings,
)
from tools.deployment_plan import (
    DeploymentPlanError,
    SnapshotPlan,
    check_snapshot_providers,
)
from tools.deployment_toml import (
    ConfigKey,
    TomlTable,
    label,
    parse_layer,
    patch_paths,
    table_at,
)

_ROOT_PATHS: dict[ConfigKey, str] = {
    ("journal", "root"): "journal",
    ("memory", "root"): "memory",
    ("logging", "directory"): "logs",
    ("mcp_mode", "token_file"): "mcp_mode.token",
}
_PROXY_DEFAULTS = PersonalProxySettings()
_CUE_DEFAULTS = SoundCueSettings()
_OPTIONAL_PATHS: dict[ConfigKey, str] = {
    ("personal_proxy", "topics_file"): _PROXY_DEFAULTS.topics_file,
    ("personal_proxy", "public_names_file"): _PROXY_DEFAULTS.public_names_file,
    **{
        ("sound_cues", field.name): getattr(_CUE_DEFAULTS, field.name)
        for field in fields(SoundCueSettings)
    },
}
_PIPER_PATHS = ("model", "config_path", "espeak_data_dir", "download_dir")
_PROMPT_KEYS: tuple[ConfigKey, ...] = (
    ("prompts", "voice_turn_instruction"),
    ("response", "voice_contract"),
    ("response", "speech_language_ru"),
    ("response", "speech_language_en"),
    ("response", "speech_language_request"),
)
_LAYERS = (DEFAULT_CONFIG_PATH, DEFAULT_UI_CONFIG_PATH)
_EXAMPLE_CONFIG = Path("config.example.toml")
_DEFAULT_TTS_ENGINES = {
    language: route.engine for language, route in TtsSettings().languages.items()
}


@dataclass(frozen=True)
class _Asset:
    source: Path | None
    destination: Path
    directory: bool = False


@dataclass(frozen=True)
class _Layer:
    name: Path
    content: str
    table: TomlTable


def _read_layer(home: Path, name: Path) -> _Layer:
    origin = home / name
    try:
        content = origin.read_bytes().decode("utf-8")
    except FileNotFoundError:
        content = ""
    return _Layer(name, content, parse_layer(content, origin))


def _lookup(table: TomlTable, key: ConfigKey) -> object:
    return table_at(table, key[:-1]).get(key[-1])


def _paths(table: TomlTable, inherited: TomlTable) -> Iterator[tuple[ConfigKey, str]]:
    for key in (*_ROOT_PATHS, *_OPTIONAL_PATHS):
        if isinstance(value := _lookup(table, key), str):
            yield key, value
    for language in table_at(table, ("tts", "languages")):
        route = ("tts", "languages", language)
        engine_key = (*route, "engine")
        engine = (
            _lookup(table, engine_key)
            or _lookup(inherited, engine_key)
            or _DEFAULT_TTS_ENGINES.get(language)
        )
        if engine != "piper":
            continue
        for field in _PIPER_PATHS:
            key = (*route, field)
            if isinstance(value := _lookup(table, key), str):
                yield key, value


def _generation_prompt_keys(table: TomlTable) -> Iterator[ConfigKey]:
    for name in table_at(table, ("generation",)):
        section = ("generation", name)
        if name == "dialog":
            for level in table_at(table, section):
                yield (*section, level, "prompt")
        else:
            yield (*section, "prompt")


def _prompt_paths(table: TomlTable) -> Iterator[tuple[ConfigKey, Path]]:
    for key in (*_PROMPT_KEYS, *_generation_prompt_keys(table)):
        value = _lookup(table, key)
        if isinstance(value, str) and value.startswith("@"):
            path = PureWindowsPath(value[1:])
            parts = path.parts[1:] if path.anchor else path.parts
            if not parts or ".." in parts:
                raise DeploymentPlanError(f"{label(key)} must stay inside .jarvis")
            yield key, Path(".jarvis", *parts)


def _source_path(source: Path, raw: str, key: ConfigKey) -> Path:
    path = Path(raw)
    if path.anchor and not path.is_absolute():
        raise DeploymentPlanError(f"{label(key)} uses an ambiguous Windows path: {raw}")
    try:
        return (source / path).resolve()
    except (OSError, RuntimeError) as error:
        raise DeploymentPlanError(f"Cannot resolve {label(key)}: {raw}") from error


def _asset_path(source: Path, key: ConfigKey, path: Path) -> Path:
    if key[-1] in {"model", "config_path"} and path.is_relative_to(source):
        relative = path.relative_to(source)
        if relative.parts and relative.parts[0].casefold() != ".venv":
            return relative
    kind = ("piper", key[-1]) if key[0] == "tts" else key
    fingerprint = hashlib.sha256(os.path.normcase(str(path)).encode("utf-8"))
    return Path(
        ".jarvis", "deployment-assets", *kind, fingerprint.hexdigest(), path.name
    )


def _assets_for_path(
    source: Path, key: ConfigKey, value: str
) -> tuple[str, tuple[_Asset, ...]]:
    original = _source_path(source, value, key)
    if key in _OPTIONAL_PATHS and value == _OPTIONAL_PATHS[key]:
        return value, ()  # Default assets are handled once, across both layers.
    if not original.exists() and key[0] == "personal_proxy":
        if not original.is_relative_to(source):
            raise DeploymentPlanError(
                f"{label(key)} does not exist outside the source: {original}"
            )
        path = Path(value)
        local = (
            value
            if not path.anchor and ".." not in path.parts
            else original.relative_to(source).as_posix()
        )
        return local, ()
    destination = _asset_path(source, key, original)
    if key[-1] == "download_dir":
        return destination.as_posix(), (_Asset(None, destination, directory=True),)
    assets = (_Asset(original, destination, directory=key[-1] == "espeak_data_dir"),)
    if key[-1] == "model":
        sidecar = _source_path(source, f"{value}.json", (*key[:-1], "config_path"))
        assets += (_Asset(sidecar, Path(f"{destination}.json")),)
    return (value if destination == Path(value) else destination.as_posix()), assets


def _prepare_layer(
    source: Path, layer: _Layer, inherited: TomlTable
) -> tuple[str, list[_Asset]]:
    replacements = dict(_ROOT_PATHS)
    assets = []
    for key, value in _paths(layer.table, inherited):
        if key in _ROOT_PATHS:
            continue
        replacements[key], transfers = _assets_for_path(source, key, value)
        assets.extend(transfers)
    for key, relative in _prompt_paths(layer.table):
        path = _source_path(source, str(relative), key)
        if not path.is_file():
            raise DeploymentPlanError(
                f"{label(key)} does not resolve to a file: {path}"
            )
        assets.append(_Asset(path, relative))
    return patch_paths(layer.content, replacements, source / layer.name), assets


def _tree_entries(source: Path) -> Iterator[tuple[Path, bool]]:
    for child in source.iterdir():
        metadata = child.lstat()
        if stat.S_ISLNK(metadata.st_mode) or (
            getattr(metadata, "st_file_attributes", 0)
            & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise DeploymentPlanError(f"Cannot copy a nested linked path: {child}")
        directory = stat.S_ISDIR(metadata.st_mode)
        if not directory and not stat.S_ISREG(metadata.st_mode):
            raise DeploymentPlanError(f"Cannot copy a non-regular file: {child}")
        yield child, directory
        if directory:
            yield from _tree_entries(child)


def _copy_tree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    for child, directory in _tree_entries(source):
        target = destination / child.relative_to(source)
        if directory:
            target.mkdir()
        else:
            shutil.copy2(child, target)


def check_directory_tree(source: Path) -> None:
    """Refuses a tree that holds a link or a non-regular file."""
    for _ in _tree_entries(source):
        continue


def copy_directory_by_value(source: Path, destination: Path) -> None:
    _copy_tree(source, destination)


def _copy_asset(asset: _Asset, source: Path, target: Path) -> None:
    destination = target / asset.destination
    original = asset.source
    if original is None:
        destination.mkdir(parents=True)
        return
    if original.is_relative_to(target) or target.is_relative_to(original):
        raise DeploymentPlanError(f"Asset path overlaps the deployment: {original}")
    if not original.exists():
        return
    if destination.exists():
        if (
            not asset.directory
            and destination.is_file()
            and original.is_file()
            and filecmp.cmp(original, destination, shallow=False)
        ):
            return
        raise DeploymentPlanError(f"Snapshot asset path conflicts: {destination}")
    if asset.directory and original.is_dir() and not source.is_relative_to(original):
        _copy_tree(original, destination)
    elif not asset.directory and original.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, destination)
    else:
        raise DeploymentPlanError(f"Unsupported snapshot asset path: {original}")


def snapshot_layers(
    source: Path, plan: SnapshotPlan
) -> Iterator[tuple[Path, str, list[_Asset]]]:
    inherited: TomlTable = {}
    for name in _LAYERS:
        if name not in plan.config_files:
            continue
        layer = _read_layer(source, name)
        content, transfers = _prepare_layer(source, layer, inherited)
        inherited = layer.table
        yield name, content, transfers


def copy_snapshot(source: Path, target: Path, plan: SnapshotPlan) -> None:
    assets = [
        _Asset(_source_path(source, value, key), Path(value))
        for key, value in _OPTIONAL_PATHS.items()
    ]
    for name, content, transfers in snapshot_layers(source, plan):
        (target / name).write_bytes(content.encode("utf-8"))
        assets.extend(transfers)
    for root, name in ((plan.journal, "journal"), (plan.memory, "memory")):
        if root.is_dir():
            _copy_tree(root, target / name)
    for asset in dict.fromkeys(assets):
        _copy_asset(asset, source, target)
    validate_copy(target)


def _verify_local(home: Path, key: ConfigKey, value: str) -> None:
    path = _source_path(home, value, key)
    if path == home or not path.is_relative_to(home):
        raise DeploymentPlanError(f"{label(key)} resolves outside the copy: {path}")


def _validate_layer_paths(home: Path, base: Path) -> None:
    inherited: TomlTable = {}
    for name in (base, DEFAULT_UI_CONFIG_PATH):
        table = _read_layer(home, name).table
        for key, value in _paths(table, inherited):
            _verify_local(home, key, value)
        for key, path in _prompt_paths(table):
            _verify_local(home, key, str(path))
        inherited = table
    for key, value in {**_ROOT_PATHS, **_OPTIONAL_PATHS}.items():
        _verify_local(home, key, value)


def validate_copy(home: Path, *, check_snapshot_tree: bool = False) -> None:
    base = (
        DEFAULT_CONFIG_PATH
        if (home / DEFAULT_CONFIG_PATH).is_file()
        else _EXAMPLE_CONFIG
    )
    _validate_layer_paths(home, base)
    try:
        settings = load_settings(home / base)
    except ConfigError as error:
        raise DeploymentPlanError(f"Invalid destination settings: {error}") from error
    check_snapshot_providers(settings)
    if base == _EXAMPLE_CONFIG:
        _check_example_snapshot_roots(home, settings.journal.root, settings.memory.root)
    for key, root in (
        ("self_file", settings.memory.self_file),
        ("memory_file", settings.memory.memory_file),
    ):
        _verify_local(home, ("memory", key), str(Path(settings.memory.root) / root))
    if check_snapshot_tree:
        for value in (settings.journal.root, settings.memory.root):
            root = home / value
            if root.is_dir():
                for _ in _tree_entries(root):
                    continue


def _check_example_snapshot_roots(home: Path, journal: str, memory: str) -> None:
    for section, value in (("journal", journal), ("memory", memory)):
        key = (section, "root")
        if _source_path(home, value, key) != home / section:
            raise DeploymentPlanError(
                f"{label(key)} from the installer configuration does not match the "
                f"snapshot directory {section}. Configure the source in config.toml."
            )
