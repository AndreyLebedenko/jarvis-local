"""Validation rules for configuration iteration 2 selections."""

from jarvis.core.config import (
    PiperTtsSettings,
    SileroTtsSettings,
    TtsLanguageSettings,
    VadSettings,
)
from jarvis.ui.config_selection import (
    UiConfigSelection,
    validate_response_mode,
    validate_selection,
)


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
        min_chunk_seconds=31.0,
        padding_noise_rms=0.2,
        request_end_pause_seconds=100.0,
        resume_cooldown_seconds=-1.0,
    )
    selection = UiConfigSelection(model="m", microphone_device="", vad=bad)

    problems = validate_selection(selection)

    assert len(problems) == 6
    assert any("threshold" in p for p in problems)
    assert any("max_chunk_seconds" in p for p in problems)
    assert any("min_chunk_seconds" in p for p in problems)
    assert any("padding_noise_rms" in p for p in problems)
    assert any("request_end_pause_seconds" in p for p in problems)
    assert any("resume_cooldown_seconds" in p for p in problems)


def test_vad_boundary_values_are_accepted():
    boundary = VadSettings(
        threshold=0.01,
        max_chunk_seconds=120,
        min_chunk_seconds=30.0,
        padding_noise_rms=0.1,
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


# --- response mode (story-v1.9.0, task 2) --------------------------------


def test_every_supported_response_mode_is_accepted():
    for mode in ("text", "voice", "text_voice"):
        assert validate_response_mode(mode) == []


def test_unknown_response_mode_is_rejected_naming_the_three_values():
    problems = validate_response_mode("spoken")

    assert len(problems) == 1
    assert "text, voice, text_voice" in problems[0]
    assert "spoken" in problems[0]


# --- response_mode as a UiConfigSelection batch field (task 3b) -----------


def test_minimal_selection_omits_the_response_mode():
    selection = UiConfigSelection(model="m", microphone_device="")

    assert selection.response_mode is None
    assert validate_selection(selection) == []


def test_every_supported_response_mode_is_accepted_as_a_selection_field():
    for mode in ("text", "voice", "text_voice"):
        selection = UiConfigSelection(
            model="m", microphone_device="", response_mode=mode
        )

        assert validate_selection(selection) == []


def test_unknown_selection_response_mode_is_rejected_the_same_way():
    selection = UiConfigSelection(
        model="m", microphone_device="", response_mode="spoken"
    )

    problems = validate_selection(selection)

    assert problems == validate_response_mode("spoken")


def test_full_selection_with_a_response_mode_is_valid():
    selection = UiConfigSelection(
        model="m",
        microphone_device="USB",
        ui_language="ru",
        response_mode="text_voice",
        vad=VadSettings(),
        tts_routes=_routes(),
    )

    assert validate_selection(selection) == []
