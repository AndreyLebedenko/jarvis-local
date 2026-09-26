"""[generation] profiles: one per model-request kind, resolved against
[generation] defaults (tasks/done/task-config-generation-profiles.md)."""

import re
from pathlib import Path

import pytest

from jarvis.core.config import (
    ANNOTATION_PROFILE,
    DIALOG_PROFILE_BY_REASONING,
    GENERATION_PROFILE_NAMES,
    MOVED_CONFIG_KEYS,
    SPOKEN_DERIVATIVE_PROFILE,
    TRANSCRIPTION_PROFILE,
    VOICE_INTENT_PROFILE,
    WARMUP_PROFILE,
    ConfigError,
    GenerationOptions,
    load_settings,
)

ALL_OPTIONS_TOML = """
temperature = 0.618
top_p = 0.9
top_k = 50
min_p = 0.05
repeat_penalty = 1.025
repeat_last_n = 64
seed = 7
num_predict = 2048
stop = ["</x>"]
draft_num_predict = 16
"""

ALL_OPTIONS = GenerationOptions(
    temperature=0.618,
    top_p=0.9,
    top_k=50,
    min_p=0.05,
    repeat_penalty=1.025,
    repeat_last_n=64,
    seed=7,
    num_predict=2048,
    stop=["</x>"],
    draft_num_predict=16,
)

LOAD_KEYS = ["num_ctx", "flash_attention", "kv_cache_type"]
NON_DIALOG_PROFILES = [
    SPOKEN_DERIVATIVE_PROFILE,
    VOICE_INTENT_PROFILE,
    WARMUP_PROFILE,
    ANNOTATION_PROFILE,
    TRANSCRIPTION_PROFILE,
]


def _load(tmp_path: Path, body: str):
    config_path = tmp_path / "config.toml"
    config_path.write_text(body, encoding="utf-8")
    return load_settings(config_path, ui_path=tmp_path / "absent.ui.toml")


def _section_header(profile_name: str) -> str:
    return f"[generation.{profile_name}]"


def test_every_request_kind_has_a_profile():
    assert set(GENERATION_PROFILE_NAMES) == {
        "dialog.off",
        "dialog.low",
        "dialog.medium",
        "dialog.high",
        "spoken_derivative",
        "voice_intent",
        "warmup",
        "annotation",
        "transcription",
    }


def test_without_config_every_profile_sends_only_the_default_length_cap(tmp_path):
    settings = _load(tmp_path, "")

    for name in GENERATION_PROFILE_NAMES:
        assert settings.generation.options_for(name) == GenerationOptions(
            num_predict=16384
        )


def test_generation_table_without_num_predict_keeps_the_default_cap(tmp_path):
    settings = _load(tmp_path, "[generation]\ntemperature = 0.5\n")

    for name in GENERATION_PROFILE_NAMES:
        assert settings.generation.options_for(name).num_predict == 16384


def test_dialog_off_num_predict_changes_only_the_dialog_off_cap(tmp_path):
    settings = _load(tmp_path, "[generation.dialog.off]\nnum_predict = 2048\n")

    assert settings.generation.options_for("dialog.off").num_predict == 2048
    for name in GENERATION_PROFILE_NAMES:
        if name != "dialog.off":
            assert settings.generation.options_for(name).num_predict == 16384


@pytest.mark.parametrize("value", [0, -1])
@pytest.mark.parametrize(
    "table", ["generation", "generation.dialog.low", "generation.warmup"]
)
def test_non_positive_num_predict_is_rejected_naming_its_table(tmp_path, table, value):
    with pytest.raises(ConfigError, match=rf"\[{re.escape(table)}\]\.num_predict"):
        _load(tmp_path, f"[{table}]\nnum_predict = {value}\n")


def test_default_history_budget_and_dialog_cap_fill_num_ctx_exactly(tmp_path):
    settings = _load(tmp_path, "")

    assert (
        settings.history.prompt_capacity_tokens
        + settings.generation.dialog_generation_reserve().tokens
        == settings.backend.num_ctx
        == 49152 + 16384
    )


def test_dialog_cap_beyond_the_history_budget_names_the_dialog_profile(tmp_path):
    with pytest.raises(
        ConfigError, match=r"\[generation\.dialog\.high\]\.num_predict.*num_ctx"
    ):
        _load(tmp_path, "[generation.dialog.high]\nnum_predict = 16385\n")


def test_inherited_cap_beyond_the_history_budget_names_the_generation_table(
    tmp_path,
):
    with pytest.raises(ConfigError) as error:
        _load(tmp_path, "[generation]\nnum_predict = 16385\n")

    assert "[generation].num_predict (16385)" in str(error.value)
    assert "[generation.dialog" not in str(error.value)


