import ast
import sys
from pathlib import Path

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
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                imported_top_level_names.add(node.module.split(".")[0])

    non_stdlib = imported_top_level_names - set(sys.stdlib_module_names)
    assert not non_stdlib, f"{module_filename} imports non-stdlib modules: {non_stdlib}"
