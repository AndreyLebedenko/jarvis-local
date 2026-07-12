"""Composition root for configured TTS engine routes."""

from typing import Protocol

from jarvis.audio.language_segments import DEFAULT_LANGUAGE, ENGLISH
from jarvis.audio.tts import BilingualTtsEngine, TtsEngine
from jarvis.audio.tts_piper import PiperEngine
from jarvis.audio.tts_silero import SileroEngine
from jarvis.core.config import (
    PiperTtsSettings,
    SileroTtsSettings,
    TtsLanguageSettings,
    TtsSettings,
)

_ROUTED_LANGUAGES = (DEFAULT_LANGUAGE, ENGLISH)


class EngineBuilder(Protocol):
    def __call__(self, route: TtsLanguageSettings) -> TtsEngine: ...


def _build_silero(route: TtsLanguageSettings) -> TtsEngine:
    if not isinstance(route, SileroTtsSettings):
        raise TypeError("Silero builder requires SileroTtsSettings")
    return SileroEngine(route)


def _build_piper(route: TtsLanguageSettings) -> TtsEngine:
    if not isinstance(route, PiperTtsSettings):
        raise TypeError("Piper builder requires PiperTtsSettings")
    return PiperEngine(route)


def default_engine_builders() -> dict[str, EngineBuilder]:
    return {
        "silero": _build_silero,
        "piper": _build_piper,
    }


def build_tts_engine(
    settings: TtsSettings,
    engine_builders: dict[str, EngineBuilder] | None = None,
) -> TtsEngine:
    if settings.languages == {DEFAULT_LANGUAGE: SileroTtsSettings()}:
        return SileroEngine(SileroTtsSettings())

    missing = [
        language for language in _ROUTED_LANGUAGES if language not in settings.languages
    ]
    if missing:
        raise ValueError(
            "Configured TTS language routes must cover "
            f"{', '.join(_ROUTED_LANGUAGES)}: charset segmentation emits all "
            f"of them regardless of configuration. Missing: {', '.join(missing)}. "
            "Add the missing [tts.languages.*] route or remove the section to "
            "use the Silero-only default."
        )

    builders = engine_builders or default_engine_builders()
    engines: dict[str, TtsEngine] = {}
    for language, route in settings.languages.items():
        try:
            builder = builders[route.engine]
        except KeyError as exc:
            available = ", ".join(sorted(builders))
            raise ValueError(
                f"Unsupported TTS engine for configured routing: {route.engine!r}. "
                f"Available builders: {available}"
            ) from exc
        engines[language] = builder(route)
    return BilingualTtsEngine(engines)
