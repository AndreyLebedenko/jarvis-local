"""Pure logic tests for the voice-intent probe parser (story-v1.9.0, task 4).

No bus, no backend, no I/O - the parser is a pure function over text, so
every fail-safe guarantee the task card requires is pinned here directly:
only the one exact marker switches; ambiguous/near-miss input always
resolves to "it was a request".
"""

from jarvis.core.config import PromptSettings
from jarvis.dialog.response_mode import ResponseMode
from jarvis.dialog.voice_intent import (
    build_probe_messages,
    intent_directive_from_settings,
    parse_mode_switch_marker,
)

# --- exact marker acceptance -----------------------------------------------


def test_exact_marker_for_each_mode_parses_to_that_mode():
    for mode in (ResponseMode.TEXT, ResponseMode.VOICE, ResponseMode.TEXT_VOICE):
        assert parse_mode_switch_marker(f"SWITCH_RESPONSE_MODE={mode.value}") is mode


def test_marker_with_surrounding_whitespace_still_parses():
    assert parse_mode_switch_marker("  SWITCH_RESPONSE_MODE=voice  ") is (
        ResponseMode.VOICE
    )


def test_marker_with_other_lines_present_still_switches():
    text = "Here is my decision:\nSWITCH_RESPONSE_MODE=text_voice\nthanks"
    assert parse_mode_switch_marker(text) is ResponseMode.TEXT_VOICE


def test_marker_with_trailing_punctuation_is_a_switch():
    assert parse_mode_switch_marker("SWITCH_RESPONSE_MODE=voice.") is None


# --- fail-safe rejections (ambiguous content resolves to "request") --------


def test_verbose_prose_about_modes_is_a_request_not_a_switch():
    text = "I understood - switching to voice mode now! SWITCH_RESPONSE_MODE maybe."
    assert parse_mode_switch_marker(text) is None


def test_empty_reply_is_a_request():
    assert parse_mode_switch_marker("") is None


def test_reply_without_any_marker_is_a_request():
    assert parse_mode_switch_marker("Прочитаю тебе инструкцию switch вслух.") is None


def test_unknown_mode_value_is_a_request():
    assert parse_mode_switch_marker("SWITCH_RESPONSE_MODE=spoken") is None


def test_two_conflicting_markers_are_ambiguous_and_resolve_to_request():
    assert (
        parse_mode_switch_marker(
            "SWITCH_RESPONSE_MODE=voice\nSWITCH_RESPONSE_MODE=text"
        )
        is None
    )


def test_two_identical_markers_are_still_ambiguous():
    """One marker is the accepted shape by construction; a doubled one is
    malformed no matter whether the values agree - refusing it keeps the
    "one line, exactly" contract honest rather than lucky."""
    assert (
        parse_mode_switch_marker(
            "SWITCH_RESPONSE_MODE=voice\nSWITCH_RESPONSE_MODE=voice"
        )
        is None
    )


def test_marker_without_the_exact_prefix_is_a_request():
    assert parse_mode_switch_marker("mode=voice") is None
    assert parse_mode_switch_marker("SWITCH RESPONSE MODE: voice") is None


# --- probe message construction --------------------------------------------


def test_probe_messages_pair_the_directive_with_the_marker_instruction():
    messages = build_probe_messages("directive text")

    assert messages == [
        {"role": "system", "content": "directive text"},
        {"role": "user", "content": "Answer with one marker word only, no other text."},
    ]


# --- settings gate (feature off by default) ---------------------------------


def test_default_settings_have_no_voice_intent_directive():
    settings = PromptSettings()

    assert settings.voice_intent_directive is None


def test_directive_resolution_is_none_by_default():
    assert intent_directive_from_settings(PromptSettings()) is None


def test_directive_resolution_passes_a_configured_directive_through():
    settings = PromptSettings(voice_intent_directive="marker contract")

    assert intent_directive_from_settings(settings) == "marker contract"


def test_blank_configured_directive_counts_as_off():
    settings = PromptSettings(voice_intent_directive="   \n  ")

    assert intent_directive_from_settings(settings) is None
