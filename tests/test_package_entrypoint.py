from pathlib import Path


def test_package_entrypoint_delegates_to_existing_main() -> None:
    entrypoint = Path("src/jarvis/__main__.py").read_text(encoding="utf-8")

    assert "from jarvis.app import main" in entrypoint
    assert "main()" in entrypoint
