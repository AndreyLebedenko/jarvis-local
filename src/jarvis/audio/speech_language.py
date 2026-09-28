"""Per-pass speech-language policy ([tts].language_mode).

Decides which language TtsOutput expects to voice an answer in, and which
directive tells the model so. Both the mode and the request language are
arguments, not state: a live toggle only needs an owner that supplies the
current mode per turn, and another language source (for example the
language of the previous answer) only needs to supply a different
`request_language`.
"""

import enum

from jarvis.audio.language_segments import DEFAULT_LANGUAGE, ENGLISH
from jarvis.core.config import ResponseSettings
from jarvis.core.lifecycle import (
    CharsetSpeechRouting,
    SingleLanguageSpeech,
    SpeechLanguage,
)


class TtsLanguageMode(enum.Enum):
    DYNAMIC = "dynamic"
    REQUEST = "request"
    RUSSIAN = "ru"
    ENGLISH = "en"


def resolve_speech_language(
    mode: TtsLanguageMode, request_language: str | None
) -> SpeechLanguage:
    """`request_language` is what request mode follows; None when it is not
    known before the answer (a voice request)."""
    if mode is TtsLanguageMode.DYNAMIC:
        return CharsetSpeechRouting()
    if mode is TtsLanguageMode.REQUEST:
        return SingleLanguageSpeech(request_language)
    return SingleLanguageSpeech(mode.value)


def speech_language_contract(
    speech_language: SpeechLanguage, settings: ResponseSettings
) -> str | None:
    if isinstance(speech_language, CharsetSpeechRouting):
        return None
    if speech_language.language == DEFAULT_LANGUAGE:
        return settings.speech_language_ru
    if speech_language.language == ENGLISH:
        return settings.speech_language_en
    return settings.speech_language_request
