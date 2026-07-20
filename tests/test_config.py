import re
from dataclasses import fields
from pathlib import Path

import pytest
from conftest import assert_stdlib_only_imports

from jarvis.core.config import (
    TTS_ROUTE_TYPES,
    BackendSettings,
    ClipboardSettings,
    ConfigError,
    DataBoundary,
    HotkeySettings,
    JournalSettings,
    McpServerSettings,
    McpSettings,
    McpToolAdapterSettings,
    MemorySettings,
    MicrophoneSettings,
    PiperTtsSettings,
    Settings,
    SileroTtsSettings,
    TtsSettings,
    VadSettings,
    load_settings,
    tts_route_field_specs,
    update_ui_config_mcp_enabled,
    write_ui_config,
)

EXAMPLE_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.example.toml"


@pytest.mark.parametrize("engine", ["silero", "piper"])
def test_tts_route_schema_projects_every_dataclass_field(engine):
    route_type = TTS_ROUTE_TYPES[engine]

    specs = tts_route_field_specs(engine)

    assert [spec.name for spec in specs] == [field.name for field in fields(route_type)]


def test_tts_route_schema_projects_validator_constraints():
    silero = {spec.name: spec for spec in tts_route_field_specs("silero")}
    piper = {spec.name: spec for spec in tts_route_field_specs("piper")}

    assert silero["model"].non_empty
    assert silero["sample_rate"].minimum == 0
    assert silero["sample_rate"].exclusive_minimum
    assert piper["config_path"].nullable
    assert piper["speaker_id"].minimum == 0
    assert not piper["speaker_id"].exclusive_minimum
    assert piper["volume"].exclusive_minimum


def _no_ui_layer(tmp_path) -> Path:
    """A ui_path guaranteed not to exist - config.example.toml's own
    directory is the real repo root, where a real config.ui.toml can
    legitimately exist after following a manual handoff (e.g.
    story-v1.2.4-task-4's), so tests asserting pure defaults must not
    rely on load_settings()'s own default ui_path resolution here."""
    return tmp_path / "no-such-config.ui.toml"


def test_example_config_round_trips_without_error(tmp_path):
    settings = load_settings(EXAMPLE_CONFIG_PATH, ui_path=_no_ui_layer(tmp_path))

    assert isinstance(settings, Settings)


def test_example_config_matches_documented_defaults(tmp_path):
    settings = load_settings(EXAMPLE_CONFIG_PATH, ui_path=_no_ui_layer(tmp_path))

    assert settings == Settings()


