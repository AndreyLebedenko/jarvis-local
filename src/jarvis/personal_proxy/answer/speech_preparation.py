"""How a restored sentence is made ready for the speaker in each response mode.
Text speaks the sentence as received; Voice cleans it first. The shown text is
never touched."""

from __future__ import annotations

from collections.abc import Callable

from jarvis.personal_proxy.answer.speech_cleanup import clean_for_speech
from jarvis.personal_proxy.common.response_mode import VOICE_MODE
from jarvis.personal_proxy.common.speech_tags import strip_speech_control_tags

SpeechPreparation = Callable[[str], str]


def as_received(sentence: str) -> str:
    return sentence


def cleaned_for_voice(sentence: str) -> str:
    return clean_for_speech(strip_speech_control_tags(sentence))


def speech_preparation_of(response_mode: str) -> SpeechPreparation:
    return cleaned_for_voice if response_mode == VOICE_MODE else as_received
