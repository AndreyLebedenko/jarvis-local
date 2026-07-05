from pathlib import Path

import pytest

from config import (
    BackendSettings,
    ClipboardSettings,
    ConfigError,
    HotkeySettings,
    Settings,
    load_settings,
)
from conftest import assert_stdlib_only_imports

EXAMPLE_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.example.toml"


def test_example_config_round_trips_without_error():
    settings = load_settings(EXAMPLE_CONFIG_PATH)

    assert isinstance(settings, Settings)


def test_example_config_matches_documented_defaults():
    settings = load_settings(EXAMPLE_CONFIG_PATH)

    assert settings == Settings()


def test_valid_config_file_parses_expected_values(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [backend]
        model = "custom-model"

        [vad]
        max_chunk_seconds = 15
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.backend.model == "custom-model"
    assert settings.vad.max_chunk_seconds == 15


def test_partial_section_fills_missing_keys_from_defaults(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [backend]
        model = "custom-model"
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.backend.model == "custom-model"
    assert settings.backend.endpoint == BackendSettings().endpoint
    assert settings.backend.num_ctx == BackendSettings().num_ctx


def test_missing_file_falls_back_to_defaults(tmp_path):
    settings = load_settings(tmp_path / "does-not-exist.toml")

    assert settings == Settings()


def test_malformed_toml_raises_config_error(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text("this is not [ valid toml", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_settings(config_path)


def test_wrong_type_value_raises_config_error(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [backend]
        num_ctx = "not-a-number"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        load_settings(config_path)


def test_unknown_top_level_section_raises_config_error(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [bogus_section]
        key = "value"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        load_settings(config_path)


def test_unknown_key_within_known_section_raises_config_error(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [backend]
        typo_field = "oops"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        load_settings(config_path)


def test_config_has_no_project_import_dependencies():
    assert_stdlib_only_imports("config.py")


# --- task-08: ClipboardSettings and new sound cue fields --------------------


def test_clipboard_max_chars_parses_from_config(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [clipboard]
        max_chars = 500
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.clipboard.max_chars == 500


def test_clipboard_max_chars_defaults_when_section_omitted(tmp_path):
    settings = load_settings(tmp_path / "does-not-exist.toml")

    assert settings.clipboard == ClipboardSettings()


def test_clipboard_max_chars_wrong_type_raises_config_error(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [clipboard]
        max_chars = "not-a-number"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        load_settings(config_path)


def test_sound_cues_clipboard_and_input_error_fields_parse(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [sound_cues]
        clipboard = "sounds/custom_clipboard.wav"
        input_error = "sounds/custom_input_error.wav"
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.sound_cues.clipboard == "sounds/custom_clipboard.wav"
    assert settings.sound_cues.input_error == "sounds/custom_input_error.wav"


# --- task-09: mic_sleep_toggle hotkey and new sound cue fields ---------------


def test_hotkeys_mic_sleep_toggle_parses_from_config(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [hotkeys]
        mic_sleep_toggle = "ctrl+alt+p"
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.hotkeys.mic_sleep_toggle == "ctrl+alt+p"


def test_hotkeys_mic_sleep_toggle_defaults_when_section_omitted(tmp_path):
    settings = load_settings(tmp_path / "does-not-exist.toml")

    assert settings.hotkeys == HotkeySettings()


def test_sound_cues_mic_sleep_and_mic_wake_fields_parse(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [sound_cues]
        mic_sleep = "sounds/custom_mic_sleep.wav"
        mic_wake = "sounds/custom_mic_wake.wav"
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.sound_cues.mic_sleep == "sounds/custom_mic_sleep.wav"
    assert settings.sound_cues.mic_wake == "sounds/custom_mic_wake.wav"
