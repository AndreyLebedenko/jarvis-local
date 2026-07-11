import io
from pathlib import Path
from types import SimpleNamespace

import pytest
import soundfile as sf

from manual.manual_check_bilingual_tts_routes import (
    DEFAULT_PIPER_EN_MODEL,
    PIPER,
    ROUTES,
    SAMPLES,
    SILERO,
    _piper_chunks_to_wav_bytes,
    build_arg_parser,
    build_segment_plan,
    engine_for_language,
    resolve_piper_config,
    resolve_required_model,
    route_labels,
    sample_labels,
    selected_routes,
    selected_samples,
    validate_piper_models_for_routes,
)


def test_route_catalog_covers_the_three_requested_variants():
    assert [(route.label, route.ru_engine, route.en_engine) for route in ROUTES] == [
        ("silero_ru_en", SILERO, SILERO),
        ("silero_ru_piper_en", SILERO, PIPER),
        ("piper_ru_en", PIPER, PIPER),
    ]


def test_sample_catalog_exercises_mixed_charset_text():
    assert sample_labels() == ("code_switch_short", "technical_terms", "sentence_mix")

    for sample in SAMPLES:
        languages = {
            plan.language for plan in build_segment_plan(ROUTES[0], sample.text)
        }

        assert languages == {"ru", "en"}


def test_build_segment_plan_assigns_engines_by_language():
    route = ROUTES[1]

    plan = build_segment_plan(route, "Проверь JSON.")

    assert [(segment.language, segment.engine_label) for segment in plan] == [
        ("ru", SILERO),
        ("en", PIPER),
    ]


def test_engine_for_language_defaults_non_english_to_russian_route():
    route = ROUTES[2]

    assert engine_for_language(route, "en") == PIPER
    assert engine_for_language(route, "ru") == PIPER


def test_selected_routes_and_samples_accept_all_or_one_label():
    assert selected_routes("all") == ROUTES
    assert selected_routes("piper_ru_en") == (ROUTES[2],)
    assert selected_samples("all") == SAMPLES
    assert selected_samples("technical_terms") == (SAMPLES[1],)


def test_resolve_piper_config_prefers_explicit_path(tmp_path):
    model_path = tmp_path / "voice.onnx"
    config_path = tmp_path / "voice.json"
    config_path.write_text("{}", encoding="utf-8")

    assert resolve_piper_config(model_path, str(config_path)) == config_path


def test_resolve_piper_config_uses_adjacent_json_when_present(tmp_path):
    model_path = tmp_path / "voice.onnx"
    config_path = tmp_path / "voice.onnx.json"
    config_path.write_text("{}", encoding="utf-8")

    assert resolve_piper_config(model_path, None) == config_path


def test_resolve_piper_config_rejects_missing_config(tmp_path):
    with pytest.raises(FileNotFoundError, match="No Piper config file"):
        resolve_piper_config(tmp_path / "voice.onnx", None)


def test_resolve_required_model_rejects_missing_path():
    with pytest.raises(FileNotFoundError, match="--piper-ru-model"):
        resolve_required_model(None, "ru")


def test_resolve_required_model_rejects_nonexistent_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="does not exist"):
        resolve_required_model(str(tmp_path / "missing.onnx"), "en")


def test_resolve_required_model_accepts_existing_file(tmp_path):
    model_path = tmp_path / "voice.onnx"
    model_path.write_bytes(b"model")

    assert resolve_required_model(str(model_path), "en") == model_path


def test_validate_piper_models_requires_only_models_used_by_selected_routes(tmp_path):
    en_model = tmp_path / "en.onnx"
    en_model.write_bytes(b"model")

    validate_piper_models_for_routes((ROUTES[1],), None, str(en_model))

    with pytest.raises(FileNotFoundError, match="--piper-ru-model"):
        validate_piper_models_for_routes((ROUTES[2],), None, str(en_model))


def test_arg_parser_exposes_route_sample_and_engine_paths():
    args = build_arg_parser().parse_args(
        [
            "--route",
            "silero_ru_piper_en",
            "--sample",
            "sentence_mix",
            "--piper-ru-model",
            r"D:\\voices\\ru.onnx",
            "--piper-en-model",
            r"D:\\voices\\en.onnx",
            "--use-cuda",
        ]
    )

    assert route_labels() == ("silero_ru_en", "silero_ru_piper_en", "piper_ru_en")
    assert args.route == "silero_ru_piper_en"
    assert args.sample == "sentence_mix"
    assert args.piper_ru_model == r"D:\\voices\\ru.onnx"
    assert args.piper_en_model == r"D:\\voices\\en.onnx"
    assert args.use_cuda is True


def test_arg_parser_defaults_to_all_routes_and_repo_local_english_piper_model():
    args = build_arg_parser().parse_args([])

    assert args.route == "all"
    assert args.sample == "all"
    assert Path(args.piper_en_model) == DEFAULT_PIPER_EN_MODEL


def test_piper_chunks_are_encoded_as_readable_wav_bytes():
    chunk = SimpleNamespace(
        sample_rate=22050,
        audio_int16_array=_Int16Bytes([0, 100, -100, 0]),
    )

    wav_bytes = _piper_chunks_to_wav_bytes([chunk])
    decoded, sample_rate = sf.read(io.BytesIO(wav_bytes), dtype="int16")

    assert sample_rate == 22050
    assert decoded.tolist() == [0, 100, -100, 0]


def test_piper_chunks_reject_empty_output():
    with pytest.raises(RuntimeError, match="no audio chunks"):
        _piper_chunks_to_wav_bytes([])


def test_piper_chunks_reject_mixed_sample_rates():
    chunks = [
        SimpleNamespace(sample_rate=22050, audio_int16_array=_Int16Bytes([0])),
        SimpleNamespace(sample_rate=16000, audio_int16_array=_Int16Bytes([0])),
    ]

    with pytest.raises(RuntimeError, match="mixed sample rates"):
        _piper_chunks_to_wav_bytes(chunks)


class _Int16Bytes:
    def __init__(self, values: list[int]) -> None:
        self._values = values

    def tobytes(self) -> bytes:
        return b"".join(
            value.to_bytes(2, "little", signed=True) for value in self._values
        )
