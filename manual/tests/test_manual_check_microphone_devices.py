from pathlib import Path

from manual.manual_check_microphone_devices import (
    DeviceInfo,
    MatrixResult,
    device_info_from_sounddevice,
    format_result_line,
    input_devices_from_sounddevice,
    sanitize_filename,
)


def test_format_result_line_includes_explicit_device_identity_and_evidence():
    device = DeviceInfo(
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
    device = DeviceInfo(
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


def test_device_info_from_sounddevice_skips_output_only_devices():
    raw_device = {
        "name": "Speakers",
        "hostapi": 0,
        "default_samplerate": 48000.0,
        "max_input_channels": 0,
    }

    assert device_info_from_sounddevice(0, raw_device, [{"name": "MME"}]) is None


def test_input_devices_from_sounddevice_maps_host_api_names():
    raw_devices = [
        {
            "name": "Speakers",
            "hostapi": 0,
            "default_samplerate": 48000.0,
            "max_input_channels": 0,
        },
        {
            "name": "USB Mic",
            "hostapi": 1,
            "default_samplerate": 44100.0,
            "max_input_channels": 2,
        },
    ]
    raw_hostapis = [{"name": "MME"}, {"name": "Windows WASAPI"}]

    assert input_devices_from_sounddevice(raw_devices, raw_hostapis) == [
        DeviceInfo(
            index=1,
            name="USB Mic",
            host_api="Windows WASAPI",
            default_sample_rate=44100.0,
            max_input_channels=2,
        )
    ]
