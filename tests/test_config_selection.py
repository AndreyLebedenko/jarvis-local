"""Validation rules for configuration iteration 2 selections."""

from jarvis.core.config import (
    PiperTtsSettings,
    SileroTtsSettings,
    TtsLanguageSettings,
    VadSettings,
)
from jarvis.ui.config_selection import UiConfigSelection, validate_selection


def _routes(en_model: str = "C:/voices/en.onnx") -> dict[str, TtsLanguageSettings]:
    return {
        "ru": SileroTtsSettings(model="custom_ru", speaker="eugene"),
        "en": PiperTtsSettings(model=en_model, length_scale=1.2),
    }


def test_minimal_selection_is_valid():
    selection = UiConfigSelection(model="m", microphone_device="")

    assert validate_selection(selection) == []


def test_full_selection_is_valid():
    selection = UiConfigSelection(
        model="m",
        microphone_device="USB",
        ui_language="ru",
        vad=VadSettings(),
        tts_routes=_routes(),
    )

    assert validate_selection(selection) == []


def test_empty_model_is_rejected():
    assert validate_selection(UiConfigSelection(model="  ", microphone_device=""))


def test_unsupported_ui_language_is_rejected():
    selection = UiConfigSelection(model="m", microphone_device="", ui_language="de")

    problems = validate_selection(selection)

    assert len(problems) == 1
    assert "ui_language" in problems[0]


def test_each_vad_field_is_range_checked():
    bad = VadSettings(
        threshold=1.5,
        max_chunk_seconds=0,
        request_end_pause_seconds=100.0,
        resume_cooldown_seconds=-1.0,
    )
    selection = UiConfigSelection(model="m", microphone_device="", vad=bad)

    problems = validate_selection(selection)

    assert len(problems) == 4
    assert any("threshold" in p for p in problems)
    assert any("max_chunk_seconds" in p for p in problems)
    assert any("request_end_pause_seconds" in p for p in problems)
    assert any("resume_cooldown_seconds" in p for p in problems)


def test_vad_boundary_values_are_accepted():
    boundary = VadSettings(
        threshold=0.01,
        max_chunk_seconds=120,
        request_end_pause_seconds=0.1,
        resume_cooldown_seconds=0.0,
    )
    selection = UiConfigSelection(model="m", microphone_device="", vad=boundary)

    assert validate_selection(selection) == []


def test_partial_tts_route_coverage_is_rejected():
    selection = UiConfigSelection(
        model="m",
        microphone_device="",
        tts_routes={"ru": SileroTtsSettings()},
    )

    problems = validate_selection(selection)

    assert len(problems) == 1
    assert "cover exactly" in problems[0]


def test_arbitrary_non_empty_silero_model_is_accepted():
    selection = UiConfigSelection(model="m", microphone_device="", tts_routes=_routes())

    assert validate_selection(selection) == []


def test_piper_route_with_empty_model_path_is_rejected():
    selection = UiConfigSelection(
        model="m", microphone_device="", tts_routes=_routes(en_model="   ")
    )

    problems = validate_selection(selection)

    assert len(problems) == 1
    assert "[tts.languages.en].model" in problems[0]


def test_invalid_engine_specific_parameter_is_rejected():
    selection = UiConfigSelection(
        model="m",
        microphone_device="",
        tts_routes={
            "ru": SileroTtsSettings(sample_rate=0),
            "en": PiperTtsSettings(model="voice.onnx", speaker_id=-1),
        },
    )

    problems = validate_selection(selection)

    assert len(problems) == 2
    assert any("sample_rate" in problem for problem in problems)
    assert any("speaker_id" in problem for problem in problems)
