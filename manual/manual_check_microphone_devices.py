#!/usr/bin/env python3
"""Human-run microphone device matrix for task v1.5.1-4.

This is not an automated test: it opens real capture/playback devices.

Usage:
  python -m manual.manual_check_microphone_devices
  python -m manual.manual_check_microphone_devices --device-index 2

The script lists input devices, makes the selected device explicit in every
RESULT line, saves captured utterance wavs under
manual_check_microphone_devices_out/, and guides the human through capture
quality, sleep/wake, stall/disconnect, Bluetooth, and shutdown checks.
"""

import argparse
import asyncio
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from numbers import Integral, Real
from pathlib import Path
from typing import cast

import sounddevice as sd
import soundfile as sf

from jarvis.audio.input import (
    SAMPLE_RATE,
    AudioInput,
    InputStreamLike,
    UtteranceChunk,
    VadChunker,
)
from jarvis.core.bus import EventBus
from jarvis.core.config import load_settings

DEFAULT_OUT_DIR = Path("manual_check_microphone_devices_out")
SLEEP_WAKE_CYCLES = 3
QUIET_REPLAY_WINDOW_SECONDS = 1.0


@dataclass(frozen=True)
class DeviceInfo:
    index: int
    name: str
    host_api: str
    default_sample_rate: float
    max_input_channels: int


@dataclass(frozen=True)
class RecordedChunk:
    number: int
    path: Path
    duration_seconds: float
    captured_at_seconds: float


@dataclass(frozen=True)
class MatrixResult:
    device: DeviceInfo
    step: str
    status: str
    detail: str = ""
    evidence: Path | None = None


def sanitize_filename(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    sanitized = sanitized.strip("._")
    return sanitized or "device"


def _result_value(value: object) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").replace("|", "/")
    return " ".join(text.split())


def format_result_line(result: MatrixResult) -> str:
    fields = {
        "device_index": result.device.index,
        "device_name": result.device.name,
        "host_api": result.device.host_api,
        "sample_rate": f"{result.device.default_sample_rate:.1f}",
        "input_channels": result.device.max_input_channels,
        "step": result.step,
        "status": result.status,
        "detail": result.detail,
    }
    if result.evidence is not None:
        fields["evidence"] = result.evidence
    parts = ["RESULT"]
    parts.extend(f"{key}={_result_value(value)}" for key, value in fields.items())
    return "|".join(parts)


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


def device_info_from_sounddevice(
    index: int,
    raw_device: Mapping[str, object],
    raw_hostapis: Sequence[Mapping[str, object]],
) -> DeviceInfo | None:
    max_input_channels = _mapping_int(raw_device, "max_input_channels")
    if max_input_channels <= 0:
        return None
    hostapi_index = _mapping_int(raw_device, "hostapi", -1)
    host_api = "unknown"
    if 0 <= hostapi_index < len(raw_hostapis):
        host_api = _mapping_text(raw_hostapis[hostapi_index], "name", "unknown")
    return DeviceInfo(
        index=index,
        name=_mapping_text(raw_device, "name", f"device-{index}"),
        host_api=host_api,
        default_sample_rate=_mapping_float(raw_device, "default_samplerate"),
        max_input_channels=max_input_channels,
    )


def input_devices_from_sounddevice(
    raw_devices: Sequence[Mapping[str, object]],
    raw_hostapis: Sequence[Mapping[str, object]],
) -> list[DeviceInfo]:
    devices = []
    for index, raw_device in enumerate(raw_devices):
        device = device_info_from_sounddevice(index, raw_device, raw_hostapis)
        if device is not None:
            devices.append(device)
    return devices


def _stream_factory_for_device_index(device_index: int):
    def make_stream(block_samples: int) -> InputStreamLike:
        return sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=block_samples,
            device=device_index,
        )

    return make_stream


def _print_devices(devices: Sequence[DeviceInfo]) -> None:
    print("Input devices:")
    for device in devices:
        print(
            f"  [{device.index}] {device.name} | {device.host_api} | "
            f"{device.default_sample_rate:.1f} Hz | "
            f"{device.max_input_channels} input channel(s)"
        )


async def _prompt(text: str) -> str:
    return await asyncio.to_thread(input, text)


