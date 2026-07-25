"""Input-device enumeration and identity resolution.

Pure tests over raw sounddevice mappings - no PortAudio, no hardware.
The enumeration cases moved here from manual/tests/ when the parsing
moved into the package: the manual check had known how to read a host
API since task v1.5.1-4, and the product had not.
"""

from dataclasses import replace

import pytest

from jarvis.audio.devices import (
    InputDevice,
    MicrophoneDeviceError,
    display_label,
    input_device_from_sounddevice,
    input_devices_from_sounddevice,
    resolve_input_device,
)

YETI_MME = InputDevice(
    index=3,
    name="Microphone (Yeti X)",
    host_api="MME",
    default_sample_rate=44100.0,
    max_input_channels=2,
)
YETI_WASAPI = InputDevice(
    index=25,
    name="Microphone (Yeti X)",
    host_api="Windows WASAPI",
    default_sample_rate=48000.0,
    max_input_channels=2,
)
WEBCAM_MME = InputDevice(
    index=4,
    name="Microphone (HD Webcam)",
    host_api="MME",
    default_sample_rate=44100.0,
    max_input_channels=1,
)
AMBIGUOUS_SET = [YETI_MME, YETI_WASAPI, WEBCAM_MME]


def test_input_device_from_sounddevice_skips_output_only_devices():
    raw_device = {
        "name": "Speakers",
        "hostapi": 0,
        "default_samplerate": 48000.0,
        "max_input_channels": 0,
    }

    assert input_device_from_sounddevice(0, raw_device, [{"name": "MME"}]) is None


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
        InputDevice(
            index=1,
            name="USB Mic",
            host_api="Windows WASAPI",
            default_sample_rate=44100.0,
            max_input_channels=2,
        )
    ]


def test_input_devices_keep_the_enumeration_index_not_the_input_only_position():
    """The index is what PortAudio opens, so it must count every device,
    including the output-only ones that never appear in the result."""
    raw_devices = [
        {"name": "Speakers", "hostapi": 0, "max_input_channels": 0},
        {"name": "Headphones", "hostapi": 0, "max_input_channels": 0},
        {"name": "USB Mic", "hostapi": 0, "max_input_channels": 1},
    ]

    devices = input_devices_from_sounddevice(raw_devices, [{"name": "MME"}])

    assert [device.index for device in devices] == [2]


def test_unknown_host_api_index_is_named_rather_than_crashing():
    raw_devices = [{"name": "USB Mic", "hostapi": 9, "max_input_channels": 1}]

    devices = input_devices_from_sounddevice(raw_devices, [{"name": "MME"}])

    assert devices[0].host_api == "unknown"


def test_empty_device_name_resolves_to_the_system_default():
    """None is what PortAudio needs to pick its own default by index -
    the one path that was never affected by name ambiguity."""
    assert resolve_input_device(AMBIGUOUS_SET, "") is None


def test_a_unique_name_still_resolves_without_a_host_api():
    """Backward compatibility: an existing config.ui.toml holding a bare
    name keeps working wherever that name is unique."""
    assert resolve_input_device(AMBIGUOUS_SET, "Microphone (HD Webcam)") == 4


def test_an_ambiguous_name_without_a_host_api_names_every_candidate():
    """The reported failure. PortAudio's own message named the candidates
    and died in a background task; this one has to reach the user."""
    with pytest.raises(MicrophoneDeviceError) as failure:
        resolve_input_device(AMBIGUOUS_SET, "Microphone (Yeti X)")

    message = str(failure.value)
    assert "[3] Microphone (Yeti X), MME" in message
    assert "[25] Microphone (Yeti X), Windows WASAPI" in message
    assert "Microphone (HD Webcam)" not in message


def test_a_host_api_disambiguates_a_repeated_name():
    assert resolve_input_device(AMBIGUOUS_SET, "Microphone (Yeti X)", "MME") == 3
    assert (
        resolve_input_device(AMBIGUOUS_SET, "Microphone (Yeti X)", "Windows WASAPI")
        == 25
    )


