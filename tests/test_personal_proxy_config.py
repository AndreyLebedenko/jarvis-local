import re
from dataclasses import fields
from pathlib import Path

import pytest

from jarvis.core.config import (
    ConfigError,
    PersonalProxySettings,
    Settings,
    load_settings,
)

EXAMPLE_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.example.toml"


def _load(tmp_path, body: str) -> Settings:
    config_path = tmp_path / "config.toml"
    config_path.write_text(body, encoding="utf-8")
    return load_settings(config_path, ui_path=tmp_path / "no-such-config.ui.toml")


def test_the_defaults_enable_nothing_and_send_nothing():
    settings = PersonalProxySettings()

    assert settings.endpoint == ""
    assert settings.model == ""
    assert settings.dry_run is True


def test_a_missing_section_gives_the_same_inert_defaults(tmp_path):
    assert _load(tmp_path, "").personal_proxy == PersonalProxySettings()
    assert Settings().personal_proxy == PersonalProxySettings()


def test_section_defaults():
    assert PersonalProxySettings() == PersonalProxySettings(
        endpoint="",
        model="",
        api_key_env="JARVIS_PERSONAL_PROXY_KEY",
        dry_run=True,
        topics_file="personal_proxy_topics.txt",
        request_timeout_seconds=60,
        connect_timeout_seconds=10,
        confirmation_timeout_seconds=20,
        doubt_min_listed=1,
        stt_model="large-v3-turbo",
        stt_device="cuda",
        stt_language="ru",
        stt_weak_word_probability=0.5,
        stt_min_speech_seconds=0.3,
        check_model="gemma4:12b",
        check_num_ctx=8192,
        check_temperature=0.618,
        check_top_p=0.9,
        check_top_k=50,
        check_min_p=0.05,
        check_repeat_penalty=1.025,
    )


def test_section_parses_from_config(tmp_path):
    settings = _load(
        tmp_path,
        """
        [personal_proxy]
        endpoint = "https://proxy.example.test/v1/chat/completions"
        model = "some-model"
        api_key_env = "MY_KEY_VAR"
        dry_run = false
        topics_file = ".local/topics.txt"
        request_timeout_seconds = 30.5
        connect_timeout_seconds = 3
        confirmation_timeout_seconds = 7
        doubt_min_listed = 2
        stt_model = "small"
        stt_device = "cpu"
        stt_language = "en"
        stt_weak_word_probability = 0.25
        stt_min_speech_seconds = 0.8
        check_model = "other:7b"
        check_num_ctx = 4096
        check_temperature = 0
        check_top_p = 1
        check_top_k = 20
        check_min_p = 0
        check_repeat_penalty = 1.5
        """,
    )

    assert settings.personal_proxy == PersonalProxySettings(
        endpoint="https://proxy.example.test/v1/chat/completions",
        model="some-model",
        api_key_env="MY_KEY_VAR",
        dry_run=False,
        topics_file=".local/topics.txt",
        request_timeout_seconds=30.5,
        connect_timeout_seconds=3,
        confirmation_timeout_seconds=7,
        doubt_min_listed=2,
        stt_model="small",
        stt_device="cpu",
        stt_language="en",
        stt_weak_word_probability=0.25,
        stt_min_speech_seconds=0.8,
        check_model="other:7b",
        check_num_ctx=4096,
        check_temperature=0,
        check_top_p=1,
        check_top_k=20,
        check_min_p=0,
        check_repeat_penalty=1.5,
    )


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ('endpoint = "proxy.example.test/v1"', r"\[personal_proxy\]\.endpoint"),
        ('endpoint = "ftp://proxy.example.test"', r"\[personal_proxy\]\.endpoint"),
        ('api_key_env = ""', r"\[personal_proxy\]\.api_key_env"),
        ('api_key_env = "not a name"', r"\[personal_proxy\]\.api_key_env"),
        ('topics_file = "  "', r"\[personal_proxy\]\.topics_file"),
        ("request_timeout_seconds = 0", r"\[personal_proxy\]\.request_timeout_seconds"),
        (
            "connect_timeout_seconds = -1",
            r"\[personal_proxy\]\.connect_timeout_seconds",
        ),
        (
            "confirmation_timeout_seconds = 0",
            r"\[personal_proxy\]\.confirmation_timeout_seconds",
        ),
        ("doubt_min_listed = 0", r"\[personal_proxy\]\.doubt_min_listed"),
        ("stt_min_speech_seconds = 0", r"\[personal_proxy\]\.stt_min_speech_seconds"),
        (
            "stt_min_speech_seconds = -0.5",
            r"\[personal_proxy\]\.stt_min_speech_seconds",
        ),
        ('stt_model = ""', r"\[personal_proxy\]\.stt_model"),
        ('stt_device = "tpu"', r"\[personal_proxy\]\.stt_device"),
        ('stt_language = " "', r"\[personal_proxy\]\.stt_language"),
        (
            "stt_weak_word_probability = 1.5",
            r"\[personal_proxy\]\.stt_weak_word_probability",
        ),
        (
            "stt_weak_word_probability = -0.1",
            r"\[personal_proxy\]\.stt_weak_word_probability",
        ),
        ('check_model = " "', r"\[personal_proxy\]\.check_model"),
        ("check_num_ctx = 0", r"\[personal_proxy\]\.check_num_ctx"),
        ("check_num_ctx = 8192.5", r"check_num_ctx must be int"),
        ("check_temperature = -0.1", r"\[personal_proxy\]\.check_temperature"),
        ("check_top_p = 0", r"\[personal_proxy\]\.check_top_p"),
        ("check_top_p = 1.1", r"\[personal_proxy\]\.check_top_p"),
        ("check_top_k = 0", r"\[personal_proxy\]\.check_top_k"),
        ("check_top_k = true", r"\[personal_proxy\]\.check_top_k"),
        ("check_top_k = 2.5", r"check_top_k must be int"),
        ("check_min_p = -0.1", r"\[personal_proxy\]\.check_min_p"),
        ("check_min_p = 1", r"\[personal_proxy\]\.check_min_p"),
        ("check_repeat_penalty = 0", r"\[personal_proxy\]\.check_repeat_penalty"),
        ("dry_run = 1", r"\[personal_proxy\]\.dry_run must be bool"),
        ("request_timeout_seconds = true", r"request_timeout_seconds must be float"),
        ('api_key = "secret"', "Unknown key"),
    ],
)
def test_section_rejects_invalid_values_naming_the_key(tmp_path, line, message):
    with pytest.raises(ConfigError, match=message):
        _load(tmp_path, f"[personal_proxy]\n{line}\n")


