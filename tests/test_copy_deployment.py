from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from jarvis.core.config import PiperTtsSettings, load_settings
from jarvis.core.single_instance import HeldInstance, acquire_single_instance
from tools import deployment, deployment_snapshot
from tools.deployment_plan import (
    APPLICATION_FILES,
    PACKAGE_DIR,
    DeploymentMode,
    DeploymentPlanError,
)
from tools.deployment_toml import patch_paths


@pytest.fixture
def home(tmp_path: Path) -> Path:
    home = tmp_path / "source"
    for name in (*APPLICATION_FILES, PACKAGE_DIR / "__init__.py"):
        path = home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    return home


@pytest.fixture(autouse=True)
def runtime_mutex(monkeypatch: pytest.MonkeyPatch) -> str:
    name = f"Local\\Jarvis.CopyTest.{uuid4().hex}"
    monkeypatch.setattr(deployment, "MUTEX_NAME", name)
    return name


def put(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def absolute(path: Path) -> str:
    return json.dumps(str(path), ensure_ascii=False)


def test_patch_preserves_layout_comments_and_ignores_table_text_in_multiline_prompt():
    source = (
        '[prompts]\r\nsystem = """\r\n[journal]\r\nroot = "old"\r\n"""\r\n'
        "# Preserve this comment\r\n[journal] # and this\r\n  root = 'old'  # keep\r\n"
    )
    result = patch_paths(source, {("journal", "root"): "journal"}, Path("base.toml"))

    assert result == source.replace("'old'", '"journal"')


@pytest.mark.parametrize(
    "source",
    [
        'journal = {root = "outside"}',
        'journal.root = "outside"',
        '"journal".root = "outside"',
        '[journal]\nroot = """outside"""',
        '["journal"]\nroot = "outside"',
        'journal.root = "journal"',
    ],
)
def test_patch_rejects_unsupported_forms_with_key_even_for_default_paths(
    source: str,
) -> None:
    with pytest.raises(DeploymentPlanError, match=r"\[journal\]\.root.*config\.toml"):
        patch_paths(source, {("journal", "root"): "journal"}, Path("config.toml"))


def test_copy_preserves_state_rebases_both_layers_and_isolates_writes(
    home: Path, tmp_path: Path, runtime_mutex: str
) -> None:
    source_journal = tmp_path / "external-journal"
    session = "20261124-103000-aabbcc"
    events = source_journal / session / "events.jsonl"
    put(events, b'{"text":"source history"}\n')
    put(source_journal / session / "image.png", b"image bytes")
    put(source_journal / "transcript_overlays.db", b"overlay bytes")
    put(home / "memory" / "memory.md", b"source memory")
    put(home / "memory" / "memory.md.bak", b"backup")
    put(home / "logs" / "jarvis.log", b"log")
    put(home / "mcp_mode.token", b"source token")
    base = (
        f"# My config\r\n[journal]\r\nroot = {absolute(home / 'old')} # fallback\r\n"
        '[ui]\r\nlanguage = "en"\r\n'
    ).encode()
    ui = f"[journal]\nroot = {absolute(source_journal)}\n".encode()
    put(home / "config.toml", base)
    put(home / "config.ui.toml", ui)
    destination = tmp_path / "new"

    def install(target: Path, assume_yes: bool) -> int:
        assert (
            target / "journal" / session / "events.jsonl"
        ).read_bytes() == events.read_bytes()
        assert (
            target / "journal" / session / "image.png"
        ).read_bytes() == b"image bytes"
        assert (
            target / "journal" / "transcript_overlays.db"
        ).read_bytes() == b"overlay bytes"
        assert (target / "memory" / "memory.md.bak").read_bytes() == b"backup"
        assert not (target / "logs").exists()
        assert not (target / "mcp_mode.token").exists()
        assert (target / "config.toml").read_bytes() == base.replace(
            absolute(home / "old").encode(), b'"journal"'
        )
        assert load_settings(target / "config.toml").journal.root == "journal"
        (target / "config.ui.toml").write_text(
            "[ui]\nlanguage = 'ru'\n", encoding="utf-8"
        )
        assert load_settings(target / "config.toml").journal.root == "journal"
        put(target / "journal" / session / "events.jsonl", b"changed")
        put(target / "memory" / "memory.md", b"changed")
        guard = acquire_single_instance(name=runtime_mutex)
        assert isinstance(guard, HeldInstance)
        guard.release()
        return 0

    assert (
        deployment.deploy(
            home, destination, mode=DeploymentMode.COPY, installer=install
        )
        == 0
    )
    assert events.read_bytes() == b'{"text":"source history"}\n'
    assert (home / "memory" / "memory.md").read_bytes() == b"source memory"
    assert (home / "config.toml").read_bytes() == base
    assert (home / "config.ui.toml").read_bytes() == ui
    assert manifest(destination) == ("copy", "complete")


def test_copy_relocates_prompts_proxy_cues_and_piper_in_both_layers(
    home: Path, tmp_path: Path
) -> None:
    files = tmp_path / "local-files"
    put(files / "topics.txt", b"topics")
    put(files / "voice.onnx", b"model")
    put(files / "voice.onnx.json", b"configuration")
    put(files / "espeak" / "rules", b"rules")
    put(files / "cue.wav", b"sound")
    put(home / "downloads" / "source-only.txt", b"keep it in the source")
    put(home / "personal_proxy_public_names.txt", b"names")
    put(home / ".jarvis" / "question.txt", b"Use this prompt.")
    base = (
        '[prompts]\nvoice_turn_instruction = "@question.txt"\n'
        f"[personal_proxy]\ntopics_file = {absolute(files / 'topics.txt')}\n"
        f"[sound_cues]\nlistening = {absolute(files / 'cue.wav')}\n"
        '[tts.languages.en]\nengine = "piper"\n'
        f"model = {absolute(files / 'voice.onnx')}\n"
        f"espeak_data_dir = {absolute(files / 'espeak')}\n"
        f"download_dir = {absolute(home / 'downloads')}\n"
    )
    put(home / "config.toml", base.encode())
    put(
        home / "config.ui.toml",
        f"[tts.languages.en]\ndownload_dir = {absolute(files)}\n".encode(),
    )
    target = tmp_path / "new"

    assert (
        deployment.deploy(
            home, target, mode=DeploymentMode.COPY, installer=lambda *_: 0
        )
        == 0
    )
    settings = load_settings(target / "config.toml")
    model = settings.tts.languages["en"]
    assert isinstance(model, PiperTtsSettings)
    assert (target / model.model).read_bytes() == b"model"
    assert (target / f"{model.model}.json").read_bytes() == b"configuration"
    assert model.espeak_data_dir is not None
    assert (target / model.espeak_data_dir / "rules").read_bytes() == b"rules"
    assert model.download_dir is not None
    assert not Path(model.download_dir).is_absolute()
    assert list((target / model.download_dir).iterdir()) == []
    base_settings = load_settings(target / "config.toml", target / "absent.toml")
    base_model = base_settings.tts.languages["en"]
    assert isinstance(base_model, PiperTtsSettings)
    assert base_model.download_dir is not None
    assert not Path(base_model.download_dir).is_absolute()
    assert list((target / base_model.download_dir).iterdir()) == []
    assert (target / settings.personal_proxy.topics_file).read_bytes() == b"topics"
    assert (target / settings.personal_proxy.public_names_file).read_bytes() == b"names"
    assert (target / settings.sound_cues.listening).read_bytes() == b"sound"
    assert settings.prompts.voice_turn_instruction == "Use this prompt."
    assert (home / "config.toml").read_bytes() == base.encode()


def test_copy_keeps_silero_model_names_in_inherited_routes(home: Path, tmp_path: Path):
    base = b'[tts.languages.ru]\nmodel = "source_model"\n'
    ui = b'[tts.languages.ru]\nmodel = "selected_model"\n'
    put(home / "config.toml", base)
    put(home / "config.ui.toml", ui)
    target = tmp_path / "new"

    assert (
        deployment.deploy(
            home, target, mode=DeploymentMode.COPY, installer=lambda *_: 0
        )
        == 0
    )

    assert (target / "config.toml").read_bytes() == base
    assert (target / "config.ui.toml").read_bytes() == ui


def test_copy_preserves_a_missing_local_proxy_file_setting(home: Path, tmp_path: Path):
    base = b'[personal_proxy]\npublic_names_file = "public_names.txt" # local\n'
    put(home / "config.toml", base)
    target = tmp_path / "new"

    assert (
        deployment.deploy(
            home, target, mode=DeploymentMode.COPY, installer=lambda *_: 0
        )
        == 0
    )
    assert (target / "config.toml").read_bytes() == base
    assert not (target / "public_names.txt").exists()


def test_copy_rejects_a_missing_external_proxy_file(home: Path, tmp_path: Path):
    missing = absolute(tmp_path / "missing.txt")
    put(home / "config.toml", f"[personal_proxy]\ntopics_file = {missing}\n".encode())

    with pytest.raises(DeploymentPlanError, match=r"\[personal_proxy\]\.topics_file"):
        deployment.deploy(home, tmp_path / "new", mode=DeploymentMode.COPY)


@pytest.mark.parametrize("external", [False, True])
def test_copy_shares_one_piper_model_across_both_layers(
    home: Path, tmp_path: Path, external: bool
):
    local = Path(".local-models/piper/test.onnx")
    original = tmp_path / "test.onnx" if external else home / local
    put(original, b"model")
    put(original.with_suffix(".onnx.json"), b"sidecar")
    value = absolute(original if external else local)
    layer = f'[tts.languages.en]\nengine = "piper"\nmodel = {value}\n'.encode()
    put(home / "config.toml", layer)
    put(home / "config.ui.toml", layer)
    target = tmp_path / "new"

    assert (
        deployment.deploy(
            home, target, mode=DeploymentMode.COPY, installer=lambda *_: 0
        )
        == 0
    )

    paths = list(target.rglob("*.onnx"))
    assert len(paths) == 1
    assert paths[0].read_bytes() == b"model"
    assert paths[0].with_suffix(".onnx.json").read_bytes() == b"sidecar"
    assert (target / "config.ui.toml").read_bytes() == (
        target / "config.toml"
    ).read_bytes()
    if not external:
        assert paths == [target / local]
        assert (target / "config.toml").read_bytes() == layer


def test_installer_creates_the_default_config_when_source_has_no_base(
    home: Path, tmp_path: Path
):
    example = b'# Config comments\n[journal]\nroot = "journal"\n'
    put(home / "config.example.toml", example)
    target = tmp_path / "new"

    def install(destination: Path, assume_yes: bool) -> int:
        assert not (destination / "config.toml").exists()
        put(
            destination / "config.toml",
            (destination / "config.example.toml").read_bytes(),
        )
        return 0

    assert (
        deployment.deploy(home, target, mode=DeploymentMode.COPY, installer=install)
        == 0
    )
    assert (target / "config.toml").read_bytes() == example


def test_missing_base_checks_example_paths_before_install(home: Path, tmp_path: Path):
    original = absolute(home / "journal")
    put(home / "config.example.toml", f"[journal]\nroot = {original}\n".encode())

    with pytest.raises(
        DeploymentPlanError, match=r"\[journal\]\.root resolves outside"
    ):
        deployment.deploy(home, tmp_path / "new", mode=DeploymentMode.COPY)


def test_copy_refuses_running_runtime_and_enabled_mcp(
    home: Path, tmp_path: Path, runtime_mutex: str
) -> None:
    target = tmp_path / "new"
    guard = acquire_single_instance(name=runtime_mutex)
    assert isinstance(guard, HeldInstance)
    try:
        with pytest.raises(
            deployment.DeploymentError, match="Close the running Jarvis"
        ):
            deployment.deploy(home, target, mode=DeploymentMode.COPY)
    finally:
        guard.release()
    assert not target.exists()
    put(
        home / "config.toml",
        b'[mcp]\nenabled = true\n[mcp.servers.test]\ncommand = "test"\n',
    )
    with pytest.raises(DeploymentPlanError, match=r"\[mcp.servers.test\]"):
        deployment.deploy(home, target, mode=DeploymentMode.COPY)
    assert not target.exists()


def test_copy_interruption_never_marks_snapshot_ready(
    home: Path, tmp_path: Path, monkeypatch
):
    target = tmp_path / "new"
    put(home / "journal" / "events.jsonl", b"history")

    def interrupt(source: Path, destination: Path) -> None:
        raise OSError("simulated interruption")

    monkeypatch.setattr(deployment_snapshot, "_copy_tree", interrupt)
    with pytest.raises(deployment.DeploymentError, match="simulated interruption"):
        deployment.deploy(home, target, mode=DeploymentMode.COPY)
    assert manifest(target) == ("copy", "preparing")
    with pytest.raises(deployment.DeploymentError, match="preparation is incomplete"):
        deployment.deploy(home, target, mode=DeploymentMode.COPY, resume=True)


def test_resume_rejects_external_base_path_even_if_ui_overrides_it(
    home: Path, tmp_path: Path
):
    target = tmp_path / "new"
    assert (
        deployment.deploy(
            home, target, mode=DeploymentMode.COPY, installer=lambda *_: 7
        )
        == 7
    )
    put(
        target / "config.toml",
        f"[journal]\nroot = {absolute(home / 'journal')}\n".encode(),
    )
    put(target / "config.ui.toml", b'[journal]\nroot = "journal"\n')
    with pytest.raises(
        DeploymentPlanError, match=r"\[journal\]\.root resolves outside"
    ):
        deployment.deploy(home, target, mode=DeploymentMode.COPY, resume=True)
    assert manifest(target) == ("copy", "ready")
    with pytest.raises(deployment.DeploymentError, match="target or mode"):
        deployment.deploy(home, target, mode=DeploymentMode.CLEAN, resume=True)
    put(target / "config.toml", b"")
    assert (
        deployment.deploy(
            tmp_path / "gone",
            target,
            mode=DeploymentMode.COPY,
            resume=True,
            installer=lambda *_: 0,
        )
        == 0
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows junction")
def test_copy_accepts_root_junction_but_rejects_nested_junction(
    home: Path, tmp_path: Path
):
    external = tmp_path / "external"
    put(external / "events.jsonl", b"history")
    junction(home / "journal", external)
    target = tmp_path / "first"
    assert (
        deployment.deploy(
            home, target, mode=DeploymentMode.COPY, installer=lambda *_: 0
        )
        == 0
    )
    assert (target / "journal" / "events.jsonl").read_bytes() == b"history"
    junction(external / "nested", home)
    target = tmp_path / "second"
    with pytest.raises(DeploymentPlanError, match="nested linked path"):
        deployment.deploy(home, target, mode=DeploymentMode.COPY)
    assert manifest(target) == ("copy", "preparing")


def test_invalid_patch_keeps_preparing_and_skips_install(
    home: Path, tmp_path: Path
) -> None:
    target = tmp_path / "new"
    put(home / "config.toml", b'journal = {root = "journal"}')

    with pytest.raises(DeploymentPlanError, match=r"Cannot rebase \[journal\]\.root"):
        deployment.deploy(home, target, mode=DeploymentMode.COPY)

    assert manifest(target) == ("copy", "preparing")


@pytest.mark.skipif(os.name != "nt", reason="Windows junction")
def test_resume_rejects_a_link_added_inside_the_copied_journal(
    home: Path, tmp_path: Path
) -> None:
    put(home / "journal" / "events.jsonl", b"history")
    target = tmp_path / "new"
    assert (
        deployment.deploy(
            home, target, mode=DeploymentMode.COPY, installer=lambda *_: 7
        )
        == 7
    )
    junction(target / "journal" / "linked", home / "journal")

    with pytest.raises(DeploymentPlanError, match="nested linked path"):
        deployment.deploy(home, target, mode=DeploymentMode.COPY, resume=True)


def junction(path: Path, target: Path) -> None:
    subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(path), str(target)],
        check=True,
        capture_output=True,
    )


def manifest(path: Path) -> tuple[str, str]:
    data = json.loads((path / deployment.MANIFEST).read_bytes())
    return data["mode"], data["phase"]
