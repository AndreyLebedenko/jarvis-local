"""Single owner for module-health projection.

ModuleHealthTracker subscribes to raw signals the modules already publish
and turns them into ModuleHealthChanged events (story v1.2.14, task 2).
No polling, no probes: a module that has produced no signal yet simply
has no event, and the UI shows it as honestly unknown.

detail_key is a ui_text catalog key resolved by the renderer, which owns
the UI language - the same split as RuntimeStateChanged.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.audio.input import MicrophoneCaptureFailed, MicSleepToggled
from jarvis.audio.tts import TtsEngineLoadFailed, TtsSynthesisResult
from jarvis.audio.tts_mute import TtsSpeechEnabledChanged
from jarvis.core.bus import EventBus
from jarvis.core.lifecycle import BackendRequestFailed, WarmupCompleted
from jarvis.dialog.backend import ResponseComplete
from jarvis.inputs.camera import (
    CameraCaptureFailed,
    CameraCaptureSucceeded,
    CameraStateChanged,
)
from jarvis.inputs.capture import CaptureFailed, ScreenshotCaptured
from jarvis.ui.contract import HealthStatus, ModuleId

logger = logging.getLogger(__name__)

Subscription = tuple[type, Callable]


@dataclass(frozen=True)
class ModuleHealthChanged:
    module: ModuleId
    status: HealthStatus
    detail_key: str


class ModuleHealthTracker:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._last: dict[ModuleId, ModuleHealthChanged] = {}
        self._failed_tts_routes: set[str] = set()
        # Camera reachability is per source while the chip is per module,
        # so the unanswered sources are remembered here. Without this, one
        # working camera would report the whole module ready while another
        # stayed unreachable.
        self._unreachable_camera_sources: set[str] = set()
        # Capture failure is terminal for the session: run_microphone_loop()
        # publishes and exits, and nothing restarts it. Sleep/wake still
        # publishes MicSleepToggled - toggle_user_sleep() only sets an
        # event a loop that already exited will never observe - so without
        # this latch a mute/unmute would repaint a dead microphone as
        # "listening", which is the exact class of lie this work removed.
        self._microphone_capture_failed = False

    def subscribe(self) -> list[Subscription]:
        subscriptions: list[Subscription] = [
            (WarmupCompleted, self._on_warmup_completed),
            (BackendRequestFailed, self._on_backend_request_failed),
            (ResponseComplete, self._on_response_complete),
            (MicSleepToggled, self._on_mic_sleep_toggled),
            (MicrophoneCaptureFailed, self._on_microphone_capture_failed),
            (TtsEngineLoadFailed, self._on_tts_engine_load_failed),
            (TtsSynthesisResult, self._on_tts_synthesis_result),
            (TtsSpeechEnabledChanged, self._on_tts_speech_enabled_changed),
            (ScreenshotCaptured, self._on_screenshot_captured),
            (CaptureFailed, self._on_capture_failed),
            (CameraStateChanged, self._on_camera_state_changed),
            (CameraCaptureSucceeded, self._on_camera_capture_succeeded),
            (CameraCaptureFailed, self._on_camera_capture_failed),
        ]
        for event_type, handler in subscriptions:
            self._bus.subscribe(event_type, handler)
        return subscriptions

    async def _on_warmup_completed(self, event: WarmupCompleted) -> None:
        if event.succeeded:
            await self._transition(
                ModuleId.BACKEND, HealthStatus.OK, "backend_detail_ready"
            )
        else:
            await self._transition(
                ModuleId.BACKEND, HealthStatus.ERROR, "backend_detail_warmup_failed"
            )

    async def _on_backend_request_failed(self, event: BackendRequestFailed) -> None:
        del event
        await self._transition(
            ModuleId.BACKEND, HealthStatus.ERROR, "backend_detail_request_failed"
        )

    async def _on_response_complete(self, event: ResponseComplete) -> None:
        # A completed response is the recovery signal after any backend
        # failure; dedup keeps the steady state quiet.
        del event
        await self._transition(
            ModuleId.BACKEND, HealthStatus.OK, "backend_detail_ready"
        )

    async def _on_mic_sleep_toggled(self, event: MicSleepToggled) -> None:
        if self._microphone_capture_failed:
            return
        if event.is_awake:
            await self._transition(
                ModuleId.MICROPHONE, HealthStatus.OK, "mic_detail_listening"
            )
        else:
            await self._transition(
                ModuleId.MICROPHONE, HealthStatus.UNAVAILABLE, "mic_detail_muted"
            )

    async def _on_microphone_capture_failed(
        self, event: MicrophoneCaptureFailed
    ) -> None:
        # Terminal for the session, and latched: see the flag's comment in
        # __init__ for why no later signal may lift it. Restart is the only
        # recovery, and a restart builds a new tracker.
        del event
        self._microphone_capture_failed = True
        await self._transition(
            ModuleId.MICROPHONE, HealthStatus.ERROR, "mic_detail_capture_failed"
        )

    async def _on_tts_synthesis_result(self, event: TtsSynthesisResult) -> None:
        # A failed unit is skipped but playback continues (see TtsOutput),
        # so a failure is DEGRADED, not ERROR; the next successful unit
        # recovers.
        if self._failed_tts_routes:
            return
        if event.succeeded:
            await self._transition(ModuleId.TTS, HealthStatus.OK, "tts_detail_ready")
        else:
            await self._transition(
                ModuleId.TTS, HealthStatus.DEGRADED, "tts_detail_failed"
            )

    async def _on_tts_engine_load_failed(self, event: TtsEngineLoadFailed) -> None:
        self._failed_tts_routes.add(event.language)
        await self._transition(
            ModuleId.TTS, HealthStatus.ERROR, "tts_detail_load_failed"
        )

    async def _on_tts_speech_enabled_changed(
        self, event: TtsSpeechEnabledChanged
    ) -> None:
        # Mirrors _on_camera_state_changed/_publish_camera_reachability: an
        # explicit on/off control gets its own honest transition, distinct
        # from the synthesis-driven ready/failed signals above. While muted,
        # TtsOutput schedules no synthesis (see tts.py), so no
        # TtsSynthesisResult/TtsEngineLoadFailed can race this transition.
        if not event.enabled:
            await self._transition(
                ModuleId.TTS, HealthStatus.UNAVAILABLE, "tts_detail_muted"
            )
            return
        await self._publish_tts_status()

    async def _publish_tts_status(self) -> None:
        # Re-enabling does not claim OK for a route that never recovered -
        # same honesty rule as camera reachability on re-enable.
        if self._failed_tts_routes:
            await self._transition(
                ModuleId.TTS, HealthStatus.ERROR, "tts_detail_load_failed"
            )
            return
        await self._transition(ModuleId.TTS, HealthStatus.OK, "tts_detail_ready")

    async def _on_screenshot_captured(self, event: ScreenshotCaptured) -> None:
        del event
        await self._transition(ModuleId.VISION, HealthStatus.OK, "vision_detail_ready")

    async def _on_capture_failed(self, event: CaptureFailed) -> None:
        del event
        await self._transition(
            ModuleId.VISION, HealthStatus.ERROR, "vision_detail_failed"
        )

    async def _on_camera_state_changed(self, event: CameraStateChanged) -> None:
        self._unreachable_camera_sources = set(event.unreachable_sources)
        if not event.enabled:
            await self._transition(
                ModuleId.CAMERA, HealthStatus.UNAVAILABLE, "camera_detail_disabled"
            )
            return
        await self._publish_camera_reachability()

    async def _on_camera_capture_succeeded(self, event: CameraCaptureSucceeded) -> None:
        # A frame proves only its own source reachable. Clearing the whole
        # module on any success would let a USB capture hide a LAN camera
        # that never answered.
        self._unreachable_camera_sources.discard(event.source)
        await self._publish_camera_reachability()

    async def _publish_camera_reachability(self) -> None:
        if self._unreachable_camera_sources:
            await self._transition(
                ModuleId.CAMERA, HealthStatus.DEGRADED, "camera_detail_partial"
            )
            return
        await self._transition(ModuleId.CAMERA, HealthStatus.OK, "camera_detail_ready")

    async def _on_camera_capture_failed(self, event: CameraCaptureFailed) -> None:
        # Remembered for the same reason as above, mirrored: once a source
        # has failed, a frame from a different camera returns the module to
        # degraded, never to ready.
        if event.source:
            self._unreachable_camera_sources.add(event.source)
        await self._transition(
            ModuleId.CAMERA, HealthStatus.ERROR, "camera_detail_failed"
        )

    async def _transition(
        self, module: ModuleId, status: HealthStatus, detail_key: str
    ) -> None:
        changed = ModuleHealthChanged(
            module=module, status=status, detail_key=detail_key
        )
        if self._last.get(module) == changed:
            return
        self._last[module] = changed
        await self._bus.publish(ModuleHealthChanged, changed)