async def _choose_device(
    devices: Sequence[DeviceInfo], requested_index: int | None
) -> DeviceInfo:
    if requested_index is not None:
        for device in devices:
            if device.index == requested_index:
                return device
        raise SystemExit(f"No input device with index {requested_index}.")

    while True:
        answer = (await _prompt("Device index to test: ")).strip()
        try:
            selected = int(answer)
        except ValueError:
            print("Enter a numeric device index.")
            continue
        for device in devices:
            if device.index == selected:
                return device
        print("That index is not in the input-device list above.")


def _output_dir(base_dir: Path, device: DeviceInfo) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = sanitize_filename(f"{device.index}-{device.name}")
    return base_dir / f"{timestamp}-{name}"


class ResultSink:
    def __init__(self, output_dir: Path) -> None:
        self._lines: list[str] = []
        self._path = output_dir / "matrix_results.txt"

    def emit(self, result: MatrixResult) -> None:
        line = format_result_line(result)
        self._lines.append(line)
        print(line)

    def write(self) -> None:
        self._path.write_text("\n".join(self._lines) + "\n", encoding="utf-8")
        print(f"\nSaved result lines to {self._path}")


async def _play_wav(path: Path) -> None:
    data, sample_rate = await asyncio.to_thread(sf.read, path, dtype="float32")
    await asyncio.to_thread(sd.play, data, sample_rate)
    await asyncio.to_thread(sd.wait)


async def _ask_status(prompt: str, allowed: Sequence[str]) -> str:
    allowed_text = "/".join(allowed)
    while True:
        answer = (await _prompt(f"{prompt} [{allowed_text}]: ")).strip().lower()
        if answer in allowed:
            return answer
        print(f"Expected one of: {allowed_text}")


async def _ask_detail(prompt: str) -> str:
    return (await _prompt(f"{prompt}: ")).strip()


async def _wait_for_capture(prompt: str, chunks: list[RecordedChunk]) -> bool:
    before = len(chunks)
    print(prompt)
    await _prompt("Press Enter after speaking and waiting for the silence boundary.")
    return len(chunks) > before


