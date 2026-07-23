"""Single-frame capture from named USB and LAN camera sources, behind a
hardware-free backend seam."""

import asyncio
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

from jarvis.core.config import (
    CameraSettings,
    CameraSource,
    DataBoundary,
    LanCameraSource,
    normalized_source_name,
)


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


class UnknownCameraSourceError(CameraError):
    """Names a source no configuration describes. Distinct from a capture
    failure: nothing was attempted, and no camera was touched."""


@dataclass(frozen=True)
class CameraFrame:
    jpeg_bytes: bytes
    captured_at: float
    source: str = "usb"
    data_boundary: DataBoundary = DataBoundary.LOCAL


def rtsp_url(source: LanCameraSource) -> str:
    """The single place an RTSP URL is assembled. Credentials are
    percent-encoded here so the human writes a password literally, however
    many URL-reserved characters it contains (PROJECT.md, 2026-07-22)."""
    credentials = ""
    if source.user or source.password:
        user = quote(source.user, safe="")
        password = quote(source.password, safe="")
        credentials = f"{user}:{password}@"
    path = source.stream_path
    if not path.startswith("/"):
        path = f"/{path}"
    return f"rtsp://{credentials}{source.host}:{source.port}{path}"


def describe_source(source: CameraSource) -> str:
    """Credential-free identification of a source for logs, events, and
    error messages. An assembled RTSP URL must never reach any of them."""
    if isinstance(source, LanCameraSource):
        return f"{source.name} (LAN {source.host}:{source.port})"
    return f"{source.name} (USB device {source.device_index})"


def source_data_boundary(source: CameraSource) -> DataBoundary:
    if isinstance(source, LanCameraSource):
        return DataBoundary.LAN
    return DataBoundary.LOCAL


class CameraBackend(Protocol):
    def probe_usb(self, device_index: int) -> None: ...

    def capture_usb(
        self, device_index: int, width: int, height: int, fourcc: str
    ) -> bytes: ...

    def probe_lan(self, url: str, timeout_seconds: float) -> None: ...

    def capture_lan(self, url: str, timeout_seconds: float) -> bytes: ...


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
    def probe_usb(self, device_index: int) -> None:
        import cv2

        camera = cv2.VideoCapture(device_index, cv2.CAP_DSHOW)
        try:
            if not camera.isOpened():
                raise CameraError("USB camera could not be opened")
        finally:
            camera.release()

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

    def probe_lan(self, url: str, timeout_seconds: float) -> None:
        with self._open_rtsp(url, timeout_seconds):
            return

    def capture_lan(self, url: str, timeout_seconds: float) -> bytes:
        import cv2

        with self._open_rtsp(url, timeout_seconds) as stream:
            try:
                ok, frame = stream.read()
                if not ok:
                    raise CameraError("LAN camera did not provide a frame")
                encoded, jpeg = cv2.imencode(".jpg", frame)
                if not encoded:
                    raise CameraError("LAN camera frame could not be encoded")
                return bytes(jpeg)
            except CameraError:
                raise
            except Exception:
                # Deliberately unchained: an OpenCV/FFMPEG failure message
                # can quote the stream URL, which carries the password.
                raise CameraError("LAN camera frame could not be read") from None

    @contextmanager
    def _open_rtsp(self, url: str, timeout_seconds: float) -> Iterator[Any]:
        import cv2

        # RTSP over TCP rather than the ffmpeg default, so blocked UDP fails
        # instead of stalling.
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        # OpenCV's own open/read timeouts, not ffmpeg's `timeout` option:
        # verified on 2026-07-23 against an unreachable host, where the
        # ffmpeg option was ignored and OpenCV's 30 s default kept the
        # capture thread alive long after the asyncio timeout - which can
        # abandon that thread but never cancel it - had already given up.
        timeout_ms = max(1, int(timeout_seconds * 1000))
        try:
            stream = cv2.VideoCapture(
                url,
                cv2.CAP_FFMPEG,
                [
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                    timeout_ms,
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                    timeout_ms,
                ],
            )
        except Exception:
            raise CameraError("LAN camera stream could not be opened") from None
        try:
            if not stream.isOpened():
                raise CameraError("LAN camera stream could not be opened")
            yield stream
        finally:
            stream.release()


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

    @property
    def sources(self) -> tuple[CameraSource, ...]:
        return self._settings.resolved_sources

    async def capture(self, source_name: str | None = None) -> CameraFrame:
        if not self._state.enabled:
            raise CameraDisabledError("Camera is off")
        source = self._source(source_name)
        jpeg_bytes = await self._run("capture", source, *self._capture_call(source))
        if not self._state.enabled:
            raise CameraDisabledError("Camera was turned off during capture")
        return CameraFrame(
            jpeg_bytes=jpeg_bytes,
            captured_at=self._clock(),
            source=source.name,
            data_boundary=source_data_boundary(source),
        )

    async def probe(self, source_name: str | None = None) -> None:
        source = self._source(source_name)
        await self._run("probe", source, *self._probe_call(source))

    def _source(self, source_name: str | None) -> CameraSource:
        sources = self.sources
        if source_name is None:
            return sources[0]
        wanted = normalized_source_name(source_name)
        for source in sources:
            if normalized_source_name(source.name) == wanted:
                return source
        known = ", ".join(source.name for source in sources)
        raise UnknownCameraSourceError(
            f"Unknown camera source: {source_name!r}. Configured sources: {known}"
        )

    def _capture_call(
        self, source: CameraSource
    ) -> tuple[Callable[..., bytes], tuple[Any, ...]]:
        if isinstance(source, LanCameraSource):
            return self._backend.capture_lan, (
                rtsp_url(source),
                self._settings.capture_timeout_seconds,
            )
        return self._backend.capture_usb, (
            source.device_index,
            self._settings.frame_width,
            self._settings.frame_height,
            self._settings.fourcc,
        )

    def _probe_call(
        self, source: CameraSource
    ) -> tuple[Callable[..., None], tuple[Any, ...]]:
        if isinstance(source, LanCameraSource):
            return self._backend.probe_lan, (
                rtsp_url(source),
                self._settings.capture_timeout_seconds,
            )
        return self._backend.probe_usb, (source.device_index,)

    async def _run(
        self,
        action: str,
        source: CameraSource,
        call: Callable[..., Any],
        arguments: tuple[Any, ...],
    ) -> Any:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(call, *arguments),
                timeout=self._settings.capture_timeout_seconds,
            )
        except TimeoutError as exc:
            raise CameraError(
                f"Camera {action} timed out for source {describe_source(source)}"
            ) from exc
        except CameraError as exc:
            raise CameraError(
                f"Camera {action} failed for source {describe_source(source)}: {exc}"
            ) from exc
