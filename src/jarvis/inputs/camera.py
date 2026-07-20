"""USB camera single-frame capture behind a hardware-free backend seam."""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from jarvis.core.config import CameraSettings, DataBoundary


@dataclass(frozen=True)
class CameraStateChanged:
    enabled: bool


@dataclass(frozen=True)
class CameraCaptureSucceeded:
    pass


@dataclass(frozen=True)
class CameraCaptureFailed:
    pass


class CameraError(Exception):
    pass


class CameraDisabledError(CameraError):
    pass


@dataclass(frozen=True)
class CameraFrame:
    jpeg_bytes: bytes
    captured_at: float
    source: str = "usb"
    data_boundary: DataBoundary = DataBoundary.LOCAL


class CameraBackend(Protocol):
    def capture_usb(
        self, device_index: int, width: int, height: int, fourcc: str
    ) -> bytes: ...


class CameraState:
    """The single runtime authority for the camera privacy switch."""

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled


class OpenCvCameraBackend:
    def capture_usb(
        self, device_index: int, width: int, height: int, fourcc: str
    ) -> bytes:
        import cv2

        camera = cv2.VideoCapture(device_index, cv2.CAP_DSHOW)
        try:
            if not camera.isOpened():
                raise CameraError("USB camera could not be opened")
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
            ok, frame = camera.read()
            if not ok:
                raise CameraError("USB camera did not provide a frame")
            encoded, jpeg = cv2.imencode(".jpg", frame)
            if not encoded:
                raise CameraError("USB camera frame could not be encoded")
            return bytes(jpeg)
        finally:
            camera.release()


class CameraCapture:
    def __init__(
        self,
        settings: CameraSettings,
        state: CameraState,
        backend: CameraBackend | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._state = state
        self._backend = backend or OpenCvCameraBackend()
        self._clock = clock

    async def capture(self) -> CameraFrame:
        if not self._state.enabled:
            raise CameraDisabledError("Camera is off")
        try:
            jpeg_bytes = await asyncio.wait_for(
                asyncio.to_thread(
                    self._backend.capture_usb,
                    self._settings.usb_device_index,
                    self._settings.frame_width,
                    self._settings.frame_height,
                    self._settings.fourcc,
                ),
                timeout=self._settings.capture_timeout_seconds,
            )
        except TimeoutError as exc:
            raise CameraError("USB camera capture timed out") from exc
        if not self._state.enabled:
            raise CameraDisabledError("Camera was turned off during capture")
        return CameraFrame(jpeg_bytes=jpeg_bytes, captured_at=self._clock())
