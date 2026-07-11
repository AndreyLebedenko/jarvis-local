import pytest

from manual.manual_check_piper import (
    DEFAULT_MODEL_PATH,
    PROMPTS,
    build_arg_parser,
    resolve_config_path,
    resolve_model_path,
)


def test_piper_prompt_catalog_reuses_the_shared_spike_prompts():
    labels = [prompt.label for prompt in PROMPTS]

    assert labels == [
        "russian",
        "english",
        "mixed_latin",
        "numbers",
        "short_answer",
        "code_like",
    ]


def test_resolve_config_path_prefers_an_explicit_config(tmp_path):
    model_path = tmp_path / "voice.onnx"
    config_path = tmp_path / "voice.json"
    config_path.write_text("{}", encoding="utf-8")

    resolved = resolve_config_path(model_path, str(config_path))

    assert resolved == config_path


def test_resolve_config_path_uses_the_adjacent_default_json(tmp_path):
    model_path = tmp_path / "voice.onnx"
    derived = tmp_path / "voice.onnx.json"
    derived.write_text("{}", encoding="utf-8")

    resolved = resolve_config_path(model_path, None)

    assert resolved == derived


def test_resolve_config_path_raises_when_no_config_exists(tmp_path):
    model_path = tmp_path / "voice.onnx"

    with pytest.raises(FileNotFoundError):
        resolve_config_path(model_path, None)


def test_resolve_model_path_uses_the_repo_local_default_when_present(
    monkeypatch, tmp_path
):
    default_model = tmp_path / DEFAULT_MODEL_PATH
    default_model.parent.mkdir(parents=True)
    default_model.write_bytes(b"model")
    monkeypatch.chdir(tmp_path)

    resolved = resolve_model_path(None)

    assert resolved == DEFAULT_MODEL_PATH


def test_resolve_model_path_uses_an_explicit_model_path(tmp_path):
    model_path = tmp_path / "voice.onnx"
    model_path.write_bytes(b"model")

    resolved = resolve_model_path(str(model_path))

    assert resolved == model_path


def test_resolve_model_path_raises_when_default_is_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError):
        resolve_model_path(None)


def test_arg_parser_accepts_model_config_and_cuda_flag():
    args = build_arg_parser().parse_args(
        [
            "--model",
            r"D:\\voices\\en_US-lessac-medium.onnx",
            "--config",
            r"D:\\voices\\en_US-lessac-medium.onnx.json",
            "--use-cuda",
        ]
    )

    assert args.model == r"D:\\voices\\en_US-lessac-medium.onnx"
    assert args.config == r"D:\\voices\\en_US-lessac-medium.onnx.json"
    assert args.use_cuda is True
