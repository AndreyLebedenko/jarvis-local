"""Catalog completeness and lookup behavior for ui_text.py."""

import pytest

from jarvis.ui.contract import ModuleId, RuntimeState
from jarvis.ui.text import (
    _MESSAGES,
    _MODULE_LABELS,
    _RUNTIME_STATE_TEXT,
    DEFAULT_UI_LANGUAGE,
    SUPPORTED_UI_LANGUAGES,
    module_label,
    runtime_state_text,
    ui_text,
)


def test_default_language_is_english():
    assert DEFAULT_UI_LANGUAGE == "en"
    assert DEFAULT_UI_LANGUAGE in SUPPORTED_UI_LANGUAGES


def test_catalog_agrees_with_config_module_literals():
    """config.py must not import project modules, so it repeats the
    supported set and the default as literals; this pins the two modules
    together."""
    from jarvis.core import config

    assert tuple(config.SUPPORTED_UI_LANGUAGES) == tuple(SUPPORTED_UI_LANGUAGES)
    assert config.UiSettings().language == DEFAULT_UI_LANGUAGE


@pytest.mark.parametrize("language", SUPPORTED_UI_LANGUAGES)
def test_every_runtime_state_has_text_in_every_language(language):
    for state in RuntimeState:
        label, substatus = runtime_state_text(state, language)
        assert isinstance(label, str) and label
        assert isinstance(substatus, str)


@pytest.mark.parametrize("language", SUPPORTED_UI_LANGUAGES)
def test_every_module_has_a_label_in_every_language(language):
    for module in ModuleId:
        assert module_label(module, language)


def test_listening_runtime_state_describes_engine_readiness_not_microphone_state():
    assert runtime_state_text(RuntimeState.LISTENING, "en") == (
        "Ready",
        "Waiting for a request",
    )
    assert runtime_state_text(RuntimeState.LISTENING, "ru") == (
        "Готов",
        "Ожидаю запрос",
    )
    assert ui_text("ready_to_listen", "en") == "Waiting for a request"
    assert ui_text("ready_to_listen", "ru") == "Ожидаю запрос"


def test_all_catalogs_cover_exactly_the_supported_languages():
    expected = set(SUPPORTED_UI_LANGUAGES)
    assert set(_RUNTIME_STATE_TEXT) == expected
    assert set(_MODULE_LABELS) == expected
    assert set(_MESSAGES) == expected


def test_every_message_key_exists_in_every_language():
    key_sets = {language: set(keys) for language, keys in _MESSAGES.items()}
    reference = key_sets[DEFAULT_UI_LANGUAGE]
    assert all(keys == reference for keys in key_sets.values())


def test_message_lookup_formats_arguments():
    message = ui_text("module_reset_unsupported", "en", module="memory")
    assert message == "Reset of memory requested, but not supported by the engine yet"


def test_russian_wording_preserves_v1_2_10_muted_microphone_detail():
    assert ui_text("mic_detail_muted", "ru") == "не используется"


def test_unknown_language_raises_key_error():
    with pytest.raises(KeyError):
        ui_text("context_reset", "de")