async def _run_matrix(device: DeviceInfo, output_dir: Path) -> None:
    settings = load_settings()
    bus = EventBus()
    output_dir.mkdir(parents=True, exist_ok=True)
    sink = ResultSink(output_dir)
    chunks: list[RecordedChunk] = []
    started_at = time.monotonic()

    async def on_chunk(chunk: UtteranceChunk) -> None:
        number = len(chunks) + 1
        path = output_dir / f"utterance-{number:03d}.wav"
        path.write_bytes(chunk.wav_bytes)
        recorded = RecordedChunk(
            number=number,
            path=path,
            duration_seconds=chunk.end_seconds - chunk.start_seconds,
            captured_at_seconds=time.monotonic() - started_at,
        )
        chunks.append(recorded)
        sink.emit(
            MatrixResult(
                device=device,
                step="capture_chunk",
                status="recorded",
                detail=f"chunk={number}; duration={recorded.duration_seconds:.2f}s",
                evidence=path,
            )
        )

    bus.subscribe(UtteranceChunk, on_chunk)
    audio_input = AudioInput(
        bus=bus,
        chunker=VadChunker(settings.vad),
        stream_factory=_stream_factory_for_device_index(device.index),
    )
    loop_task = asyncio.create_task(audio_input.run_microphone_loop())
    sink.emit(MatrixResult(device=device, step="identification", status="selected"))

    try:
        captured = await _wait_for_capture(
            "\nCapture quality: speak a normal test utterance into this device.",
            chunks,
        )
        if captured:
            latest = chunks[-1]
            print(f"Playing back {latest.path}")
            await _play_wav(latest.path)
            status = await _ask_status(
                "Listening check result", ("clean", "distorted", "dropouts")
            )
            detail = await _ask_detail("Optional capture-quality notes")
            sink.emit(
                MatrixResult(
                    device=device,
                    step="capture_quality",
                    status=status,
                    detail=detail,
                    evidence=latest.path,
                )
            )
        else:
            sink.emit(
                MatrixResult(
                    device=device,
                    step="capture_quality",
                    status="no_chunk",
                    detail="No utterance was published before Enter.",
                )
            )

        for cycle in range(1, SLEEP_WAKE_CYCLES + 1):
            await _prompt(
                f"\nSleep/wake cycle {cycle}: press Enter to put the mic to sleep."
            )
            await audio_input.toggle_user_sleep()
            asleep_count = len(chunks)
            print("Mic is asleep. Stay quiet, then wait for the replay window.")
            await asyncio.sleep(QUIET_REPLAY_WINDOW_SECONDS)
            sleep_status = "pass" if len(chunks) == asleep_count else "stale_replay"
            sink.emit(
                MatrixResult(
                    device=device,
                    step=f"sleep_wake_{cycle}_sleep",
                    status=sleep_status,
                    detail="No chunk should appear while asleep.",
                )
            )

            await _prompt("Press Enter to wake the mic.")
            await audio_input.toggle_user_sleep()
            wake_count = len(chunks)
            await asyncio.sleep(QUIET_REPLAY_WINDOW_SECONDS)
            replay_status = "pass" if len(chunks) == wake_count else "stale_replay"
            sink.emit(
                MatrixResult(
                    device=device,
                    step=f"sleep_wake_{cycle}_quiet_after_wake",
                    status=replay_status,
                    detail="No immediate stale-buffer chunk should appear after wake.",
                )
            )

            resumed = await _wait_for_capture(
                f"Cycle {cycle}: speak a short phrase to confirm capture resumed.",
                chunks,
            )
            sink.emit(
                MatrixResult(
                    device=device,
                    step=f"sleep_wake_{cycle}_resume",
                    status="pass" if resumed else "no_chunk",
                    detail="Capture should publish a fresh post-wake utterance.",
                    evidence=chunks[-1].path if resumed else None,
                )
            )

        print(
            "\nStall/disconnect: unplug USB, power off Bluetooth, or move it "
            "out of range while capture is active. Reconnect before continuing."
        )
        await _prompt("Press Enter after the disconnect/reconnect attempt.")
        if loop_task.done():
            exception = loop_task.exception()
            sink.emit(
                MatrixResult(
                    device=device,
                    step="stall_disconnect",
                    status="loop_exited",
                    detail=repr(exception) if exception is not None else "no exception",
                )
            )
        else:
            before_recovery = len(chunks)
            recovered = await _wait_for_capture(
                "After reconnect, speak to test whether capture recovered.",
                chunks,
            )
            recovery_status = await _ask_status(
                "Observed recovery mode",
                ("auto", "sleep_wake", "restart", "no_recovery"),
            )
            detail = (
                "fresh chunk observed"
                if recovered and len(chunks) > before_recovery
                else "no fresh chunk observed"
            )
            sink.emit(
                MatrixResult(
                    device=device,
                    step="stall_disconnect",
                    status=recovery_status,
                    detail=detail,
                    evidence=chunks[-1].path if recovered else None,
                )
            )

        bluetooth = await _ask_status(
            "\nBluetooth profile check applicable", ("no", "yes")
        )
        if bluetooth == "yes":
            profile_detail = await _ask_detail(
                "Profile/playback observation "
                "(HFP switch, sample-rate change, playback degraded capture)"
            )
            sink.emit(
                MatrixResult(
                    device=device,
                    step="bluetooth_profile",
                    status="observed",
                    detail=profile_detail,
                )
            )
        else:
            sink.emit(
                MatrixResult(
                    device=device,
                    step="bluetooth_profile",
                    status="not_applicable",
                )
            )

    finally:
        try:
            await audio_input.stop()
            await loop_task
            sink.emit(MatrixResult(device=device, step="clean_shutdown", status="pass"))
        except Exception as exc:
            sink.emit(
                MatrixResult(
                    device=device,
                    step="clean_shutdown",
                    status="error",
                    detail=repr(exc),
                )
            )
            raise
        finally:
            sink.write()


async def _main_async(args: argparse.Namespace) -> None:
    raw_devices = cast(Sequence[Mapping[str, object]], sd.query_devices())
    raw_hostapis = cast(Sequence[Mapping[str, object]], sd.query_hostapis())
    devices = input_devices_from_sounddevice(raw_devices, raw_hostapis)
    if not devices:
        raise SystemExit("No PortAudio input devices found.")
    _print_devices(devices)
    if args.list_only:
        return
    device = await _choose_device(devices, args.device_index)
    output_dir = _output_dir(args.output_dir, device)
    print(f"\nTesting [{device.index}] {device.name} via {device.host_api}")
    print(f"Output directory: {output_dir}\n")
    await _run_matrix(device, output_dir)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--device-index",
        type=int,
        default=None,
        help="PortAudio input device index to test; omit for an interactive prompt.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Directory where evidence wavs and result lines are saved.",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="List input devices and exit without opening a stream.",
    )
    return parser.parse_args()


def main() -> None:
    asyncio.run(_main_async(_parse_args()))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
