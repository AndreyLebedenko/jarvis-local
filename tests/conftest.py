import ast
import sys
from pathlib import Path

import pytest

from jarvis.core.single_instance import HeldInstance, MutexCreation

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def assert_stdlib_only_imports(module_filename: str) -> None:
    """Guards a module's "no project-module dependency" boundary.

    Used across task cards to enforce architectural invariants declared in
    PROJECT.md/task cards, e.g. bus.py and config.py must not import each
    other or any other project module.
    """
    source = (PROJECT_ROOT / module_filename).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_top_level_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_top_level_names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported_top_level_names.add(node.module.split(".")[0])

    non_stdlib = imported_top_level_names - set(sys.stdlib_module_names)
    assert not non_stdlib, f"{module_filename} imports non-stdlib modules: {non_stdlib}"


class NoWin32SingleInstanceGuard:
    """Stands in for the real guard: no Win32, never refuses, records calls."""

    def __init__(self) -> None:
        self.acquire_calls = 0
        self.closed_handles: list[int] = []

    def create(self, name: str) -> MutexCreation:
        return MutexCreation(handle=1, already_exists=False)

    def close(self, handle: int) -> None:
        self.closed_handles.append(handle)

    def acquire(self) -> HeldInstance:
        self.acquire_calls += 1
        return HeldInstance(self, 1)


def _message_box_must_never_appear(message: str) -> None:
    raise AssertionError(f"a real message box would have appeared: {message}")


@pytest.fixture(autouse=True)
def no_win32_single_instance_guard(monkeypatch: pytest.MonkeyPatch):
    # A Jarvis running on the dev machine would otherwise refuse main() in
    # the suite and pop a real modal box.
    guard = NoWin32SingleInstanceGuard()
    monkeypatch.setattr("jarvis.app.acquire_single_instance", guard.acquire)
    monkeypatch.setattr(
        "jarvis.app.show_already_running_message_box", _message_box_must_never_appear
    )
    return guard
