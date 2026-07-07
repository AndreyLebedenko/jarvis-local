from pathlib import Path

import pytest

from config import (
    BackendSettings,
    ClipboardSettings,
    ConfigError,
    HotkeySettings,
    MicrophoneSettings,
    Settings,
    VadSettings,
    load_settings,
    write_ui_config,
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


# --- task-10: clipboard_submit hotkey ----------------------------------------


def test_hotkeys_clipboard_submit_parses_from_config(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [hotkeys]
        clipboard_submit = "ctrl+alt+c"
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.hotkeys.clipboard_submit == "ctrl+alt+c"


def test_hotkeys_clipboard_submit_defaults_when_section_omitted(tmp_path):
    settings = load_settings(tmp_path / "does-not-exist.toml")

    assert settings.hotkeys == HotkeySettings()


# --- task-12: thinking_toggle hotkey and thinking_on/thinking_off cues ------


def test_hotkeys_thinking_toggle_parses_from_config(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [hotkeys]
        thinking_toggle = "ctrl+alt+k"
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.hotkeys.thinking_toggle == "ctrl+alt+k"


def test_hotkeys_thinking_toggle_defaults_when_section_omitted(tmp_path):
    settings = load_settings(tmp_path / "does-not-exist.toml")

    assert settings.hotkeys == HotkeySettings()
    assert settings.hotkeys.thinking_toggle == "ctrl+alt+t"


def test_sound_cues_thinking_on_and_thinking_off_fields_parse(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [sound_cues]
        thinking_on = "sounds/custom_thinking_on.wav"
        thinking_off = "sounds/custom_thinking_off.wav"
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.sound_cues.thinking_on == "sounds/custom_thinking_on.wav"
    assert settings.sound_cues.thinking_off == "sounds/custom_thinking_off.wav"


def test_sound_cues_thinking_on_and_thinking_off_default_when_section_omitted(tmp_path):
    settings = load_settings(tmp_path / "does-not-exist.toml")

    assert settings.sound_cues.thinking_on == "sounds/thinking_on.wav"
    assert settings.sound_cues.thinking_off == "sounds/thinking_off.wav"


# --- story-v1.2.4-task-2: config layering (defaults < config.toml <
# config.ui.toml) ------------------------------------------------------------


def test_missing_ui_config_file_is_compatible_with_existing_behavior(tmp_path):
    """AC: 'Existing config behavior remains compatible when config.ui.toml
    is absent.' Every other test in this file already calls load_settings()
    with only a base path, relying on the default ui_path
    (config.ui.toml) not existing next to an arbitrary tmp_path file - this
    test makes that assumption explicit and pins it down with a real
    config.toml override present, not just all-defaults."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [backend]
        model = "custom-model"
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path, ui_path=tmp_path / "does-not-exist-ui.toml")

    assert settings.backend.model == "custom-model"
    assert settings == load_settings(config_path)


def test_ui_config_overrides_base_config_for_the_same_key(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [backend]
        model = "from-base-config"
        """,
        encoding="utf-8",
    )
    ui_config_path = tmp_path / "config.ui.toml"
    ui_config_path.write_text(
        """
        [backend]
        model = "from-ui-config"
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path, ui_path=ui_config_path)

    assert settings.backend.model == "from-ui-config"


def test_ui_config_precedence_is_per_key_not_per_file(tmp_path):
    """A key set in config.toml but left out of config.ui.toml must still
    apply - config.ui.toml overriding one key in a section must not reset
    the rest of that section back to built-in defaults."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [backend]
        model = "from-base-config"
        num_ctx = 1234
        """,
        encoding="utf-8",
    )
    ui_config_path = tmp_path / "config.ui.toml"
    ui_config_path.write_text(
        """
        [backend]
        model = "from-ui-config"
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path, ui_path=ui_config_path)

    assert settings.backend.model == "from-ui-config"
    assert settings.backend.num_ctx == 1234


def test_ui_config_alone_still_falls_back_to_defaults_for_other_sections(tmp_path):
    ui_config_path = tmp_path / "config.ui.toml"
    ui_config_path.write_text(
        """
        [backend]
        model = "from-ui-config"
        """,
        encoding="utf-8",
    )

    settings = load_settings(tmp_path / "does-not-exist.toml", ui_path=ui_config_path)

    assert settings.backend.model == "from-ui-config"
    assert settings.vad == VadSettings()


def test_unknown_section_in_ui_config_raises_config_error(tmp_path):
    ui_config_path = tmp_path / "config.ui.toml"
    ui_config_path.write_text(
        """
        [bogus_section]
        key = "value"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        load_settings(tmp_path / "does-not-exist.toml", ui_path=ui_config_path)


def test_unknown_key_in_ui_config_raises_config_error(tmp_path):
    ui_config_path = tmp_path / "config.ui.toml"
    ui_config_path.write_text(
        """
        [backend]
        typo_field = "oops"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        load_settings(tmp_path / "does-not-exist.toml", ui_path=ui_config_path)


def test_malformed_ui_config_toml_raises_config_error(tmp_path):
    ui_config_path = tmp_path / "config.ui.toml"
    ui_config_path.write_text("this is not [ valid toml", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_settings(tmp_path / "does-not-exist.toml", ui_path=ui_config_path)


def test_wrong_type_value_in_ui_config_raises_config_error(tmp_path):
    ui_config_path = tmp_path / "config.ui.toml"
    ui_config_path.write_text(
        """
        [backend]
        num_ctx = "not-a-number"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        load_settings(tmp_path / "does-not-exist.toml", ui_path=ui_config_path)


# --- story-v1.2.4-task-3: MicrophoneSettings and write_ui_config ------------


def test_microphone_device_parses_from_config(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [microphone]
        device = "USB Headset"
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.microphone.device == "USB Headset"


def test_microphone_device_defaults_to_empty_string_when_section_omitted(tmp_path):
    settings = load_settings(tmp_path / "does-not-exist.toml")

    assert settings.microphone == MicrophoneSettings()
    assert settings.microphone.device == ""


def test_write_ui_config_then_load_settings_round_trips(tmp_path):
    ui_config_path = tmp_path / "config.ui.toml"

    write_ui_config(ui_config_path, model="custom-model", microphone_device="USB Headset")
    settings = load_settings(tmp_path / "does-not-exist.toml", ui_path=ui_config_path)

    assert settings.backend.model == "custom-model"
    assert settings.microphone.device == "USB Headset"


def test_write_ui_config_never_touches_the_base_config_file(tmp_path):
    base_config_path = tmp_path / "config.toml"
    base_config_path.write_text('[backend]\nmodel = "do-not-touch"\n', encoding="utf-8")
    ui_config_path = tmp_path / "config.ui.toml"

    write_ui_config(ui_config_path, model="new-model", microphone_device="")

    assert base_config_path.read_text(encoding="utf-8") == '[backend]\nmodel = "do-not-touch"\n'


def test_write_ui_config_escapes_values_with_quotes_and_backslashes(tmp_path):
    """A device name from a real driver can contain characters that would
    corrupt the hand-written TOML if not escaped (e.g. a quote or
    backslash) - round-tripping through load_settings() is the strongest
    proof the written file is still valid, escaped TOML."""
    ui_config_path = tmp_path / "config.ui.toml"
    tricky_name = 'Mic "Pro" \\ Device'

    write_ui_config(ui_config_path, model="model", microphone_device=tricky_name)
    settings = load_settings(tmp_path / "does-not-exist.toml", ui_path=ui_config_path)

    assert settings.microphone.device == tricky_name