def test_journal_settings_parse_from_config(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [journal]
        enabled = false
        root = ".local/journal"
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.journal == JournalSettings(enabled=False, root=".local/journal")


def test_memory_settings_parse_from_config(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [memory]
        fork_seed_max_chars = 4096
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.memory == MemorySettings(fork_seed_max_chars=4096)


def test_memory_fork_seed_budget_must_be_positive(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [memory]
        fork_seed_max_chars = 0
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="fork_seed_max_chars"):
        load_settings(config_path)


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


def test_flash_attention_parses_from_config(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [backend]
        flash_attention = true
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.backend.flash_attention is True


def test_flash_attention_defaults_to_none_when_section_omitted(tmp_path):
    settings = load_settings(tmp_path / "does-not-exist.toml")

    assert settings.backend.flash_attention is None


def test_flash_attention_false_parses_from_config(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [backend]
        flash_attention = false
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.backend.flash_attention is False


def test_flash_attention_wrong_type_raises_config_error(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [backend]
        flash_attention = "yes"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        load_settings(config_path)


def test_kv_cache_type_parses_from_config(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [backend]
        kv_cache_type = "q8_0"
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.backend.kv_cache_type == "q8_0"


def test_kv_cache_type_defaults_to_none_when_section_omitted(tmp_path):
    settings = load_settings(tmp_path / "does-not-exist.toml")

    assert settings.backend.kv_cache_type is None


def test_kv_cache_type_wrong_type_raises_config_error(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [backend]
        kv_cache_type = 123
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        load_settings(config_path)


def test_backend_generation_options_parse_from_config(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [backend]
        temperature = 0.2
        top_p = 0.8
        top_k = 40
        min_p = 0.05
        repeat_penalty = 1.1
        repeat_last_n = 64
        seed = 123
        num_predict = 80
        stop = ["</speak>", "\\n\\n"]
        draft_num_predict = 16
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.backend.temperature == 0.2
    assert settings.backend.top_p == 0.8
    assert settings.backend.top_k == 40
    assert settings.backend.min_p == 0.05
    assert settings.backend.repeat_penalty == 1.1
    assert settings.backend.repeat_last_n == 64
    assert settings.backend.seed == 123
    assert settings.backend.num_predict == 80
    assert settings.backend.stop == ["</speak>", "\n\n"]
    assert settings.backend.draft_num_predict == 16


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("temperature", '"low"'),
        ("top_p", '"wide"'),
        ("top_k", "0.5"),
        ("min_p", '"small"'),
        ("repeat_penalty", '"high"'),
        ("repeat_last_n", "1.5"),
        ("seed", '"random"'),
        ("num_predict", "true"),
        ("draft_num_predict", '"short"'),
    ],
)
def test_backend_generation_option_wrong_type_raises_config_error(
    tmp_path, field_name, bad_value
):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
        [backend]
        {field_name} = {bad_value}
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        load_settings(config_path)


def test_backend_stop_must_be_a_list_of_strings(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [backend]
        stop = "stop-here"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        load_settings(config_path)


def test_backend_stop_rejects_non_string_list_items(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [backend]
        stop = ["ok", 123]
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        load_settings(config_path)


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
    assert_stdlib_only_imports("src/jarvis/core/config.py")


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


# --- story-v1.2.9-task-1: per-language TTS route config ---------------------


def test_tts_language_routes_parse_engine_specific_settings(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [tts.languages.ru]
        engine = "silero"
        model = "v5_ru"
        language = "ru"
        speaker = "eugene"
        sample_rate = 24000
        put_accent = true
        put_yo = false

        [tts.languages.en]
        engine = "piper"
        model = "voices/en.onnx"
        config_path = "voices/en.onnx.json"
        use_cuda = true
        espeak_data_dir = "voices/espeak-ng-data"
        download_dir = "voices/resources"
        speaker_id = 2
        length_scale = 0.9
        noise_scale = 0.6
        noise_w_scale = 0.7
        normalize_audio = false
        volume = 0.8
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.tts.languages == {
        "ru": SileroTtsSettings(
            model="v5_ru",
            language="ru",
            speaker="eugene",
            sample_rate=24000,
            put_accent=True,
            put_yo=False,
        ),
        "en": PiperTtsSettings(
            model="voices/en.onnx",
            config_path="voices/en.onnx.json",
            use_cuda=True,
            espeak_data_dir="voices/espeak-ng-data",
            download_dir="voices/resources",
            speaker_id=2,
            length_scale=0.9,
            noise_scale=0.6,
            noise_w_scale=0.7,
            normalize_audio=False,
            volume=0.8,
        ),
    }


def test_silero_config_accepts_an_unlisted_non_empty_model(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [tts.languages.ru]
        engine = "silero"
        model = "future_ru_model"
        language = "ru"
        speaker = "future_speaker"
        sample_rate = 44100
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.tts.languages["ru"] == SileroTtsSettings(
        model="future_ru_model",
        language="ru",
        speaker="future_speaker",
        sample_rate=44100,
    )


@pytest.mark.parametrize("legacy_field", ['voice = "baya"', "rate = 1.0"])
def test_legacy_global_tts_fields_fail_with_migration_guidance(tmp_path, legacy_field):
    config_path = tmp_path / "config.toml"
    config_path.write_text(f"[tts]\n{legacy_field}\n", encoding="utf-8")

    with pytest.raises(ConfigError, match=r"Move .*\[tts\.languages\."):
        load_settings(config_path)


@pytest.mark.parametrize(
    ("route", "message"),
    [
        (
            """
            engine = "silero"
            model = "v3_1_ru"
            language = "ru"
            speaker = "baya"
            sample_rate = 0
            """,
            "sample_rate",
        ),
        (
            """
            engine = "piper"
            model = "voice.onnx"
            length_scale = 0.0
            """,
            "length_scale",
        ),
        (
            """
            engine = "piper"
            model = "voice.onnx"
            speaker = "not-a-piper-setting"
            """,
            "Unknown key",
        ),
    ],
)
def test_engine_specific_tts_settings_reject_invalid_values(tmp_path, route, message):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"[tts.languages.ru]\n{route}",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=message):
        load_settings(config_path)


@pytest.mark.parametrize(
    ("route", "field", "python_type_description"),
    [
        (
            """
            engine = "silero"
            model = "v3_1_ru"
            sample_rate = "fast"
            """,
            "sample_rate",
            "int",
        ),
        (
            """
            engine = "silero"
            model = "v3_1_ru"
            put_accent = "yes"
            """,
            "put_accent",
            "bool | None",
        ),
        (
            """
            engine = "piper"
            model = "voice.onnx"
            length_scale = "fast"
            """,
            "length_scale",
            "float | None",
        ),
        (
            """
            engine = "piper"
            model = "voice.onnx"
            use_cuda = "yes"
            """,
            "use_cuda",
            "bool",
        ),
    ],
)
def test_tts_route_type_mismatch_reports_python_type_name(
    tmp_path, route, field, python_type_description
):
    """Locks the exact wording `_describe_spec_kind()` must reproduce for
    core/config.py's ConfigError - the shared TTS field-validation
    predicate (story-code-entropy-reduction.md, Task 2) must keep
    reporting Python type names (str/int/float/bool) here, not the
    `TtsFieldSpec.kind` strings (string/integer/number/boolean) that
    ui/transport.py's ProtocolError uses instead."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(f"[tts.languages.ru]\n{route}", encoding="utf-8")

    expected = re.escape(python_type_description)
    with pytest.raises(
        ConfigError, match=rf"\[tts\.languages\.ru\]\.{field} must be {expected}, "
    ):
        load_settings(config_path)


def test_tts_language_routes_parse_for_supported_languages(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [tts.languages.ru]
        engine = "silero"
        model = "v3_1_ru"

        [tts.languages.en]
        engine = "piper"
        model = ".local-models/piper/en_US-lessac-medium/en_US-lessac-medium.onnx"
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.tts.languages == {
        "ru": SileroTtsSettings(),
        "en": PiperTtsSettings(
            model=".local-models/piper/en_US-lessac-medium/en_US-lessac-medium.onnx",
        ),
    }


def test_tts_language_routes_default_to_current_silero_behavior(tmp_path):
    settings = load_settings(tmp_path / "does-not-exist.toml")

    assert settings.tts == TtsSettings()
    assert settings.tts.languages == {"ru": SileroTtsSettings()}


def test_tts_language_routes_reject_unknown_language(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [tts.languages.de]
        engine = "piper"
        model = "de.onnx"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=r"Unsupported TTS language.*de"):
        load_settings(config_path)


def test_tts_language_routes_reject_unknown_engine(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [tts.languages.en]
        engine = "festival"
        model = "voice.onnx"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=r"Unsupported TTS engine.*festival"):
        load_settings(config_path)


def test_tts_language_routes_merge_base_and_ui_layers_per_language(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [tts.languages.ru]
        engine = "silero"
        model = "custom_ru"
        """,
        encoding="utf-8",
    )
    ui_config_path = tmp_path / "config.ui.toml"
    ui_config_path.write_text(
        """
        [tts.languages.en]
        engine = "piper"
        model = "en.onnx"
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path, ui_path=ui_config_path)

    assert settings.tts.languages == {
        "ru": SileroTtsSettings(model="custom_ru"),
        "en": PiperTtsSettings(model="en.onnx"),
    }


def test_ui_route_with_engine_replaces_the_base_discriminated_variant(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [tts.languages.en]
        engine = "silero"
        model = "english_silero"
        language = "en"
        speaker = "speaker"
        """,
        encoding="utf-8",
    )
    ui_config_path = tmp_path / "config.ui.toml"
    write_ui_config(
        ui_config_path,
        model="m",
        microphone_device="",
        tts_routes={
            "ru": SileroTtsSettings(),
            "en": PiperTtsSettings(model="en.onnx"),
        },
    )

    settings = load_settings(config_path, ui_path=ui_config_path)

    assert settings.tts.languages["en"] == PiperTtsSettings(model="en.onnx")


def test_full_ui_route_can_clear_optional_base_parameter(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [tts.languages.en]
        engine = "piper"
        model = "base.onnx"
        config_path = "base.json"
        speaker_id = 3
        """,
        encoding="utf-8",
    )
    ui_config_path = tmp_path / "config.ui.toml"
    write_ui_config(
        ui_config_path,
        model="m",
        microphone_device="",
        tts_routes={
            "ru": SileroTtsSettings(),
            "en": PiperTtsSettings(model="ui.onnx"),
        },
    )

    settings = load_settings(config_path, ui_path=ui_config_path)

    assert settings.tts.languages["en"] == PiperTtsSettings(model="ui.onnx")


# --- story-v1.2.4-task-2: config layering (defaults < config.toml <
# config.ui.toml) ------------------------------------------------------------


def test_default_ui_path_sits_next_to_the_given_base_path(tmp_path, monkeypatch):
    """Regression: the default ui_path used to be an independently
    cwd-relative constant (Path("config.ui.toml")), so a real
    config.ui.toml sitting in the process's actual working directory
    would silently apply to every load_settings(some_other_dir/config.
    toml) call, even though it has nothing to do with that other
    directory - exactly the risk a manual QA pass leaving a real
    config.ui.toml in the repo root would create for any test not
    explicitly passing ui_path. Proves the fix: the default is derived
    from `path`'s own directory, not the cwd. monkeypatch.chdir() to a
    directory with its own decoy config.ui.toml, distinct from tmp_path,
    to make sure cwd is never consulted at all."""
    decoy_cwd = tmp_path / "unrelated-cwd"
    decoy_cwd.mkdir()
    (decoy_cwd / "config.ui.toml").write_text(
        '[backend]\nmodel = "decoy-from-cwd"\n', encoding="utf-8"
    )
    monkeypatch.chdir(decoy_cwd)

    real_dir = tmp_path / "real-config-dir"
    real_dir.mkdir()
    config_path = real_dir / "config.toml"
    config_path.write_text('[backend]\nmodel = "base-model"\n', encoding="utf-8")
    (real_dir / "config.ui.toml").write_text(
        '[backend]\nmodel = "ui-model-next-to-base"\n', encoding="utf-8"
    )

    settings = load_settings(config_path)  # no ui_path given

    assert settings.backend.model == "ui-model-next-to-base"


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


def test_ui_language_defaults_to_english(tmp_path):
    settings = load_settings(tmp_path / "does-not-exist.toml")

    assert settings.ui.language == "en"


def test_ui_language_parses_russian_from_config(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [ui]
        language = "ru"
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.ui.language == "ru"


def test_unsupported_ui_language_raises_config_error_naming_the_field(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [ui]
        language = "de"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=r"\[ui\].language"):
        load_settings(config_path)


def test_ui_language_of_wrong_type_raises_config_error(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [ui]
        language = 2
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=r"\[ui\].language"):
        load_settings(config_path)


def test_prompts_default_to_the_russian_dialog_prompts(tmp_path):
    settings = load_settings(tmp_path / "does-not-exist.toml")

    assert settings.prompts.system.startswith("Ты - Джарвис")
    assert settings.prompts.warmup == "Привет"


def test_prompts_parse_from_config(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [prompts]
        system = "You are Jarvis. Answer in English."
        warmup = "Hello"
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.prompts.system == "You are Jarvis. Answer in English."
    assert settings.prompts.warmup == "Hello"


def test_prompts_allow_partial_override_keeping_other_default(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [prompts]
        warmup = "Hello"
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.prompts.warmup == "Hello"
    assert settings.prompts.system.startswith("Ты - Джарвис")


@pytest.mark.parametrize("field_name", ["system", "warmup"])
def test_empty_prompt_raises_config_error_naming_the_field(tmp_path, field_name):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
        [prompts]
        {field_name} = "   "
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=rf"\[prompts\].{field_name}"):
        load_settings(config_path)


def test_prompt_of_wrong_type_raises_config_error(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [prompts]
        warmup = 5
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=r"\[prompts\].warmup"):
        load_settings(config_path)


def test_write_ui_config_then_load_settings_round_trips(tmp_path):
    ui_config_path = tmp_path / "config.ui.toml"

    write_ui_config(
        ui_config_path, model="custom-model", microphone_device="USB Headset"
    )
    settings = load_settings(tmp_path / "does-not-exist.toml", ui_path=ui_config_path)

    assert settings.backend.model == "custom-model"
    assert settings.microphone.device == "USB Headset"


def test_write_ui_config_never_touches_the_base_config_file(tmp_path):
    base_config_path = tmp_path / "config.toml"
    base_config_path.write_text('[backend]\nmodel = "do-not-touch"\n', encoding="utf-8")
    ui_config_path = tmp_path / "config.ui.toml"

    write_ui_config(ui_config_path, model="new-model", microphone_device="")

    assert (
        base_config_path.read_text(encoding="utf-8")
        == '[backend]\nmodel = "do-not-touch"\n'
    )


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


# --- story-v1.3.0-task-2: configuration iteration 2 fields ------------------


def test_write_ui_config_iteration_2_fields_round_trip(tmp_path):
    ui_config_path = tmp_path / "config.ui.toml"

    write_ui_config(
        ui_config_path,
        model="custom-model",
        microphone_device="USB Headset",
        ui_language="ru",
        vad=VadSettings(
            threshold=0.7,
            max_chunk_seconds=20,
            request_end_pause_seconds=1.5,
            resume_cooldown_seconds=0.5,
        ),
        tts_routes={
            "ru": SileroTtsSettings(
                model="custom_ru",
                language="ru",
                speaker="eugene",
                sample_rate=24000,
                put_accent=True,
                put_yo=False,
            ),
            "en": PiperTtsSettings(
                model="C:\\voices\\en.onnx",
                config_path="C:\\voices\\en.json",
                use_cuda=True,
                espeak_data_dir="C:\\espeak",
                download_dir="C:\\cache",
                speaker_id=2,
                length_scale=1.2,
                noise_scale=0.6,
                noise_w_scale=0.8,
                normalize_audio=False,
                volume=0.9,
            ),
        },
    )
    settings = load_settings(tmp_path / "does-not-exist.toml", ui_path=ui_config_path)

    assert settings.ui.language == "ru"
    assert settings.vad == VadSettings(
        threshold=0.7,
        max_chunk_seconds=20,
        request_end_pause_seconds=1.5,
        resume_cooldown_seconds=0.5,
    )
    assert settings.tts.languages == {
        "ru": SileroTtsSettings(
            model="custom_ru",
            language="ru",
            speaker="eugene",
            sample_rate=24000,
            put_accent=True,
            put_yo=False,
        ),
        "en": PiperTtsSettings(
            model="C:\\voices\\en.onnx",
            config_path="C:\\voices\\en.json",
            use_cuda=True,
            espeak_data_dir="C:\\espeak",
            download_dir="C:\\cache",
            speaker_id=2,
            length_scale=1.2,
            noise_scale=0.6,
            noise_w_scale=0.8,
            normalize_audio=False,
            volume=0.9,
        ),
    }


def test_write_ui_config_omits_sections_left_as_none(tmp_path):
    """None means "not chosen in the UI layer": the section is absent from
    config.ui.toml, so the layered loader falls through to config.toml or
    the built-in defaults - including the Silero-only TTS default."""
    ui_config_path = tmp_path / "config.ui.toml"

    write_ui_config(ui_config_path, model="m", microphone_device="d")
    settings = load_settings(tmp_path / "does-not-exist.toml", ui_path=ui_config_path)
    content = ui_config_path.read_text(encoding="utf-8")

    assert "[ui]" not in content
    assert "[vad]" not in content
    assert "[tts" not in content
    assert settings.ui.language == "en"
    assert settings.vad == VadSettings()
    assert settings.tts.languages == {"ru": SileroTtsSettings()}


def test_write_ui_config_persists_live_mcp_enabled_state(tmp_path):
    ui_config_path = tmp_path / "config.ui.toml"

    write_ui_config(
        ui_config_path,
        model="m",
        microphone_device="d",
        mcp_enabled=True,
    )

    settings = load_settings(tmp_path / "does-not-exist.toml", ui_path=ui_config_path)
    assert settings.mcp.enabled is True


def test_update_ui_config_mcp_enabled_creates_only_the_mcp_override(tmp_path):
    config_path = tmp_path / "config.toml"
    ui_config_path = tmp_path / "config.ui.toml"
    config_path.write_text('[backend]\nmodel = "before-toggle"\n', encoding="utf-8")

    update_ui_config_mcp_enabled(ui_config_path, enabled=True)

    config_path.write_text('[backend]\nmodel = "after-toggle"\n', encoding="utf-8")

    contents = ui_config_path.read_text(encoding="utf-8")
    assert "[mcp]\nenabled = true" in contents
    assert "[backend]" not in contents
    assert "[microphone]" not in contents
    assert "[ui]" not in contents
    assert "[vad]" not in contents
    assert "[tts" not in contents
    settings = load_settings(config_path, ui_path=ui_config_path)
    assert settings.backend.model == "after-toggle"
    assert settings.mcp.enabled is True


def test_update_ui_config_mcp_enabled_preserves_every_other_byte(tmp_path):
    ui_config_path = tmp_path / "config.ui.toml"
    original = (
        "# Existing UI selections stay machine-owned.\n"
        "[backend]\n"
        'model = "selected-model"\n'
        "\n"
        "[mcp]\n"
        "enabled = false\n"
        "\n"
        "[vad]\n"
        "threshold = 0.75\n"
    )
    ui_config_path.write_text(original, encoding="utf-8")
    original_bytes = ui_config_path.read_bytes()

    update_ui_config_mcp_enabled(ui_config_path, enabled=True)

    assert ui_config_path.read_bytes() == original_bytes.replace(
        b"enabled = false", b"enabled = true"
    )


def test_update_ui_config_mcp_enabled_appends_to_a_legacy_ui_file(tmp_path):
    ui_config_path = tmp_path / "config.ui.toml"
    original = '[backend]\nmodel = "selected-model"\n'
    ui_config_path.write_text(original, encoding="utf-8")

    update_ui_config_mcp_enabled(ui_config_path, enabled=False)

    contents = ui_config_path.read_text(encoding="utf-8")
    assert contents.startswith(original)
    assert contents.endswith("\n[mcp]\nenabled = false\n")


def test_mcp_defaults_to_disabled_with_no_servers(tmp_path):
    settings = load_settings(tmp_path / "does-not-exist.toml")

    assert settings.mcp == McpSettings()
    assert settings.mcp.enabled is False
    assert settings.mcp.presentation_strategy == "native"
    assert settings.mcp.max_tool_calls_per_turn == 3
    assert settings.mcp.servers == {}


def test_mcp_presentation_settings_parse_from_config(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [mcp]
        presentation_strategy = "prompt"
        max_tool_calls_per_turn = 5
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.mcp.presentation_strategy == "prompt"
    assert settings.mcp.max_tool_calls_per_turn == 5


def test_mcp_rejects_unknown_presentation_strategy(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text('[mcp]\npresentation_strategy = "xml"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match=r"\[mcp\]\.presentation_strategy"):
        load_settings(config_path)


def test_mcp_rejects_non_string_presentation_strategy(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[mcp]\npresentation_strategy = ["native"]\n', encoding="utf-8"
    )

    with pytest.raises(ConfigError, match=r"\[mcp\]\.presentation_strategy"):
        load_settings(config_path)


@pytest.mark.parametrize("raw_value", ["0", "-1", "true", '"3"'])
def test_mcp_rejects_invalid_tool_call_budget(tmp_path, raw_value):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"[mcp]\nmax_tool_calls_per_turn = {raw_value}\n", encoding="utf-8"
    )

    with pytest.raises(ConfigError, match=r"\[mcp\]\.max_tool_calls_per_turn"):
        load_settings(config_path)


def test_mcp_section_parses_enabled_and_servers(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [mcp]
        enabled = true

        [mcp.servers.search]
        command = "npx"
        args = ["-y", "some-search-server"]

        [mcp.servers.db]
        command = "db-server"
        enabled = false
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.mcp.enabled is True
    assert settings.mcp.servers == {
        "search": McpServerSettings(
            command="npx", args=("-y", "some-search-server"), enabled=True
        ),
        "db": McpServerSettings(command="db-server", enabled=False),
    }


def test_mcp_server_cannot_use_reserved_builtin_provider_name(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[mcp.servers.builtin]\ncommand = "server"\n', encoding="utf-8"
    )

    with pytest.raises(ConfigError, match="reserved provider name 'builtin'"):
        load_settings(config_path)


def test_mcp_server_enabled_defaults_to_true(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [mcp.servers.search]
        command = "search-server"
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.mcp.servers["search"].enabled is True
    assert settings.mcp.servers["search"].args == ()
    assert settings.mcp.servers["search"].data_boundary is DataBoundary.UNKNOWN


def test_mcp_server_parses_default_boundary_and_per_tool_overrides(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [mcp.servers.mixed]
        command = "mixed-server"
        data_boundary = "local"

        [mcp.servers.mixed.tool_boundaries]
        lan_query = "lan"
        web_search = "internet"
        """,
        encoding="utf-8",
    )

    server = load_settings(config_path).mcp.servers["mixed"]

    assert server.boundary_for("local_lookup") is DataBoundary.LOCAL
    assert server.boundary_for("lan_query") is DataBoundary.LAN
    assert server.boundary_for("web_search") is DataBoundary.INTERNET


def test_mcp_server_parses_environment_and_canonical_tool_adapter(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [mcp.servers.search]
        command = "ddgs"
        env = { DDGS_PROXY = "socks5://127.0.0.1:9150" }

        [mcp.servers.search.tool_adapters.search_text]
        name = "web_search"
        description = "Search the current public web."
        allowed_arguments = ["query", "max_results", "timelimit"]
        fixed_arguments = { backend = "duckduckgo", safesearch = "moderate" }
        """,
        encoding="utf-8",
    )

    server = load_settings(config_path).mcp.servers["search"]

    assert server.env == {"DDGS_PROXY": "socks5://127.0.0.1:9150"}
    assert server.tool_adapters == {
        "search_text": McpToolAdapterSettings(
            public_name="web_search",
            description="Search the current public web.",
            allowed_arguments=("query", "max_results", "timelimit"),
            fixed_arguments={"backend": "duckduckgo", "safesearch": "moderate"},
        )
    }


def test_mcp_server_rejects_duplicate_canonical_tool_names(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [mcp.servers.search]
        command = "server"

        [mcp.servers.search.tool_adapters.first]
        name = "web_search"

        [mcp.servers.search.tool_adapters.second]
        name = "web_search"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="duplicate canonical tool name"):
        load_settings(config_path)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("env = { TOKEN = 1 }", "env must be a table of strings"),
        ('tool_adapters = "lookup"', "tool_adapters.*must be a table"),
        (
            '[mcp.servers.search.tool_adapters.lookup]\nname = "public"\nextra = 1',
            "Unknown key",
        ),
        (
            '[mcp.servers.search.tool_adapters.lookup]\nname = ""',
            "name must be a non-empty string",
        ),
        (
            '[mcp.servers.search.tool_adapters.lookup]\nname = "public"\n'
            'description = ""',
            "description must be a non-empty string",
        ),
        (
            '[mcp.servers.search.tool_adapters.lookup]\nname = "public"\n'
            'allowed_arguments = ["query", "query"]',
            "must not contain duplicates",
        ),
        (
            '[mcp.servers.search.tool_adapters.lookup]\nname = "public"\n'
            "fixed_arguments = { query = [1] }",
            "fixed_arguments must be a table",
        ),
        (
            '[mcp.servers.search.tool_adapters.lookup]\nname = "public"\n'
            'allowed_arguments = ["query"]\nfixed_arguments = { query = "fixed" }',
            "cannot be both allowed and fixed",
        ),
    ],
)
def test_mcp_server_rejects_invalid_tool_adapter_configuration(tmp_path, body, message):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[mcp.servers.search]\ncommand = "server"\n{body}\n', encoding="utf-8"
    )

    with pytest.raises(ConfigError, match=message):
        load_settings(config_path)


@pytest.mark.parametrize("field", ["data_boundary", "tool_boundaries.lookup"])
def test_mcp_server_rejects_unknown_data_boundary(tmp_path, field):
    config_path = tmp_path / "config.toml"
    if field == "data_boundary":
        body = 'data_boundary = "cloud"'
    else:
        body = '[mcp.servers.search.tool_boundaries]\nlookup = "cloud"'
    config_path.write_text(
        f'[mcp.servers.search]\ncommand = "server"\n{body}\n', encoding="utf-8"
    )

    with pytest.raises(ConfigError, match="data boundary"):
        load_settings(config_path)


def test_mcp_server_rejects_non_string_data_boundary(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [mcp.servers.search]
        command = "server"
        data_boundary = 1
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="data boundary must be a string"):
        load_settings(config_path)


def test_mcp_server_rejects_non_table_tool_boundary_overrides(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [mcp.servers.search]
        command = "server"
        tool_boundaries = "internet"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="tool_boundaries must be a table"):
        load_settings(config_path)


def test_mcp_section_rejects_unknown_key(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [mcp]
        enabled = true
        bogus = true
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=r"Unknown key\(s\) in \[mcp\].*bogus"):
        load_settings(config_path)


def test_mcp_section_rejects_wrong_type_for_enabled(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [mcp]
        enabled = "yes"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=r"\[mcp\].enabled must be bool"):
        load_settings(config_path)


def test_mcp_server_requires_command(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [mcp.servers.search]
        args = ["-y"]
        """,
        encoding="utf-8",
    )

    with pytest.raises(
        ConfigError, match=r"\[mcp.servers.search\].command is required"
    ):
        load_settings(config_path)


def test_mcp_server_rejects_empty_command(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [mcp.servers.search]
        command = "   "
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=r"\[mcp.servers.search\].command"):
        load_settings(config_path)


def test_mcp_server_rejects_unknown_key(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [mcp.servers.search]
        command = "search-server"
        bogus = 1
        """,
        encoding="utf-8",
    )

    with pytest.raises(
        ConfigError, match=r"Unknown key\(s\) in \[mcp.servers.search\].*bogus"
    ):
        load_settings(config_path)


def test_mcp_server_rejects_non_string_args(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [mcp.servers.search]
        command = "search-server"
        args = [1, 2]
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=r"\[mcp.servers.search\].args"):
        load_settings(config_path)


def test_mcp_ui_layer_can_override_enabled_without_resetting_servers(tmp_path):
    config_path = tmp_path / "config.toml"
    ui_path = tmp_path / "config.ui.toml"
    config_path.write_text(
        """
        [mcp.servers.search]
        command = "search-server"
        """,
        encoding="utf-8",
    )
    ui_path.write_text(
        """
        [mcp]
        enabled = true
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path, ui_path=ui_path)

    assert settings.mcp.enabled is True
    assert settings.mcp.servers == {
        "search": McpServerSettings(command="search-server")
    }