def test_non_dialog_cap_is_not_part_of_the_dialog_history_budget(tmp_path):
    settings = _load(tmp_path, "[generation.annotation]\nnum_predict = 60000\n")

    assert settings.generation.options_for(ANNOTATION_PROFILE).num_predict == 60000


def test_smaller_num_ctx_fits_with_a_matching_dialog_cap(tmp_path):
    settings = _load(
        tmp_path,
        """
        [backend]
        num_ctx = 32768

        [history]
        prompt_capacity_tokens = 24576
        recent_history_max_tokens = 12288

        [generation]
        num_predict = 8192
        """,
    )

    assert settings.generation.dialog_generation_reserve().tokens == 8192


def test_dialog_generation_reserve_is_the_largest_dialog_cap(tmp_path):
    settings = _load(
        tmp_path,
        """
        [generation]
        num_predict = 1024

        [generation.dialog.off]
        num_predict = 2048

        [generation.dialog.medium]
        num_predict = 12000

        [generation.annotation]
        num_predict = 15000
        """,
    )

    reserve = settings.generation.dialog_generation_reserve()

    assert (reserve.profile, reserve.tokens, reserve.table) == (
        "dialog.medium",
        12000,
        "generation.dialog.medium",
    )


def test_history_generation_reserve_key_moved_to_generation_num_predict(tmp_path):
    with pytest.raises(
        ConfigError,
        match=(
            r"\[history\]\.reasoning_generation_reserve_tokens .*"
            r"moved to \[generation\]\.num_predict"
        ),
    ):
        _load(tmp_path, "[history]\nreasoning_generation_reserve_tokens = 16384\n")


def test_built_in_profile_prompts_match_the_pre_profile_defaults(tmp_path):
    settings = _load(tmp_path, "")
    generation = settings.generation

    assert generation.profile(WARMUP_PROFILE).prompt == "Привет"
    assert generation.profile(SPOKEN_DERIVATIVE_PROFILE).prompt.startswith(
        "Тебе передан точный текст"
    )
    for name in [
        *DIALOG_PROFILE_BY_REASONING.values(),
        VOICE_INTENT_PROFILE,
        ANNOTATION_PROFILE,
        TRANSCRIPTION_PROFILE,
    ]:
        assert generation.profile(name).prompt is None


def test_dialog_profile_reasoning_is_its_level_and_others_default_to_off(tmp_path):
    settings = _load(tmp_path, "")

    for level, name in DIALOG_PROFILE_BY_REASONING.items():
        assert settings.generation.profile(name).reasoning == level
    for name in NON_DIALOG_PROFILES:
        assert settings.generation.profile(name).reasoning == "off"


def test_generation_defaults_apply_to_every_profile(tmp_path):
    settings = _load(tmp_path, f"[generation]\n{ALL_OPTIONS_TOML}")

    for name in GENERATION_PROFILE_NAMES:
        assert settings.generation.options_for(name) == ALL_OPTIONS


def test_profile_key_overrides_default_and_unset_key_falls_back(tmp_path):
    settings = _load(
        tmp_path,
        """
        [generation]
        temperature = 0.618
        top_p = 0.9

        [generation.annotation]
        temperature = 0.9
        """,
    )

    assert settings.generation.options_for(ANNOTATION_PROFILE) == GenerationOptions(
        temperature=0.9, top_p=0.9, num_predict=16384
    )


def test_profile_override_reaches_no_other_profile(tmp_path):
    settings = _load(
        tmp_path,
        """
        [generation]
        temperature = 0.618

        [generation.annotation]
        temperature = 0.9
        """,
    )

    for name in GENERATION_PROFILE_NAMES:
        if name != ANNOTATION_PROFILE:
            assert settings.generation.options_for(name).temperature == 0.618


def test_key_unset_in_both_profile_and_defaults_stays_unset(tmp_path):
    settings = _load(tmp_path, "[generation.dialog.medium]\nnum_predict = 8192\n")

    assert settings.generation.options_for("dialog.medium") == GenerationOptions(
        num_predict=8192
    )


@pytest.mark.parametrize("profile_name", GENERATION_PROFILE_NAMES)
def test_every_profile_accepts_every_generation_option(tmp_path, profile_name):
    settings = _load(tmp_path, f"{_section_header(profile_name)}\n{ALL_OPTIONS_TOML}")

    assert settings.generation.options_for(profile_name) == ALL_OPTIONS


