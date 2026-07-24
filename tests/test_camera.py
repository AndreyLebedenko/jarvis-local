import asyncio
import threading
from urllib.parse import unquote, urlsplit

import pytest

from jarvis.core.config import (
    CameraSettings,
    DataBoundary,
    LanCameraSource,
    UsbCameraSource,
)
from jarvis.inputs.camera import (
    CameraCapture,
    CameraDisabledError,
    CameraError,
    CameraState,
    UnknownCameraSourceError,
    describe_source,
    rtsp_url,
)

WIDE = LanCameraSource(
    name="wide",
    host="192.168.1.108",
    stream_path="/cam/realmonitor?channel=2&subtype=0",
    user="admin",
    password="pa#ss",
    description="Fixed wide-angle lens.",
)


class FakeBackend:
    def __init__(self, result: bytes | Exception = b"jpeg") -> None:
        self.result = result
        self.calls: list[tuple[int, int, int, str]] = []
        self.probe_calls: list[int] = []
        self.lan_calls: list[tuple[str, float]] = []
        self.lan_probe_calls: list[tuple[str, float]] = []

    def probe_usb(self, device_index: int) -> None:
        self.probe_calls.append(device_index)
        self._raise_if_failing()

    def capture_usb(
        self, device_index: int, width: int, height: int, fourcc: str
    ) -> bytes:
        self.calls.append((device_index, width, height, fourcc))
        return self._result()

    def probe_lan(self, url: str, timeout_seconds: float) -> None:
        self.lan_probe_calls.append((url, timeout_seconds))
        self._raise_if_failing()

    def capture_lan(self, url: str, timeout_seconds: float) -> bytes:
        self.lan_calls.append((url, timeout_seconds))
        return self._result()

    def _raise_if_failing(self) -> None:
        if isinstance(self.result, Exception):
            raise self.result

    def _result(self) -> bytes:
        self._raise_if_failing()
        assert isinstance(self.result, bytes)
        return self.result


@pytest.mark.asyncio
async def test_camera_capture_returns_local_usb_frame_with_configured_device():
    backend = FakeBackend()
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
    backend = FakeBackend()
    capture = CameraCapture(CameraSettings(), CameraState(False), backend)

    with pytest.raises(CameraDisabledError, match="off"):
        await capture.capture()

    assert backend.calls == []


@pytest.mark.asyncio
async def test_privacy_switch_governs_lan_sources_exactly_like_usb_ones():
    backend = FakeBackend()
    capture = CameraCapture(
        CameraSettings(sources=(WIDE,)), CameraState(False), backend
    )

    with pytest.raises(CameraDisabledError, match="off"):
        await capture.capture("wide")

    assert backend.lan_calls == []


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


@pytest.mark.asyncio
async def test_disabling_camera_during_capture_prevents_frame_delivery():
    started = threading.Event()
    release = threading.Event()

    class BlockingBackend(FakeBackend):
        def capture_usb(
            self, device_index: int, width: int, height: int, fourcc: str
        ) -> bytes:
            del device_index, width, height, fourcc
            started.set()
            release.wait(timeout=1)
            return b"jpeg"

    state = CameraState(True)
    capture = CameraCapture(CameraSettings(), state, BlockingBackend())
    capture_task = asyncio.create_task(capture.capture())
    await asyncio.to_thread(started.wait, 1)
    state.set_enabled(False)
    release.set()

    with pytest.raises(CameraDisabledError, match="turned off"):
        await capture_task


@pytest.mark.asyncio
async def test_capture_times_out_and_names_the_source_it_waited_for():
    release = threading.Event()

    class StallingBackend(FakeBackend):
        def capture_lan(self, url: str, timeout_seconds: float) -> bytes:
            del url, timeout_seconds
            release.wait(timeout=1)
            return b"jpeg"

    capture = CameraCapture(
        CameraSettings(sources=(WIDE,), capture_timeout_seconds=0.05),
        CameraState(True),
        StallingBackend(),
    )

    try:
        with pytest.raises(CameraError, match=r"timed out.*wide"):
            await capture.capture("wide")
    finally:
        release.set()


@pytest.mark.asyncio
async def test_lan_capture_reports_the_lan_boundary_and_its_own_source_name():
    backend = FakeBackend()
    capture = CameraCapture(
        CameraSettings(
            sources=(UsbCameraSource(name="desk"), WIDE), capture_timeout_seconds=4.0
        ),
        CameraState(True),
        backend,
        clock=lambda: 7.0,
    )

    frame = await capture.capture("wide")

    assert frame.source == "wide"
    assert frame.data_boundary is DataBoundary.LAN
    assert backend.lan_calls == [
        (
            "rtsp://admin:pa%23ss@192.168.1.108:554/cam/realmonitor?channel=2&subtype=0",
            4.0,
        )
    ]
    assert backend.calls == []


@pytest.mark.asyncio
async def test_named_usb_source_keeps_the_local_boundary():
    backend = FakeBackend()
    capture = CameraCapture(
        CameraSettings(sources=(UsbCameraSource(name="desk", device_index=3), WIDE)),
        CameraState(True),
        backend,
    )

    frame = await capture.capture("desk")

    assert frame.source == "desk"
    assert frame.data_boundary is DataBoundary.LOCAL
    assert backend.calls == [(3, 1920, 1080, "MJPG")]


