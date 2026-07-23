"""ModuleHealthTracker: authoritative module-health events only."""

from jarvis.audio.input import MicSleepToggled
from jarvis.audio.tts import TtsEngineLoadFailed, TtsSynthesisResult
from jarvis.core.bus import EventBus
from jarvis.core.lifecycle import BackendRequestFailed, WarmupCompleted
from jarvis.dialog.backend import LatencyMetrics, ResponseComplete
from jarvis.inputs.camera import (
    CameraCaptureFailed,
    CameraCaptureSucceeded,
    CameraStateChanged,
)
from jarvis.inputs.capture import CaptureFailed, ScreenshotCaptured
from jarvis.ui.contract import HealthStatus, ModuleId
from jarvis.ui.module_health import ModuleHealthChanged, ModuleHealthTracker


class _Recorder:
    def __init__(self, bus: EventBus) -> None:
        self.events: list[ModuleHealthChanged] = []
        bus.subscribe(ModuleHealthChanged, self._on_changed)

    async def _on_changed(self, event: ModuleHealthChanged) -> None:
        self.events.append(event)


def _tracked_bus() -> tuple[EventBus, _Recorder]:
    bus = EventBus()
    ModuleHealthTracker(bus).subscribe()
    return bus, _Recorder(bus)


def _response_complete() -> ResponseComplete:
    return ResponseComplete(metrics=LatencyMetrics(0.0, 0.0, 0.0, 1))


async def test_successful_warmup_reports_backend_ok():
    bus, recorder = _tracked_bus()

    await bus.publish(WarmupCompleted, WarmupCompleted(succeeded=True))

    assert recorder.events == [
        ModuleHealthChanged(
            module=ModuleId.BACKEND,
            status=HealthStatus.OK,
            detail_key="backend_detail_ready",
        )
    ]


async def test_failed_warmup_reports_backend_error():
    bus, recorder = _tracked_bus()

    await bus.publish(WarmupCompleted, WarmupCompleted(succeeded=False))

    assert recorder.events[-1].module is ModuleId.BACKEND
    assert recorder.events[-1].status is HealthStatus.ERROR
    assert recorder.events[-1].detail_key == "backend_detail_warmup_failed"


async def test_backend_recovers_to_ok_on_next_completed_turn():
    bus, recorder = _tracked_bus()

    await bus.publish(BackendRequestFailed, BackendRequestFailed())
    await bus.publish(ResponseComplete, _response_complete())

    assert [(e.status, e.detail_key) for e in recorder.events] == [
        (HealthStatus.ERROR, "backend_detail_request_failed"),
        (HealthStatus.OK, "backend_detail_ready"),
    ]


async def test_repeated_completed_turns_publish_backend_ok_once():
    bus, recorder = _tracked_bus()

    await bus.publish(ResponseComplete, _response_complete())
    await bus.publish(ResponseComplete, _response_complete())

    assert len(recorder.events) == 1


async def test_mic_toggle_maps_to_the_existing_health_vocabulary():
    bus, recorder = _tracked_bus()

    await bus.publish(MicSleepToggled, MicSleepToggled(is_awake=False))
    await bus.publish(MicSleepToggled, MicSleepToggled(is_awake=True))

    assert [(e.module, e.status, e.detail_key) for e in recorder.events] == [
        (ModuleId.MICROPHONE, HealthStatus.UNAVAILABLE, "mic_detail_muted"),
        (ModuleId.MICROPHONE, HealthStatus.OK, "mic_detail_listening"),
    ]


async def test_tts_unit_failure_degrades_and_next_success_recovers():
    bus, recorder = _tracked_bus()

    await bus.publish(
        TtsSynthesisResult, TtsSynthesisResult(language="ru", succeeded=True)
    )
    await bus.publish(
        TtsSynthesisResult, TtsSynthesisResult(language="en", succeeded=False)
    )
    await bus.publish(
        TtsSynthesisResult, TtsSynthesisResult(language="ru", succeeded=True)
    )

    assert [(e.module, e.status) for e in recorder.events] == [
        (ModuleId.TTS, HealthStatus.OK),
        (ModuleId.TTS, HealthStatus.DEGRADED),
        (ModuleId.TTS, HealthStatus.OK),
    ]
    assert recorder.events[1].detail_key == "tts_detail_failed"


