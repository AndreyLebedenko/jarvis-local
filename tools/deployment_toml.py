"""Rewrite existing TOML path scalars and verify each edit with tomllib."""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import TypeAlias

from tools.deployment_plan import DeploymentPlanError

ConfigKey: TypeAlias = tuple[str, ...]
TomlTable: TypeAlias = dict[str, object]

_HEADER = re.compile(r"\s*\[([\w.-]+)\]\s*(?:#.*)?$")
_ANY_HEADER = re.compile(r"\s*\[.*\]\s*(?:#.*)?$")
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


def _newline(content: str) -> str:
    return "\r\n" if "\r\n" in content else "\n"


def _cannot_rewrite(table: str, origin: Path) -> DeploymentPlanError:
    return DeploymentPlanError(
        f"Cannot rewrite [{table}] in {origin}. "
        f"Use a plain [{table}] table with single-line quoted values."
    )


def _header_indexes(lines: list[str], table: str) -> Iterator[int]:
    for index, line in enumerate(lines):
        header = _HEADER.fullmatch(line.rstrip("\r\n"))
        if header and header[1] == table:
            yield index


def _assignments(values: dict[str, str], newline: str) -> list[str]:
    return [
        f"{key} = {json.dumps(value, ensure_ascii=False)}{newline}"
        for key, value in values.items()
    ]


def _append_table(
    content: str, table: str, values: dict[str, str], expected: TomlTable, origin: Path
) -> str:
    newline = _newline(content)
    text = content
    if text and not text.endswith("\n"):
        text += newline
    if text and not text.endswith(newline * 2):
        text += newline
    result = text + "".join([f"[{table}]{newline}", *_assignments(values, newline)])
    if not _matches(result, {**expected, table: dict(values)}):
        raise _cannot_rewrite(table, origin)
    return result


def _insert_after_header(
    lines: list[str], table: str, values: dict[str, str], expected: TomlTable
) -> list[str] | None:
    newline = _newline("".join(lines))
    for index in _header_indexes(lines, table):
        header = lines[index]
        candidate = [
            *lines[:index],
            header if header.endswith("\n") else header + newline,
            *_assignments(values, newline),
            *lines[index + 1 :],
        ]
        if _matches("".join(candidate), expected):
            return candidate
    return None


def set_table_strings(
    content: str, table: str, values: dict[str, str], origin: Path
) -> str:
    """Set string keys of one plain table, appending the table when absent.
    Keys already present keep their line, comments and position."""
    expected = parse_layer(content, origin)
    current = expected.get(table)
    if current is None:
        return _append_table(content, table, values, expected, origin)
    if not isinstance(current, dict):
        raise _cannot_rewrite(table, origin)
    missing = {key: value for key, value in values.items() if key not in current}
    lines = content.splitlines(keepends=True)
    for key, value in values.items():
        if key not in missing and not _patch_scalar(
            lines, expected, (table, key), value
        ):
            raise _cannot_rewrite(table, origin)
    if missing:
        final = deepcopy(expected)
        table_at(final, (table,)).update(missing)
        inserted = _insert_after_header(lines, table, missing, final)
        if inserted is None:
            raise _cannot_rewrite(table, origin)
        lines = inserted
        expected = final
    result = "".join(lines)
    if not _matches(result, expected):
        raise _cannot_rewrite(table, origin)
    return result


def _drop_assignment(
    lines: list[str], table: str, key: str, expected: TomlTable
) -> list[str] | None:
    section = ""
    for index, line in enumerate(lines):
        body = line.rstrip("\r\n")
        if header := _HEADER.fullmatch(body):
            section = header[1]
        match = _STRING.match(body)
        if section == table and match and match["key"] == key:
            candidate = [*lines[:index], *lines[index + 1 :]]
            if _matches("".join(candidate), expected):
                return candidate
    return None


def remove_table_strings(
    content: str, table: str, keys: list[str], origin: Path
) -> str:
    """Delete single-line string keys of one plain table; other lines stay."""
    expected = parse_layer(content, origin)
    lines = content.splitlines(keepends=True)
    for key in keys:
        if key not in table_at(expected, (table,)):
            continue
        del table_at(expected, (table,))[key]
        remaining = _drop_assignment(lines, table, key, expected)
        if remaining is None:
            raise _cannot_rewrite(table, origin)
        lines = remaining
    return "".join(lines)


def _table_end(lines: list[str], start: int) -> int:
    for index in range(start + 1, len(lines)):
        if _ANY_HEADER.fullmatch(lines[index].rstrip("\r\n")):
            return index
    return len(lines)


def remove_table(content: str, table: str, origin: Path) -> str:
    """Delete one plain table with its body; everything else is kept as is."""
    expected = parse_layer(content, origin)
    if table not in expected:
        return content
    if not isinstance(expected[table], dict):
        raise _cannot_rewrite(table, origin)
    del expected[table]
    lines = content.splitlines(keepends=True)
    for start in _header_indexes(lines, table):
        end = _table_end(lines, start)
        before = lines[:start]
        if end == len(lines) and before and not before[-1].strip():
            before.pop()
        result = "".join([*before, *lines[end:]])
        if _matches(result, expected):
            return result
    raise _cannot_rewrite(table, origin)


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
