from __future__ import annotations

import hashlib
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import plantuml


def distribution_for(tmp_path: Path, contents: bytes) -> plantuml.Distribution:
    return plantuml.Distribution(
        version="test",
        url="https://example.invalid/plantuml.jar",
        sha256=hashlib.sha256(contents).hexdigest(),
        jar_path=tmp_path / "plantuml.jar",
    )


def test_install_downloads_and_verifies_the_pinned_jar(monkeypatch, tmp_path):
    contents = b"verified PlantUML jar"
    distribution = distribution_for(tmp_path, contents)
    monkeypatch.setattr(
        plantuml,
        "urlopen",
        lambda _url, timeout: io.BytesIO(contents),
    )

    installed = plantuml.install(distribution)

    assert installed == distribution.jar_path
    assert installed.read_bytes() == contents
    assert not installed.with_suffix(".download").exists()


def test_install_removes_an_invalid_download(monkeypatch, tmp_path):
    distribution = distribution_for(tmp_path, b"expected")
    monkeypatch.setattr(
        plantuml,
        "urlopen",
        lambda _url, timeout: io.BytesIO(b"tampered"),
    )

    with pytest.raises(plantuml.PlantUmlToolError, match="SHA-256 mismatch"):
        plantuml.install(distribution)

    assert not distribution.jar_path.exists()
    assert not distribution.jar_path.with_suffix(".download").exists()


def test_require_jar_reports_the_install_command_when_cache_is_empty(tmp_path):
    distribution = distribution_for(tmp_path, b"expected")

    with pytest.raises(
        plantuml.PlantUmlToolError,
        match=r"python tools/plantuml.py install",
    ):
        plantuml.require_jar(distribution)


def test_require_jar_rejects_a_modified_cached_jar(tmp_path):
    distribution = distribution_for(tmp_path, b"expected")
    distribution.jar_path.write_bytes(b"modified")

    with pytest.raises(plantuml.PlantUmlToolError, match="SHA-256 mismatch"):
        plantuml.require_jar(distribution)


def test_check_uses_plantuml_syntax_only_mode(monkeypatch, tmp_path):
    distribution = distribution_for(tmp_path, b"jar")
    distribution.jar_path.write_bytes(b"jar")
    source = tmp_path / "diagram.puml"
    source.write_text("@startuml\n@enduml\n", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_run(command, *, check):
        commands.append(command)
        assert check is False
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(
        plantuml.shutil,
        "which",
        lambda name: r"C:\Java\bin\java.exe" if name == "java" else None,
    )
    monkeypatch.setattr(plantuml.subprocess, "run", fake_run)

    result = plantuml.check_syntax((source,), distribution)

    assert result == 0
    assert commands == [
        [
            r"C:\Java\bin\java.exe",
            "-jar",
            str(distribution.jar_path),
            "-stdrpt:1",
            "--check-syntax",
            str(source),
        ]
    ]


def test_render_creates_the_output_directory_and_requests_svg(monkeypatch, tmp_path):
    distribution = distribution_for(tmp_path, b"jar")
    distribution.jar_path.write_bytes(b"jar")
    source = tmp_path / "diagram.puml"
    source.write_text("@startuml\n@enduml\n", encoding="utf-8")
    output_dir = tmp_path / "rendered"
    commands: list[list[str]] = []

    def fake_run(command, *, check):
        commands.append(command)
        assert check is False
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(
        plantuml.shutil,
        "which",
        lambda name: r"C:\Java\bin\java.exe" if name == "java" else None,
    )
    monkeypatch.setattr(plantuml.subprocess, "run", fake_run)

    result = plantuml.render((source,), output_dir, "svg", distribution)

    assert result == 0
    assert output_dir.is_dir()
    assert commands == [
        [
            r"C:\Java\bin\java.exe",
            "-jar",
            str(distribution.jar_path),
            "--format",
            "svg",
            "--output-dir",
            str(output_dir.resolve()),
            str(source),
        ]
    ]


def test_missing_java_has_an_actionable_error(monkeypatch, tmp_path):
    distribution = distribution_for(tmp_path, b"jar")
    distribution.jar_path.write_bytes(b"jar")
    source = tmp_path / "diagram.puml"

    monkeypatch.setattr(plantuml.shutil, "which", lambda _name: None)

    with pytest.raises(plantuml.PlantUmlToolError, match="Java is unavailable"):
        plantuml.check_syntax((source,), distribution)


def test_jenv_batch_launcher_runs_through_cmd_with_windows_quoting(
    monkeypatch, tmp_path
):
    distribution = distribution_for(tmp_path, b"jar")
    distribution.jar_path.write_bytes(b"jar")
    source = tmp_path / "diagram with spaces.puml"
    commands: list[list[str]] = []

    def fake_which(name):
        if name == "java":
            return r"D:\Development\JEnv-for-Windows\java.BAT"
        return None

    def fake_run(command, *, check):
        commands.append(command)
        assert check is False
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(plantuml.shutil, "which", fake_which)
    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")
    monkeypatch.setattr(plantuml.subprocess, "run", fake_run)

    result = plantuml.check_syntax((source,), distribution)

    expected_batch_command = plantuml.subprocess.list2cmdline(
        [
            r"D:\Development\JEnv-for-Windows\java.BAT",
            "-jar",
            str(distribution.jar_path),
            "-stdrpt:1",
            "--check-syntax",
            str(source),
        ]
    )
    assert result == 0
    assert commands == [
        [
            r"C:\Windows\System32\cmd.exe",
            "/d",
            "/s",
            "/c",
            expected_batch_command,
        ]
    ]


def test_batch_launcher_requires_windows_command_interpreter(monkeypatch, tmp_path):
    distribution = distribution_for(tmp_path, b"jar")
    distribution.jar_path.write_bytes(b"jar")
    source = tmp_path / "diagram.puml"
    monkeypatch.setattr(
        plantuml.shutil,
        "which",
        lambda name: r"D:\JEnv\java.bat" if name == "java" else None,
    )
    monkeypatch.delenv("COMSPEC", raising=False)

    with pytest.raises(
        plantuml.PlantUmlToolError,
        match="Windows command interpreter is unavailable",
    ):
        plantuml.check_syntax((source,), distribution)
