from __future__ import annotations

import json
from pathlib import Path

import pytest
from brand_deployment_support import FakeRenderer, put

from jarvis.core.config import load_brand
from tools import deployment
from tools.deployment_rebrand import REBRAND_PREFIX, RECOVERY_COMMAND, rebrand_home

BRAND_ENVIRONMENT = "JARVIS_DEPLOY_BRAND"


@pytest.fixture
def home(tmp_path: Path) -> Path:
    root = tmp_path / "home"
    put(root / "config.toml", '[brand]\nname = "Work"\n')
    put(root / "src/jarvis/core/brand.py", "# marker")
    return root


@pytest.fixture(autouse=True)
def fake_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    def rebrand(home: Path, request):  # type: ignore[no-untyped-def]
        return rebrand_home(home, request, renderer=FakeRenderer())

    monkeypatch.setattr(deployment, "rebrand_home", rebrand)


def answer(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    lines = [
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith(REBRAND_PREFIX)
    ]
    assert len(lines) == 1
    return json.loads(lines[0].removeprefix(REBRAND_PREFIX))


def run(source: Path, home: Path, *flags: str) -> int:
    return deployment.main(["--source", str(source), "--target", str(home), *flags])


def test_a_rebrand_prints_the_resolved_brand_and_the_written_files(
    home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(BRAND_ENVIRONMENT, '{"name": "Lab"}')

    code = run(tmp_path, home, "--rebrand")

    result = answer(capsys)
    assert code == 0
    assert result["ok"] is True
    assert result["files"] == ["config.toml", "brand/brand.png", "brand/brand.ico"]
    assert result["brand"]["name"] == "Lab"  # type: ignore[index]
    assert load_brand(home / "config.toml").name == "Lab"


def test_a_rejected_request_is_an_answer_with_exit_code_zero(
    home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(BRAND_ENVIRONMENT, '{"accent": "red"}')

    code = run(tmp_path, home, "--rebrand")

    result = answer(capsys)
    assert code == 0
    assert result["ok"] is False
    assert "[brand].accent" in str(result["message"])
    assert load_brand(home / "config.toml").accent != "red"


def test_an_unreadable_request_is_an_answer_too(
    home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(BRAND_ENVIRONMENT, "{not json")

    code = run(tmp_path, home, "--rebrand")

    assert code == 0
    assert answer(capsys)["ok"] is False


def test_no_request_at_all_says_there_is_nothing_to_change(
    home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(BRAND_ENVIRONMENT, raising=False)

    code = run(tmp_path, home, "--rebrand")

    assert code == 0
    assert "Nothing to change" in str(answer(capsys)["message"])


def test_a_half_applied_rebrand_is_an_error_naming_the_recovery_command(
    home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(BRAND_ENVIRONMENT, '{"name": "Lab"}')
    (home / "brand" / "brand.png").mkdir(parents=True)

    code = run(tmp_path, home, "--rebrand")

    captured = capsys.readouterr()
    assert code == 1
    assert RECOVERY_COMMAND in captured.err
    assert REBRAND_PREFIX not in captured.out


def test_the_target_is_required(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        deployment.main(["--source", str(tmp_path), "--rebrand"])

    assert "--target" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--resume", "--yes", "--preview", "--brand-check"])
def test_rebrand_cannot_be_combined_with_the_deployment_flags(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], flag: str
) -> None:
    with pytest.raises(SystemExit):
        run(tmp_path, home, "--rebrand", flag)

    assert "--rebrand cannot be combined" in capsys.readouterr().err


def test_a_brand_check_with_a_target_checks_that_home_and_changes_nothing(
    home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(BRAND_ENVIRONMENT, '{"name": "Lab"}')

    code = run(tmp_path, home, "--brand-check")

    line = capsys.readouterr().out.strip()
    result = json.loads(line.removeprefix("JARVIS_DEPLOY_BRAND_CHECK:"))
    assert code == 0
    assert result["ok"] is True
    assert result["brand"]["name"] == "Lab"
    assert load_brand(home / "config.toml").name == "Work"
