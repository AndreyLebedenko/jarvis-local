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

from jarvis.audio.input import MicSleepToggled
from jarvis.audio.tts import TtsEngineLoadFailed, TtsSynthesisResult
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

    def subscribe(self) -> list[Subscription]:
        subscriptions: list[Subscription] = [
            (WarmupCompleted, self._on_warmup_completed),
            (BackendRequestFailed, self._on_backend_request_failed),
            (ResponseComplete, self._on_response_complete),
            (MicSleepToggled, self._on_mic_sleep_toggled),
            (TtsEngineLoadFailed, self._on_tts_engine_load_failed),
            (TtsSynthesisResult, self._on_tts_synthesis_result),
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
        if event.is_awake:
            await self._transition(
                ModuleId.MICROPHONE, HealthStatus.OK, "mic_detail_listening"
            )
        else:
            await self._transition(
                ModuleId.MICROPHONE, HealthStatus.UNAVAILABLE, "mic_detail_muted"
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

    async def _on_screenshot_captured(self, event: ScreenshotCaptured) -> None:
        del event
        await self._transition(ModuleId.VISION, HealthStatus.OK, "vision_detail_ready")

    async def _on_capture_failed(self, event: CaptureFailed) -> None:
        del event
        await self._transition(
            ModuleId.VISION, HealthStatus.ERROR, "vision_detail_failed"
        )

    async def _on_camera_state_changed(self, event: CameraStateChanged) -> None:
        await self._transition(
            ModuleId.CAMERA,
            HealthStatus.OK if event.enabled else HealthStatus.UNAVAILABLE,
            "camera_detail_ready" if event.enabled else "camera_detail_disabled",
        )

    async def _on_camera_capture_succeeded(self, event: CameraCaptureSucceeded) -> None:
        del event
        await self._transition(ModuleId.CAMERA, HealthStatus.OK, "camera_detail_ready")

    async def _on_camera_capture_failed(self, event: CameraCaptureFailed) -> None:
        del event
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
