import pytest

from jarvis.core.config import CameraSettings, DataBoundary
from jarvis.inputs.camera import (
    CameraCapture,
    CameraDisabledError,
    CameraError,
    CameraState,
)


class FakeBackend:
    def __init__(self, result: bytes | Exception) -> None:
        self.result = result
        self.calls: list[tuple[int, int, int, str]] = []
        self.probe_calls: list[int] = []

    def probe_usb(self, device_index: int) -> None:
        self.probe_calls.append(device_index)
        if isinstance(self.result, Exception):
            raise self.result

    def capture_usb(
        self, device_index: int, width: int, height: int, fourcc: str
    ) -> bytes:
        self.calls.append((device_index, width, height, fourcc))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.asyncio
async def test_camera_capture_returns_local_usb_frame_with_configured_device():
    backend = FakeBackend(b"jpeg")
    capture = CameraCapture(
        CameraSettings(usb_device_index=2, frame_width=640, frame_height=480),
        CameraState(True),
        backend,
        clock=lambda: 123.0,
    )

    frame = await capture.capture()

    assert frame.jpeg_bytes == b"jpeg"
    assert frame.captured_at == 123.0
    assert frame.source == "usb"
    assert frame.data_boundary is DataBoundary.LOCAL
    assert backend.calls == [(2, 640, 480, "MJPG")]


@pytest.mark.asyncio
async def test_camera_capture_does_not_touch_backend_when_privacy_switch_is_off():
    backend = FakeBackend(b"jpeg")
    capture = CameraCapture(CameraSettings(), CameraState(False), backend)

    with pytest.raises(CameraDisabledError, match="off"):
        await capture.capture()

    assert backend.calls == []


@pytest.mark.asyncio
async def test_camera_capture_surfaces_backend_failure_without_empty_frame():
    capture = CameraCapture(
        CameraSettings(), CameraState(True), FakeBackend(CameraError("unavailable"))
    )

    with pytest.raises(CameraError, match="unavailable"):
        await capture.capture()


@pytest.mark.asyncio
async def test_camera_probe_reports_a_missing_configured_device_without_capturing():
    backend = FakeBackend(CameraError("USB camera could not be opened"))
    capture = CameraCapture(
        CameraSettings(usb_device_index=2), CameraState(False), backend
    )

    with pytest.raises(CameraError, match="could not be opened"):
        await capture.probe()

    assert backend.probe_calls == [2]
    assert backend.calls == []
