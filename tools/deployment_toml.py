"""Rewrite existing TOML path scalars and verify each edit with tomllib."""

from __future__ import annotations

import json
import re
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import TypeAlias

from tools.deployment_plan import DeploymentPlanError

ConfigKey: TypeAlias = tuple[str, ...]
TomlTable: TypeAlias = dict[str, object]

_HEADER = re.compile(r"\s*\[([\w.-]+)\]\s*(?:#.*)?$")
_STRING = re.compile(
    r"[ \t]*(?P<key>[\w-]+)[ \t]*=[ \t]*"
    r"(?P<value>\"(?:[^\"\\\r\n]|\\.)*\"|'[^'\r\n]*')(?=[ \t]*(?:#.*)?$)"
)


def label(key: ConfigKey) -> str:
    return f"[{'.'.join(key[:-1])}].{key[-1]}"


def parse_layer(content: str, origin: Path) -> TomlTable:
    try:
        return tomllib.loads(content)
    except tomllib.TOMLDecodeError as error:
        raise DeploymentPlanError(f"Cannot parse {origin}: {error}") from error


def table_at(table: TomlTable, section: ConfigKey) -> TomlTable:
    for name in section:
        child = table.get(name)
        if not isinstance(child, dict):
            return {}
        table = child
    return table


def _matches(text: str, expected: TomlTable) -> bool:
    try:
        return tomllib.loads(text) == expected
    except tomllib.TOMLDecodeError:
        return False


def _patch_scalar(
    lines: list[str], table: TomlTable, key: ConfigKey, value: str
) -> bool:
    original = table_at(table, key[:-1])[key[-1]]
    probe = value if original != value else value + "__jarvis_path_probe__"
    expected = deepcopy(table)
    table_at(expected, key[:-1])[key[-1]] = probe
    section = ""
    for index, line in enumerate(lines):
        body = line.rstrip("\r\n")
        if header := _HEADER.fullmatch(body):
            section = header[1]
        if section != ".".join(key[:-1]):
            continue
        match = _STRING.match(body)
        if not match or match["key"] != key[-1]:
            continue
        start, end = match.span("value")
        prefix, suffix = line[:start], line[end:]
        lines[index] = prefix + json.dumps(probe, ensure_ascii=False) + suffix
        if _matches("".join(lines), expected):
            if original == value:
                lines[index] = line
            table_at(table, key[:-1])[key[-1]] = value
            return True
        lines[index] = line
    return False


def patch_paths(content: str, replacements: dict[ConfigKey, str], origin: Path) -> str:
    """Accept only simple string assignments under their explicit table header."""
    expected = parse_layer(content, origin)
    lines = content.splitlines(keepends=True)
    for key, value in replacements.items():
        if key[-1] not in table_at(expected, key[:-1]):
            continue
        if not _patch_scalar(lines, expected, key, value):
            raise DeploymentPlanError(
                f"Cannot rebase {label(key)} in {origin}. "
                "Use a single-line quoted value under its explicit table header."
            )
    result = "".join(lines)
    if replacements and not _matches(result, expected):
        raise DeploymentPlanError(f"TOML verification failed for {origin}")
    return result