async def test_tts_engine_load_failure_is_an_error():
    bus, recorder = _tracked_bus()

    await bus.publish(
        TtsEngineLoadFailed,
        TtsEngineLoadFailed(
            language="en",
            engine="piper",
            model="voices/en.onnx",
            message="model file missing",
        ),
    )

    assert [(e.module, e.status, e.detail_key) for e in recorder.events] == [
        (ModuleId.TTS, HealthStatus.ERROR, "tts_detail_load_failed")
    ]


async def test_success_on_another_route_does_not_hide_terminal_load_failure():
    bus, recorder = _tracked_bus()

    await bus.publish(
        TtsEngineLoadFailed,
        TtsEngineLoadFailed(
            language="en",
            engine="piper",
            model="voices/en.onnx",
            message="model file missing",
        ),
    )
    await bus.publish(
        TtsSynthesisResult, TtsSynthesisResult(language="ru", succeeded=True)
    )

    assert [(e.module, e.status) for e in recorder.events] == [
        (ModuleId.TTS, HealthStatus.ERROR)
    ]


async def test_screenshot_outcomes_drive_vision_health():
    bus, recorder = _tracked_bus()

    await bus.publish(
        ScreenshotCaptured,
        ScreenshotCaptured(png_bytes=b"png", width=1, height=1, mode="full"),
    )
    await bus.publish(CaptureFailed, CaptureFailed(mode="region"))

    assert [(e.module, e.status) for e in recorder.events] == [
        (ModuleId.VISION, HealthStatus.OK),
        (ModuleId.VISION, HealthStatus.ERROR),
    ]


async def test_no_signal_publishes_nothing():
    _bus, recorder = _tracked_bus()

    assert recorder.events == []


async def test_camera_enabled_with_every_source_answering_reports_ok():
    bus, recorder = _tracked_bus()

    await bus.publish(CameraStateChanged, CameraStateChanged(enabled=True))

    assert [(e.module, e.status, e.detail_key) for e in recorder.events] == [
        (ModuleId.CAMERA, HealthStatus.OK, "camera_detail_ready")
    ]


async def test_camera_with_an_unreachable_source_never_claims_ready():
    """A LAN camera can be configured, enabled, and simply not answering -
    a condition an unplugged USB device does not have. The module still
    works through its other sources, so it is neither ready nor failed."""
    bus, recorder = _tracked_bus()

    await bus.publish(
        CameraStateChanged,
        CameraStateChanged(enabled=True, unreachable_sources=("wide",)),
    )

    assert [(e.module, e.status, e.detail_key) for e in recorder.events] == [
        (ModuleId.CAMERA, HealthStatus.DEGRADED, "camera_detail_partial")
    ]


async def test_a_frame_from_one_camera_does_not_clear_another_that_is_unreachable():
    bus, recorder = _tracked_bus()

    await bus.publish(
        CameraStateChanged,
        CameraStateChanged(enabled=True, unreachable_sources=("wide",)),
    )
    await bus.publish(CameraCaptureSucceeded, CameraCaptureSucceeded("desk"))

    assert [(e.status, e.detail_key) for e in recorder.events] == [
        (HealthStatus.DEGRADED, "camera_detail_partial")
    ]


async def test_a_frame_from_the_unreachable_camera_itself_restores_ready():
    bus, recorder = _tracked_bus()

    await bus.publish(
        CameraStateChanged,
        CameraStateChanged(enabled=True, unreachable_sources=("wide",)),
    )
    await bus.publish(CameraCaptureSucceeded, CameraCaptureSucceeded("wide"))

    assert [(e.status, e.detail_key) for e in recorder.events] == [
        (HealthStatus.DEGRADED, "camera_detail_partial"),
        (HealthStatus.OK, "camera_detail_ready"),
    ]


async def test_a_failed_source_keeps_the_module_degraded_after_another_succeeds():
    bus, recorder = _tracked_bus()

    await bus.publish(CameraStateChanged, CameraStateChanged(enabled=True))
    await bus.publish(CameraCaptureFailed, CameraCaptureFailed("wide"))
    await bus.publish(CameraCaptureSucceeded, CameraCaptureSucceeded("desk"))

    assert [(e.status, e.detail_key) for e in recorder.events] == [
        (HealthStatus.OK, "camera_detail_ready"),
        (HealthStatus.ERROR, "camera_detail_failed"),
        (HealthStatus.DEGRADED, "camera_detail_partial"),
    ]
