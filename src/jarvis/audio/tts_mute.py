"""Runtime TTS speech-enabled state (task-ui-ux-3).

Owns whether Jarvis speaks at all - distinct from TtsEngineLoadFailed
(engine-side failure) and from a route's per-language configuration. Mutes
speech only; SoundCuePlayer is untouched (see tts.py's TtsOutput gating and
sound_cues.py). Mirrors VisibilityModeState/ReasoningLevelState: a small,
single-responsibility bus-publishing state owner with no persistence
responsibility of its own - startup seeds the initial value from
`settings.tts.enabled`, and toggling here never rewrites config (task card's
settled sub-decision: the runtime mute is not self-persisting).
"""

from dataclasses import dataclass

from jarvis.core.bus import EventBus


@dataclass(frozen=True)
class TtsSpeechEnabledChanged:
    enabled: bool


class TtsMuteState:
    def __init__(self, bus: EventBus, *, enabled: bool = True) -> None:
        self._bus = bus
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def set_enabled(self, enabled: bool) -> None:
        if enabled == self._enabled:
            return
        self._enabled = enabled
        await self._bus.publish(
            TtsSpeechEnabledChanged, TtsSpeechEnabledChanged(enabled=enabled)
        )
