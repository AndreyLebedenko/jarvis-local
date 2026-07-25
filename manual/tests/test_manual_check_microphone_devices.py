"""Result-line formatting for the human-run microphone matrix.

Device enumeration itself is no longer this script's own logic - it uses
jarvis.audio.devices, whose tests live in tests/test_audio_devices.py.
"""

from pathlib import Path

from jarvis.audio.devices import InputDevice
from manual.manual_check_microphone_devices import (
    MatrixResult,
    format_result_line,
    sanitize_filename,
)


def test_format_result_line_includes_explicit_device_identity_and_evidence():
    device = InputDevice(
        index=7,
        name="USB Headset",
        host_api="Windows WASAPI",
        default_sample_rate=48000.0,
        max_input_channels=1,
    )
    result = MatrixResult(
        device=device,
        step="capture_quality",
        status="clean",
        detail="normal spoken test",
        evidence=Path("manual_out/chunk.wav"),
    )

    line = format_result_line(result)

    assert line == (
        "RESULT|device_index=7|device_name=USB Headset|host_api=Windows WASAPI|"
        "sample_rate=48000.0|input_channels=1|step=capture_quality|status=clean|"
        "detail=normal spoken test|evidence=manual_out\\chunk.wav"
    )


def test_format_result_line_escapes_delimiters_and_multiline_detail():
    device = InputDevice(
        index=2,
        name="Bluetooth | Hands-Free",
        host_api="MME",
        default_sample_rate=16000.0,
        max_input_channels=1,
    )
    result = MatrixResult(
        device=device,
        step="stall_disconnect",
        status="sleep_wake",
        detail="line one\nline | two",
    )

    line = format_result_line(result)

    assert "Bluetooth / Hands-Free" in line
    assert "detail=line one line / two" in line
    assert "\n" not in line


def test_sanitize_filename_keeps_device_output_paths_stable():
    assert sanitize_filename("  USB Headset (MME)  ") == "USB_Headset_MME"
    assert sanitize_filename("...") == "device"