@pytest.mark.asyncio
async def test_capture_without_a_name_uses_the_first_configured_source():
    backend = FakeBackend()
    capture = CameraCapture(
        CameraSettings(sources=(WIDE, UsbCameraSource(name="desk"))),
        CameraState(True),
        backend,
    )

    frame = await capture.capture()

    assert frame.source == "wide"


@pytest.mark.asyncio
async def test_unknown_source_fails_without_capturing_from_any_other_one():
    backend = FakeBackend()
    capture = CameraCapture(CameraSettings(sources=(WIDE,)), CameraState(True), backend)

    with pytest.raises(UnknownCameraSourceError) as failure:
        await capture.capture("garage")

    assert "Unknown camera source: 'garage'" in str(failure.value)
    assert "Configured sources: wide" in str(failure.value)
    assert backend.lan_calls == []
    assert backend.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("requested", ["Wide", "WIDE", " wide "])
async def test_a_source_name_matches_however_the_caller_capitalized_it(requested):
    backend = FakeBackend()
    capture = CameraCapture(CameraSettings(sources=(WIDE,)), CameraState(True), backend)

    frame = await capture.capture(requested)

    assert frame.source == "wide"
    assert len(backend.lan_calls) == 1


@pytest.mark.asyncio
async def test_an_empty_source_list_still_captures_from_the_legacy_usb_config():
    backend = FakeBackend()
    capture = CameraCapture(
        CameraSettings(usb_device_index=1, sources=()), CameraState(True), backend
    )

    frame = await capture.capture()

    assert frame.source == "usb"
    assert frame.data_boundary is DataBoundary.LOCAL
    assert backend.calls == [(1, 1920, 1080, "MJPG")]


@pytest.mark.parametrize("reserved", ["#", "/", "@", ":", "?", "&", "%"])
def test_rtsp_url_survives_every_reserved_character_a_password_may_contain(reserved):
    password = f"a{reserved}b"
    source = LanCameraSource(
        name="wide",
        host="192.168.1.108",
        stream_path="/cam/realmonitor?channel=1&subtype=0",
        user="admin",
        password=password,
    )

    parts = urlsplit(rtsp_url(source))

    assert parts.hostname == "192.168.1.108"
    assert parts.port == 554
    assert unquote(parts.username or "") == "admin"
    assert unquote(parts.password or "") == password
    assert parts.path == "/cam/realmonitor"


def test_rtsp_url_keeps_the_stream_path_query_unencoded():
    assert rtsp_url(WIDE).endswith("/cam/realmonitor?channel=2&subtype=0")


def test_rtsp_url_accepts_a_stream_path_written_without_a_leading_slash():
    source = LanCameraSource(
        name="wide", host="10.0.0.2", stream_path="stream1", user="u", password="p"
    )

    assert rtsp_url(source) == "rtsp://u:p@10.0.0.2:554/stream1"


def test_rtsp_url_omits_the_credential_part_when_the_camera_needs_none():
    source = LanCameraSource(name="open", host="10.0.0.2", stream_path="/live")

    assert rtsp_url(source) == "rtsp://10.0.0.2:554/live"


def test_source_description_identifies_a_lan_camera_without_its_credentials():
    description = describe_source(WIDE)

    assert "wide" in description
    assert "192.168.1.108:554" in description
    assert WIDE.password not in description
    assert WIDE.user not in description


def test_source_description_identifies_a_usb_camera_by_name_and_device():
    assert describe_source(UsbCameraSource(name="desk", device_index=2)) == (
        "desk (USB device 2)"
    )


@pytest.mark.asyncio
async def test_a_failing_lan_capture_never_leaks_the_password_into_the_error():
    backend = FakeBackend(CameraError("LAN camera stream could not be opened"))
    capture = CameraCapture(CameraSettings(sources=(WIDE,)), CameraState(True), backend)

    with pytest.raises(CameraError) as failure:
        await capture.capture("wide")

    message = str(failure.value)
    assert WIDE.password not in message
    assert "%23" not in message
    assert "wide" in message


@pytest.mark.asyncio
async def test_probe_all_reports_only_the_sources_that_did_not_answer():
    class HalfDeadBackend(FakeBackend):
        def probe_lan(self, url: str, timeout_seconds: float) -> None:
            del url, timeout_seconds
            raise CameraError("unreachable")

    capture = CameraCapture(
        CameraSettings(sources=(UsbCameraSource(name="desk"), WIDE)),
        CameraState(True),
        HalfDeadBackend(),
    )

    assert await capture.probe_all() == ("wide",)


@pytest.mark.asyncio
async def test_probe_all_is_empty_when_every_source_answers():
    capture = CameraCapture(
        CameraSettings(sources=(UsbCameraSource(name="desk"), WIDE)),
        CameraState(True),
        FakeBackend(),
    )

    assert await capture.probe_all() == ()
