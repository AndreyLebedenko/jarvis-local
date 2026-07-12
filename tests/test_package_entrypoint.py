from pathlib import Path


def test_package_entrypoint_delegates_to_existing_main() -> None:
    entrypoint = Path("src/jarvis/__main__.py").read_text(encoding="utf-8")

    assert "from jarvis.app import main" in entrypoint
    assert "main()" in entrypoint


def test_manual_modules_use_package_imports_without_sys_path_workarounds() -> None:
    manual_files = Path("manual").glob("*.py")
    contents = [path.read_text(encoding="utf-8") for path in manual_files]

    assert all("sys.path" not in content for content in contents)
    assert all("python manual/" not in content for content in contents)