def test_a_rejected_key_name_value_is_not_echoed_in_the_error(tmp_path):
    pasted_key = "sk-abc123-not-a-variable-name"

    with pytest.raises(ConfigError) as raised:
        _load(tmp_path, f'[personal_proxy]\napi_key_env = "{pasted_key}"\n')

    assert pasted_key not in str(raised.value)


def test_no_field_holds_a_secret():
    secret_words = ("key", "token", "password", "secret", "credential")

    assert not [
        f.name
        for f in fields(PersonalProxySettings)
        if f.name != "api_key_env" and any(word in f.name for word in secret_words)
    ]


@pytest.mark.parametrize(
    ("endpoint", "secret"),
    [
        ("sk-SECRETKEY", "SECRETKEY"),
        ("https://u:SECRET@h/v1", "SECRET"),
        ("https://SECRET@h/v1", "SECRET"),
        ("https://h/v1?api_key=SECRET", "SECRET"),
        ("http://[bad-SECRET", "SECRET"),
        ("http:///x-SECRET", "SECRET"),
    ],
)
def test_an_unsafe_endpoint_is_rejected_without_echoing_it(tmp_path, endpoint, secret):
    with pytest.raises(ConfigError) as raised:
        _load(tmp_path, f'[personal_proxy]\nendpoint = "{endpoint}"\n')

    assert "[personal_proxy].endpoint" in str(raised.value)
    assert secret not in str(raised.value)


def test_a_wrongly_typed_endpoint_is_rejected_without_echoing_it(tmp_path):
    with pytest.raises(ConfigError) as raised:
        _load(tmp_path, "[personal_proxy]\nendpoint = 987654321\n")

    assert "[personal_proxy].endpoint" in str(raised.value)
    assert "987654321" not in str(raised.value)


@pytest.mark.parametrize(
    "key",
    [
        "request_timeout_seconds",
        "connect_timeout_seconds",
        "confirmation_timeout_seconds",
        "stt_weak_word_probability",
        "stt_min_speech_seconds",
        "check_temperature",
        "check_top_p",
        "check_min_p",
        "check_repeat_penalty",
    ],
)
@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_non_finite_numbers_are_rejected(tmp_path, key, value):
    with pytest.raises(ConfigError, match=rf"\[personal_proxy\]\.{key}"):
        _load(tmp_path, f"[personal_proxy]\n{key} = {value}\n")


def test_every_key_is_documented_in_the_example_config():
    example = EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8")
    section = example.split("[personal_proxy]", 1)[1]

    for settings_field in fields(PersonalProxySettings):
        assert re.search(rf"^{settings_field.name} = ", section, re.MULTILINE), (
            settings_field.name
        )


def test_the_example_config_loads_and_matches_the_defaults(tmp_path):
    settings = load_settings(EXAMPLE_CONFIG_PATH, ui_path=tmp_path / "none.toml")

    assert settings.personal_proxy == PersonalProxySettings()


def test_the_minimum_speech_is_labeled_unmeasured_in_the_example_config():
    example = EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8")
    before_key = example.split("stt_min_speech_seconds = ", 1)[0]
    comment_lines = []
    for line in reversed(before_key.splitlines()):
        if not line.startswith("#"):
            break
        comment_lines.append(line)

    assert "UNMEASURED" in " ".join(comment_lines)


def test_the_example_config_does_not_promise_a_dry_run_is_journaled():
    text = EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8")
    comment = text.split("dry_run = true")[0].rsplit("api_key_env", 1)[1]

    assert "journaled" not in comment
    assert "Nothing is written to" in comment