@pytest.mark.parametrize(
    ("key", "bad_value"),
    [
        ("temperature", '"low"'),
        ("top_k", "0.5"),
        ("repeat_last_n", "1.5"),
        ("seed", '"random"'),
        ("num_predict", "true"),
        ("stop", '"</x>"'),
    ],
)
def test_wrong_option_type_names_the_section_and_key(tmp_path, key, bad_value):
    with pytest.raises(ConfigError, match=rf"\[generation\]\.{key}"):
        _load(tmp_path, f"[generation]\n{key} = {bad_value}\n")
    with pytest.raises(ConfigError, match=rf"\[generation\.warmup\]\.{key}"):
        _load(tmp_path, f"[generation.warmup]\n{key} = {bad_value}\n")


@pytest.mark.parametrize("load_key", LOAD_KEYS)
@pytest.mark.parametrize("profile_name", GENERATION_PROFILE_NAMES)
def test_model_load_key_in_a_profile_is_rejected(tmp_path, load_key, profile_name):
    value = "true" if load_key == "flash_attention" else "1"
    if load_key == "kv_cache_type":
        value = '"q8_0"'

    with pytest.raises(ConfigError, match=r"model-load setting.*\[backend\]"):
        _load(tmp_path, f"{_section_header(profile_name)}\n{load_key} = {value}\n")


def test_model_load_key_in_generation_defaults_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match=r"\[generation\]\.num_ctx.*\[backend\]"):
        _load(tmp_path, "[generation]\nnum_ctx = 4096\n")


@pytest.mark.parametrize(
    "header",
    ["[generation.summary]", "[generation.dialog.extreme]"],
)
def test_unknown_profile_is_rejected(tmp_path, header):
    with pytest.raises(ConfigError, match="Unknown"):
        _load(tmp_path, f"{header}\ntemperature = 0.5\n")


def test_unknown_key_in_a_profile_is_rejected(tmp_path):
    with pytest.raises(
        ConfigError, match=r"Unknown key\(s\) in \[generation\.warmup\].*colour"
    ):
        _load(tmp_path, '[generation.warmup]\ncolour = "blue"\n')


def test_dialog_profile_does_not_accept_reasoning(tmp_path):
    with pytest.raises(ConfigError, match=r"\[generation\.dialog\.low\].*reasoning"):
        _load(tmp_path, '[generation.dialog.low]\nreasoning = "high"\n')


@pytest.mark.parametrize("profile_name", NON_DIALOG_PROFILES)
def test_non_dialog_profile_reasoning_parses(tmp_path, profile_name):
    settings = _load(
        tmp_path, f'{_section_header(profile_name)}\nreasoning = "medium"\n'
    )

    assert settings.generation.profile(profile_name).reasoning == "medium"


@pytest.mark.parametrize("bad_value", ['"sideways"', "3"])
def test_invalid_reasoning_value_is_rejected(tmp_path, bad_value):
    with pytest.raises(ConfigError, match=r"\[generation\.annotation\]\.reasoning"):
        _load(tmp_path, f"[generation.annotation]\nreasoning = {bad_value}\n")


@pytest.mark.parametrize("profile_name", GENERATION_PROFILE_NAMES)
def test_profile_prompt_preserves_literal_text(tmp_path, profile_name):
    settings = _load(
        tmp_path, f'{_section_header(profile_name)}\nprompt = "Custom text."\n'
    )

    assert settings.generation.profile(profile_name).prompt == "Custom text."


def test_profile_prompt_reference_resolves_under_config_local_jarvis_directory(
    tmp_path,
):
    prompt_path = tmp_path / ".jarvis" / "prompts" / "think-level-2.md"
    prompt_path.parent.mkdir(parents=True)
    prompt_path.write_text("Consider alternatives.", encoding="utf-8")

    settings = _load(
        tmp_path,
        '[generation.dialog.medium]\nprompt = "@prompts/think-level-2.md"\n',
    )

    assert settings.generation.profile("dialog.medium").prompt == (
        "Consider alternatives."
    )


@pytest.mark.parametrize(
    ("reference", "relative_path"),
    [
        ("@low.md", "low.md"),
        ("@/modes/medium.md", "modes/medium.md"),
        ("@C:/modes/high.md", "modes/high.md"),
    ],
)
def test_anchored_profile_prompt_reference_still_resolves_under_jarvis_directory(
    tmp_path, reference, relative_path
):
    prompt_path = tmp_path / ".jarvis" / relative_path
    prompt_path.parent.mkdir(parents=True)
    prompt_path.write_text("Plan briefly.", encoding="utf-8")

    settings = _load(tmp_path, f"[generation.dialog.low]\nprompt = {reference!r}\n")

    assert settings.generation.profile("dialog.low").prompt == "Plan briefly."


