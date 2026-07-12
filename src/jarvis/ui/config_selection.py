"""Configuration-iteration-2 selection shape and validation.

One pure module shared by the command handler (payload semantics) and
StatusConsoleApi (backstop before write_ui_config), so both sides of the
"defense on both sides" rule run the same checks. The front-end mirrors
the same ranges in JS; this module is the authority.

Ranges are deliberately wide sanity bounds, not tuning advice: they stop
a typo (threshold 5.0, pause 200 s) from being written into the config,
nothing more.
"""

from dataclasses import dataclass

from jarvis.core.config import (
    SUPPORTED_TTS_LANGUAGES,
    SUPPORTED_UI_LANGUAGES,
    ConfigError,
    TtsLanguageSettings,
    VadSettings,
    validate_tts_route,
)

VAD_THRESHOLD_RANGE = (0.0, 1.0)  # exclusive bounds: silence/always-on are typos
VAD_MAX_CHUNK_RANGE = (1, 120)
VAD_REQUEST_END_PAUSE_RANGE = (0.1, 10.0)
VAD_RESUME_COOLDOWN_RANGE = (0.0, 10.0)


@dataclass(frozen=True)
class UiConfigSelection:
    model: str
    microphone_device: str
    ui_language: str | None = None
    vad: VadSettings | None = None
    # All-or-nothing: a customized route table must cover every supported
    # language (build_tts_engine's coverage rule); None keeps the
    # Silero-only default.
    tts_routes: dict[str, TtsLanguageSettings] | None = None


def validate_selection(selection: UiConfigSelection) -> list[str]:
    """Returns human-readable English problems; empty list means valid."""
    problems: list[str] = []
    if not selection.model.strip():
        problems.append("model must not be empty")
    if (
        selection.ui_language is not None
        and selection.ui_language not in SUPPORTED_UI_LANGUAGES
    ):
        supported = ", ".join(SUPPORTED_UI_LANGUAGES)
        problems.append(
            f"ui_language must be one of: {supported}; got {selection.ui_language!r}"
        )
    if selection.vad is not None:
        problems.extend(_validate_vad(selection.vad))
    if selection.tts_routes is not None:
        problems.extend(_validate_tts_routes(selection.tts_routes))
    return problems


def _validate_vad(vad: VadSettings) -> list[str]:
    problems: list[str] = []
    low, high = VAD_THRESHOLD_RANGE
    if not low < vad.threshold < high:
        problems.append(
            f"vad.threshold must be between {low} and {high} exclusive; "
            f"got {vad.threshold}"
        )
    low, high = VAD_MAX_CHUNK_RANGE
    if not low <= vad.max_chunk_seconds <= high:
        problems.append(
            f"vad.max_chunk_seconds must be between {low} and {high}; "
            f"got {vad.max_chunk_seconds}"
        )
    low, high = VAD_REQUEST_END_PAUSE_RANGE
    if not low <= vad.request_end_pause_seconds <= high:
        problems.append(
            f"vad.request_end_pause_seconds must be between {low} and {high}; "
            f"got {vad.request_end_pause_seconds}"
        )
    low, high = VAD_RESUME_COOLDOWN_RANGE
    if not low <= vad.resume_cooldown_seconds <= high:
        problems.append(
            f"vad.resume_cooldown_seconds must be between {low} and {high}; "
            f"got {vad.resume_cooldown_seconds}"
        )
    return problems


def _validate_tts_routes(routes: dict[str, TtsLanguageSettings]) -> list[str]:
    problems: list[str] = []
    if set(routes) != set(SUPPORTED_TTS_LANGUAGES):
        required = ", ".join(sorted(SUPPORTED_TTS_LANGUAGES))
        got = ", ".join(sorted(routes)) or "nothing"
        problems.append(
            "tts_routes must cover exactly the supported languages "
            f"({required}); got {got}. Charset segmentation emits every "
            "supported language regardless of configuration."
        )
    for language, route in sorted(routes.items()):
        try:
            validate_tts_route(language, route)
        except ConfigError as exc:
            problems.append(str(exc))
    return problems
