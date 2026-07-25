"""Input-device enumeration and identity resolution.

Windows exposes one physical microphone once per host API, and PortAudio
lists each copy under an identical name. A name is therefore not an
identifier: asking PortAudio to resolve one raises when it matches
several devices, which left a selected microphone unopenable (see the
microphone-device-name-ambiguous bug report in tasks/bug_reports/).

This module resolves a configured (name, host API) pair to a device index
itself, so no code path hands a name to PortAudio. Parsing is pure over
raw sounddevice mappings; only enumerate_input_devices() touches the
audio stack, which keeps every resolution rule testable without hardware.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Integral, Real

UNKNOWN_HOST_API = "unknown"

# Windows hands PortAudio the raw MMDevice resource string for Bluetooth
# hands-free endpoints, embedded newline included:
#
#   Headset (@System32\drivers\bthhfenum.sys,#2;%1 Hands-Free%0
#   ;(Galaxy Buds Live (2A04)))
#
# The name a human recognizes is the parenthesized tail. The greedy `.*`
# is deliberate: it binds `;(` to the last occurrence, so a friendly name
# containing its own parentheses - "(2A04)" above - survives intact.
_RESOURCE_STRING = re.compile(
    r"^(?P<kind>[^(]*)\(@.*;\((?P<friendly>.+)\)\)$", re.DOTALL
)


def display_label(name: str) -> str:
    """A device name fit to show a human. Never an identity: resolution
    matches the raw PortAudio name, because that is the string the driver
    will answer to and the one config stores."""
    match = _RESOURCE_STRING.match(name)
    if match:
        name = f"{match['kind'].strip()} ({match['friendly']})"
    return " ".join(name.split())


class MicrophoneDeviceError(Exception):
    """A configured microphone cannot be resolved to exactly one device."""


@dataclass(frozen=True)
class InputDevice:
    index: int
    name: str
    host_api: str
    default_sample_rate: float
    max_input_channels: int

    @property
    def label(self) -> str:
        """Derived, not stored: `name` stays exactly what PortAudio said,
        so nothing can drift between what is shown and what is opened."""
        return display_label(self.name)


def _mapping_text(raw: Mapping[str, object], key: str, default: str = "") -> str:
    value = raw.get(key, default)
    return value if isinstance(value, str) else default


def _mapping_int(raw: Mapping[str, object], key: str, default: int = 0) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool):
        return default
    return int(value) if isinstance(value, Integral) else default


def _mapping_float(raw: Mapping[str, object], key: str, default: float = 0.0) -> float:
    value = raw.get(key, default)
    if isinstance(value, bool):
        return default
    if isinstance(value, Real):
        return float(value)
    return default


def input_device_from_sounddevice(
    index: int,
    raw_device: Mapping[str, object],
    raw_hostapis: Sequence[Mapping[str, object]],
) -> InputDevice | None:
    """Returns None for a device with no input channels."""
    max_input_channels = _mapping_int(raw_device, "max_input_channels")
    if max_input_channels <= 0:
        return None
    hostapi_index = _mapping_int(raw_device, "hostapi", -1)
    host_api = UNKNOWN_HOST_API
    if 0 <= hostapi_index < len(raw_hostapis):
        host_api = _mapping_text(raw_hostapis[hostapi_index], "name", UNKNOWN_HOST_API)
    return InputDevice(
        index=index,
        name=_mapping_text(raw_device, "name", f"device-{index}"),
        host_api=host_api,
        default_sample_rate=_mapping_float(raw_device, "default_samplerate"),
        max_input_channels=max_input_channels,
    )


def input_devices_from_sounddevice(
    raw_devices: Sequence[Mapping[str, object]],
    raw_hostapis: Sequence[Mapping[str, object]],
) -> list[InputDevice]:
    devices = []
    for index, raw_device in enumerate(raw_devices):
        device = input_device_from_sounddevice(index, raw_device, raw_hostapis)
        if device is not None:
            devices.append(device)
    return devices


def enumerate_input_devices() -> list[InputDevice]:
    """The only function here that touches the audio stack. sounddevice is
    imported lazily so importing this module from a pure test - or from
    the UI bridge - does not pull in PortAudio."""
    import sounddevice as sd

    return input_devices_from_sounddevice(sd.query_devices(), sd.query_hostapis())


def describe_devices(devices: Sequence[InputDevice]) -> str:
    """Candidate list for error messages. Labels, not raw names: the
    audience is a human diagnosing a failure, and the remedy this points
    at is the Settings selector rather than hand-typing a name. A raw
    Bluetooth resource string would also drop a newline into the middle
    of a log line."""
    return "; ".join(
        f"[{device.index}] {device.label}, {device.host_api}" for device in devices
    )


def resolve_input_device(
    devices: Sequence[InputDevice], name: str, host_api: str = ""
) -> int | None:
    """Resolves configured microphone identity to a PortAudio device index.

    An empty name means "use the system default": the caller passes None
    to PortAudio, which resolves its own default by index and is therefore
    unaffected by name ambiguity.

    An empty host_api resolves by name alone and is an error when the name
    is not unique - never a pick among candidates. Whichever copy sorted
    first would be a silent choice of host API, and host API choice is not
    cosmetic on Windows: PROJECT.md ties MME to both the wake-recovery fix
    and the post-mute degraded-capture finding.
    """
    if not name:
        return None
    matches = [device for device in devices if device.name == name]
    # Echoed by label for the same reason describe_devices() uses one: the
    # configured value can be a raw Bluetooth resource string, and a
    # message a human cannot read is not a message.
    shown = display_label(name)
    if host_api:
        matches = [device for device in matches if device.host_api == host_api]
        if not matches:
            raise MicrophoneDeviceError(
                f"No input device named {shown!r} on host API {host_api!r}. "
                f"Available input devices: {describe_devices(devices) or 'none'}"
            )
        # A single (name, host API) pair can still repeat if two identical
        # devices are attached. Their indices are all this code can tell
        # apart, and config cannot express one, so report rather than pick.
        if len(matches) > 1:
            raise MicrophoneDeviceError(
                f"Multiple input devices named {shown!r} on host API "
                f"{host_api!r}: {describe_devices(matches)}. Detach one, or "
                "select the device again after removing the duplicate."
            )
        return matches[0].index
    if not matches:
        raise MicrophoneDeviceError(
            f"No input device named {shown!r}. "
            f"Available input devices: {describe_devices(devices) or 'none'}"
        )
    if len(matches) > 1:
        raise MicrophoneDeviceError(
            f"Multiple input devices found for {shown!r}: {describe_devices(matches)}. "
            "Set [microphone].host_api, or select the device again in the "
            "Status Console's Settings tab."
        )
    return matches[0].index