@pytest.mark.parametrize(
    ("reference", "prepare_prompt"),
    [
        ("@directory", lambda root: (root / "directory").mkdir()),
        (
            "@invalid-utf8.md",
            lambda root: (root / "invalid-utf8.md").write_bytes(b"\x80"),
        ),
        (
            "@blank.md",
            lambda root: (root / "blank.md").write_text(" \n\t", encoding="utf-8"),
        ),
    ],
)
def test_unreadable_profile_prompt_reference_names_the_profile(
    tmp_path, reference, prepare_prompt
):
    prompt_root = tmp_path / ".jarvis"
    prompt_root.mkdir()
    prepare_prompt(prompt_root)

    with pytest.raises(ConfigError, match=r"\[generation\.spoken_derivative\]\.prompt"):
        _load(tmp_path, f"[generation.spoken_derivative]\nprompt = {reference!r}\n")


def test_blank_voice_intent_prompt_is_rejected_rather_than_read_as_off(tmp_path):
    with pytest.raises(ConfigError, match=r"\[generation\.voice_intent\]\.prompt"):
        _load(tmp_path, '[generation.voice_intent]\nprompt = "  "\n')


@pytest.mark.parametrize(
    "value", ['""', '"   "', "'@nested/../prompt.md'", '"@missing.md"', "5"]
)
def test_invalid_profile_prompt_names_the_profile(tmp_path, value):
    (tmp_path / ".jarvis").mkdir()

    with pytest.raises(ConfigError, match=r"\[generation\.dialog\.low\]\.prompt"):
        _load(tmp_path, f"[generation.dialog.low]\nprompt = {value}\n")


@pytest.mark.parametrize(("old_location", "new_location"), MOVED_CONFIG_KEYS.items())
def test_moved_key_names_its_new_location(tmp_path, old_location, new_location):
    section, key = old_location.rsplit(".", 1)

    with pytest.raises(ConfigError) as error:
        _load(tmp_path, f'[{section}]\n{key} = "x"\n')

    message = str(error.value)
    assert f"[{section}].{key}" in message
    assert f"moved to {new_location}" in message


def test_moved_key_in_the_ui_layer_is_also_rejected(tmp_path):
    ui_path = tmp_path / "config.ui.toml"
    ui_path.write_text("[backend]\ntemperature = 0.5\n", encoding="utf-8")

    with pytest.raises(ConfigError, match=r"moved to \[generation\]\.temperature"):
        load_settings(tmp_path / "absent.toml", ui_path=ui_path)


def test_every_generation_option_and_moved_prompt_has_a_migration_entry():
    moved_backend_keys = {
        location.split(".", 1)[1]
        for location in MOVED_CONFIG_KEYS
        if location.startswith("backend.")
    }

    assert moved_backend_keys == set(GenerationOptions.__dataclass_fields__)
    assert {
        "prompts.reasoning_low",
        "prompts.reasoning_medium",
        "prompts.reasoning_high",
        "prompts.response_text_voice",
        "prompts.response_voice",
        "prompts.voice_intent_directive",
        "prompts.warmup",
        "history.annotation.reasoning",
        "history.annotation.instruction",
        "history.transcription.instruction",
        "history.reasoning_generation_reserve_tokens",
    } <= set(MOVED_CONFIG_KEYS)


def test_response_voice_contract_has_a_built_in_default(tmp_path):
    settings = _load(tmp_path, "")

    assert settings.response.voice_contract.startswith("Этот ответ будет только")


def test_response_voice_contract_reference_resolves(tmp_path):
    prompt_path = tmp_path / ".jarvis" / "voice.md"
    prompt_path.parent.mkdir(parents=True)
    prompt_path.write_text("Speak plainly.", encoding="utf-8")

    settings = _load(tmp_path, '[response]\nvoice_contract = "@voice.md"\n')

    assert settings.response.voice_contract == "Speak plainly."


def test_empty_response_voice_contract_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match=r"\[response\]\.voice_contract"):
        _load(tmp_path, '[response]\nvoice_contract = ""\n')


def test_todays_status_console_ui_layer_still_loads(tmp_path):
    ui_path = tmp_path / "config.ui.toml"
    ui_path.write_text(
        """
        [backend]
        model = "gemma4:12b-it-q8_0"

        [microphone]
        device = "Microphone (Yeti X)"
        host_api = "MME"

        [ui]
        language = "ru"

        [tts]
        enabled = true

        [mcp]
        enabled = false

        [response]
        mode = "voice"
        """,
        encoding="utf-8",
    )

    settings = load_settings(tmp_path / "absent.toml", ui_path=ui_path)

    assert settings.backend.model == "gemma4:12b-it-q8_0"
    assert settings.response.mode == "voice"
