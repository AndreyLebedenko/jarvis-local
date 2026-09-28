import pytest

from jarvis.audio.speech_language import (
    TtsLanguageMode,
    resolve_speech_language,
    speech_language_contract,
)
from jarvis.core.config import SUPPORTED_TTS_LANGUAGE_MODES, ResponseSettings
from jarvis.core.lifecycle import CharsetSpeechRouting, SingleLanguageSpeech

_SETTINGS = ResponseSettings(
    speech_language_ru="speak russian",
    speech_language_en="speak english",
    speech_language_request="speak the question's language",
)


def test_mode_values_match_the_config_contract():
    assert tuple(mode.value for mode in TtsLanguageMode) == (
        SUPPORTED_TTS_LANGUAGE_MODES
    )


@pytest.mark.parametrize("request_language", ["ru", "en", None])
def test_dynamic_mode_keeps_charset_routing(request_language):
    assert (
        resolve_speech_language(TtsLanguageMode.DYNAMIC, request_language)
        == CharsetSpeechRouting()
    )


@pytest.mark.parametrize(
    ("mode", "language"),
    [(TtsLanguageMode.RUSSIAN, "ru"), (TtsLanguageMode.ENGLISH, "en")],
)
def test_a_fixed_mode_ignores_the_request_language(mode, language):
    assert resolve_speech_language(mode, "en" if language == "ru" else "ru") == (
        SingleLanguageSpeech(language)
    )


@pytest.mark.parametrize("request_language", ["ru", "en", None])
def test_request_mode_expects_the_request_language(request_language):
    assert resolve_speech_language(
        TtsLanguageMode.REQUEST, request_language
    ) == SingleLanguageSpeech(request_language)


def test_charset_routing_tells_the_model_nothing():
    assert speech_language_contract(CharsetSpeechRouting(), _SETTINGS) is None


@pytest.mark.parametrize(
    ("speech_language", "contract"),
    [
        (SingleLanguageSpeech("ru"), "speak russian"),
        (SingleLanguageSpeech("en"), "speak english"),
        (SingleLanguageSpeech(None), "speak the question's language"),
    ],
)
def test_a_single_language_selects_its_directive(speech_language, contract):
    assert speech_language_contract(speech_language, _SETTINGS) == contract
