from pathlib import Path

from setup_tts_model import build_arg_parser, cache_model


def test_setup_tts_model_accepts_an_explicit_language_and_model():
    args = build_arg_parser().parse_args(["--language", "en", "--model", "v3_en"])

    assert args.language == "en"
    assert args.model == "v3_en"


def test_cache_model_forwards_selection_and_copies_the_manifest(tmp_path, monkeypatch):
    calls = []

    class _FakeSilero:
        @staticmethod
        def silero_tts(*, language, speaker):
            calls.append((language, speaker))
            Path("latest_silero_models.yml").write_text("manifest", encoding="utf-8")

    working_directory = tmp_path / "working"
    repo_root = tmp_path / "repo"
    working_directory.mkdir()
    repo_root.mkdir()
    monkeypatch.chdir(working_directory)

    cache_model(
        "en",
        "v3_en",
        silero_module=_FakeSilero,
        repo_root=repo_root,
    )

    assert calls == [("en", "v3_en")]
    assert (repo_root / "latest_silero_models.yml").read_text(
        encoding="utf-8"
    ) == "manifest"