def test_a_configured_host_api_that_matches_nothing_is_an_error():
    """Never a silent fall back to another host API: PROJECT.md ties MME
    to both the wake-recovery fix and the post-mute capture finding, so
    moving a configuration to a different API changes real behavior."""
    with pytest.raises(MicrophoneDeviceError):
        resolve_input_device(AMBIGUOUS_SET, "Microphone (Yeti X)", "Windows WDM-KS")


def test_an_unknown_name_is_an_error_listing_what_is_available():
    with pytest.raises(MicrophoneDeviceError) as failure:
        resolve_input_device(AMBIGUOUS_SET, "Microphone (Unplugged)")

    assert "Microphone (Yeti X)" in str(failure.value)


def test_two_identical_devices_on_one_host_api_are_reported_not_guessed():
    """Two of the same headset model: config cannot express which, and
    picking the lower index would be a coin flip presented as a choice."""
    duplicates = [YETI_MME, replace(YETI_MME, index=9)]

    with pytest.raises(MicrophoneDeviceError):
        resolve_input_device(duplicates, "Microphone (Yeti X)", "MME")


def test_no_devices_at_all_reports_rather_than_returning_the_default():
    with pytest.raises(MicrophoneDeviceError):
        resolve_input_device([], "Microphone (Yeti X)")


# --- display labels (owner UX request, 2026-07-25) -------------------------
# Windows hands PortAudio the raw MMDevice resource string for Bluetooth
# hands-free endpoints, embedded newline and all. It is still the identity
# the driver answers to, so it is cleaned for display only.

BLUETOOTH_RESOURCE_NAME = (
    "Headset (@System32\\drivers\\bthhfenum.sys,#2;%1 Hands-Free%0\n"
    ";(Galaxy Buds Live (2A04)))"
)


def test_a_bluetooth_resource_string_shows_the_name_a_human_recognizes():
    assert display_label(BLUETOOTH_RESOURCE_NAME) == "Headset (Galaxy Buds Live (2A04))"


def test_a_friendly_name_keeps_its_own_parentheses():
    """ "(2A04)" is part of what the user sees on the device, so the tail
    must be taken whole rather than cut at the first bracket."""
    assert "(2A04)" in display_label(BLUETOOTH_RESOURCE_NAME)


def test_an_ordinary_device_name_is_left_alone():
    assert display_label("Microphone (Yeti X)") == "Microphone (Yeti X)"


def test_any_embedded_newline_is_collapsed_even_without_the_resource_pattern():
    """A label reaches single-line surfaces - a log line, a <option>, a
    RESULT row - so no label may carry a line break."""
    assert display_label("Weird\nDevice\r\n Name") == "Weird Device Name"


def test_the_label_never_replaces_the_identity():
    """The raw name is what PortAudio will answer to and what config
    stores; the label is derived and must not leak into either."""
    device = InputDevice(
        index=34,
        name=BLUETOOTH_RESOURCE_NAME,
        host_api="Windows WDM-KS",
        default_sample_rate=8000.0,
        max_input_channels=1,
    )

    assert device.name == BLUETOOTH_RESOURCE_NAME
    assert device.label == "Headset (Galaxy Buds Live (2A04))"
    assert resolve_input_device([device], BLUETOOTH_RESOURCE_NAME) == 34


def test_error_candidates_are_listed_by_label_and_stay_on_one_line():
    devices = [
        InputDevice(34, BLUETOOTH_RESOURCE_NAME, "Windows WDM-KS", 8000.0, 1),
        InputDevice(38, BLUETOOTH_RESOURCE_NAME, "MME", 16000.0, 1),
    ]

    with pytest.raises(MicrophoneDeviceError) as failure:
        resolve_input_device(devices, BLUETOOTH_RESOURCE_NAME)

    message = str(failure.value)
    assert "Headset (Galaxy Buds Live (2A04))" in message
    assert "bthhfenum" not in message
    assert "\n" not in message
