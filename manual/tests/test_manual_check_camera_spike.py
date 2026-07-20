import base64

from jarvis.core.bus import EventBus
from jarvis.core.config import BackendSettings
from jarvis.dialog.backend import OllamaBackend
from manual.manual_check_camera_spike import (
    CameraSource,
    build_arg_parser,
    build_probe_request,
    build_source,
    classify_chunks,
    format_requested_resolution,
    normalize_fourcc,
    redact_uri,
    safe_label,
)


def _backend() -> OllamaBackend:
    return OllamaBackend(EventBus(), BackendSettings(model="test-model", num_ctx=123))


def test_safe_label_keeps_filesystem_friendly_text():
    assert safe_label("Imou channel 1 / fixed lens") == "Imou-channel-1-fixed-lens"


def test_safe_label_falls_back_for_empty_values():
    assert safe_label("...") == "camera"


def test_redact_uri_hides_rtsp_credentials():
    redacted = redact_uri(
        "rtsp://admin:SAFETY_CODE@192.168.1.50:554/cam/realmonitor?channel=1"
    )

    assert redacted == "rtsp://<credentials>@192.168.1.50:554/cam/realmonitor?channel=1"
    assert "SAFETY_CODE" not in redacted
    assert "admin:" not in redacted


def test_redact_uri_leaves_credential_free_uri_unchanged():
    uri = "rtsp://192.168.1.50:554/cam/realmonitor?channel=1"

    assert redact_uri(uri) == uri


def test_camera_source_records_usb_source():
    source = CameraSource("usb", "c920", 0, "auto", None, None, None)

    assert source.kind == "usb"
    assert source.address == 0
    assert source.opencv_backend == "auto"


def test_build_source_records_requested_opencv_backend():
    args = build_arg_parser().parse_args(
        ["--usb-index", "1", "--label", "c920", "--opencv-backend", "dshow"]
    )

    source = build_source(args)

    assert source == CameraSource("usb", "c920", 1, "dshow", None, None, None)


def test_build_source_records_requested_resolution_and_fourcc():
    args = build_arg_parser().parse_args(
        [
            "--usb-index",
            "0",
            "--frame-width",
            "1920",
            "--frame-height",
            "1080",
            "--fourcc",
            "MJPG",
        ]
    )

    source = build_source(args)

    assert source == CameraSource("usb", "usb-0", 0, "auto", 1920, 1080, "MJPG")


def test_build_source_normalizes_fourcc_to_uppercase():
    args = build_arg_parser().parse_args(["--fourcc", "mjpg"])

    source = build_source(args)

    assert source.fourcc == "MJPG"


def test_normalize_fourcc_rejects_non_four_character_values():
    try:
        normalize_fourcc("jpegx")
    except ValueError as exc:
        assert "exactly four characters" in str(exc)
    else:
        raise AssertionError("Expected invalid FOURCC to be rejected.")


def test_format_requested_resolution_reports_default_or_requested_size():
    default_source = CameraSource("usb", "c920", 0, "auto", None, None, None)
    full_hd_source = CameraSource("usb", "c920", 0, "dshow", 1920, 1080, "MJPG")

    assert format_requested_resolution(default_source) == "default"
    assert format_requested_resolution(full_hd_source) == "1920x1080"


def test_build_probe_request_uses_images_field_and_backend_options():
    frame = base64.b64encode(b"jpg bytes").decode("ascii")
    request = build_probe_request(_backend(), "c920", frame, "Describe this.")

    [message] = request.payload["messages"]
    assert message["content"] == "Describe this."
    assert message["images"] == [frame]
    assert request.payload["model"] == "test-model"
    assert request.payload["options"] == {"num_ctx": 123}
    assert request.payload["think"] is False


def test_classify_chunks_collects_streamed_content_and_eval_count():
    chunks = [
        {"message": {"content": "A desk "}},
        {"message": {"content": "and monitor."}},
        {"done": True, "eval_count": 9},
    ]

    result = classify_chunks("c920", "Describe.", chunks, wall_seconds=1.5)

    assert result.success is True
    assert result.content_text == "A desk and monitor."
    assert result.eval_count == 9
    assert result.wall_seconds == 1.5


def test_classify_chunks_without_done_is_not_success():
    result = classify_chunks("c920", "Describe.", [{"message": {"content": "A"}}], 0.1)

    assert result.success is False


def test_classify_chunks_reports_transport_error_as_failure():
    result = classify_chunks("c920", "Describe.", [], 0.1, error="timeout")

    assert result.success is False
    assert result.error == "timeout"
