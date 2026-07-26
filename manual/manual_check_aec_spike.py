#!/usr/bin/env python3
"""Manual handoff for task-v1.7.0-1: AEC spike (hard gate).

Plays a real TTS-synthesized response through the speakers while
recording the microphone at the same time (sounddevice.playrec, so the
"far-end" reference is exactly the array requested for playback and the
"near-end" recording is time-aligned to it by construction). The
far-end/near-end delay is estimated by cross-correlation first (Windows
MME has been measured on this machine adding 300+ ms of round-trip
buffering latency - far more than acoustic travel time, and far more
than a short adaptive filter can see unless it is told where to look).
A simple NLMS adaptive-filter echo canceller - pure numpy, no new
dependency - then runs offline against the delay-compensated recording,
and the residual is fed through the project's real Silero VAD at the
configured config.vad.threshold: the same detector production code
uses, not an invented metric.

Use --input-device/--output-device to try a WASAPI copy of your mic and
speakers instead of the configured MME ones (`python -c "import
sounddevice as sd; print(sd.query_devices())"` lists indices) - MME's
latency is the leading suspect if a candidate keeps failing here.

This is hardware-dependent and is run by the human, not by automated CI.
No new package is required; the NLMS canceller here is a deliberately
simple, dependency-free candidate (see the task card's boundary: any
library may be tried, but a pure-numpy filter carries zero Windows
packaging risk, which is the story's own stop-condition concern). If
this candidate is a clear no-go, later runs can try a native library
instead - see PROJECT.md's roadmap-after-v1.0 notes on why operability
cost is weighed before adding a dependency.

Known simplification: this NLMS implementation has no double-talk
detector, so the filter keeps adapting even while both Jarvis and the
human are speaking (the "interrupt" scenario below). That is expected to
inflate residual energy during a real interruption rather than suppress
it - which is the outcome we want there - but it means the filter can
also drift for a moment after a genuine interrupt. That drift, if
visible in the residual/VAD output, is itself a finding worth recording,
not a bug in the check.

Run each condition twice, changing only --scenario:

  python -m manual.manual_check_aec_spike --label quiet-close --scenario silent
  python -m manual.manual_check_aec_spike --label quiet-close --scenario interrupt
  python -m manual.manual_check_aec_spike --label quiet-far --scenario silent
  python -m manual.manual_check_aec_spike --label quiet-far --scenario interrupt
  python -m manual.manual_check_aec_spike --label reverb-close --scenario silent
  python -m manual.manual_check_aec_spike --label reverb-close --scenario interrupt
  python -m manual.manual_check_aec_spike --label reverb-far --scenario silent
  python -m manual.manual_check_aec_spike --label reverb-far --scenario interrupt

See tasks/aec-spike-handoff.md for the full instructions and result
table.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
import torch
import torchaudio
from silero_vad import get_speech_timestamps, load_silero_vad

from jarvis.audio.devices import enumerate_input_devices, resolve_input_device
from jarvis.audio.language_segments import DEFAULT_LANGUAGE
from jarvis.audio.tts_factory import build_tts_engine
from jarvis.core.config import Settings, load_settings

VAD_SAMPLE_RATE = 16000

DEFAULT_TEXT = (
    "Сегодня хорошая погода для прогулки в парке. Я думаю, что стоит выйти "
    "на улицу и подышать свежим воздухом, а потом можно выпить чашку чая и "
    "почитать интересную книгу. Это отличный способ провести свободное "
    "время после долгого рабочего дня, особенно если рядом нет никаких "
    "срочных дел."
)

DEFAULT_OUT_DIR = Path("manual_check_aec_spike_out")


@dataclass(frozen=True)
class Recording:
    far_end: np.ndarray  # float32, native rate, exactly what was requested for playback
    near_end: np.ndarray  # float32, native rate, playrec's recorded channel
    sample_rate: int
    tts_start_seconds: float
    tts_end_seconds: float


@dataclass(frozen=True)
class VadSegment:
    start_seconds: float
    end_seconds: float
    overlaps_tts_window: bool


async def synthesize_far_end(settings: Settings, text: str) -> tuple[np.ndarray, int]:
    engine = build_tts_engine(settings.tts)
    wav_bytes = await engine.synthesize(text, DEFAULT_LANGUAGE)
    data, sample_rate = sf.read(io.BytesIO(wav_bytes), dtype="float32", always_2d=True)
    return data.mean(axis=1).astype(np.float32), sample_rate


def _as_index_or_name(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def resolve_io_devices(
    settings: Settings,
    output_device: str | None,
    input_device: str | None = None,
) -> tuple[int | str | None, int | str | None]:
    """input_device overrides config.microphone entirely (e.g. to test a
    WASAPI copy of the same physical mic instead of the configured MME
    one) - it does not go through resolve_input_device()'s name/host_api
    matching, since the point is to bypass the configured identity."""
    if input_device is not None:
        input_index: int | str | None = _as_index_or_name(input_device)
    else:
        mic = settings.microphone
        input_index = resolve_input_device(
            enumerate_input_devices(), mic.device, mic.host_api
        )
    if output_device is None:
        return input_index, None
    return input_index, _as_index_or_name(output_device)


def pad_and_record(
    far_end: np.ndarray,
    sample_rate: int,
    lead_in_seconds: float,
    tail_seconds: float,
    devices: tuple[int | str | None, int | str | None],
) -> Recording:
    lead_in = np.zeros(int(lead_in_seconds * sample_rate), dtype=np.float32)
    tail = np.zeros(int(tail_seconds * sample_rate), dtype=np.float32)
    padded = np.concatenate([lead_in, far_end, tail])
    tts_start_seconds = lead_in_seconds
    tts_end_seconds = lead_in_seconds + len(far_end) / sample_rate

    recording = sd.playrec(
        padded.reshape(-1, 1),
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        device=devices,
    )
    sd.wait()
    return Recording(
        far_end=padded,
        near_end=recording[:, 0],
        sample_rate=sample_rate,
        tts_start_seconds=tts_start_seconds,
        tts_end_seconds=tts_end_seconds,
    )


def resample_to_vad_rate(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    if sample_rate == VAD_SAMPLE_RATE:
        return samples
    tensor = torchaudio.functional.resample(
        torch.from_numpy(samples), sample_rate, VAD_SAMPLE_RATE
    )
    return tensor.numpy()


def estimate_delay_samples(
    far_end: np.ndarray,
    near_end: np.ndarray,
    max_lag_seconds: float = 0.6,
    sample_rate: int = VAD_SAMPLE_RATE,
) -> int:
    """Coarse delay estimate via normalized cross-correlation over the
    first few seconds of signal, so the adaptive filter's tap window can
    be centered on the real echo path instead of assuming near-zero
    device latency. Windows MME playrec has been observed to carry 300+
    ms of round-trip buffering latency here - far beyond what a short
    adaptive filter can otherwise see, which silently defeats echo
    cancellation rather than merely weakening it (the filter adapts to
    whatever is inside its window, which is the wrong signal entirely).
    Returns 0, never negative, if the estimated peak is not positive -
    near-end audio cannot causally precede the far-end signal it echoes."""
    max_lag = int(max_lag_seconds * sample_rate)
    n = min(len(far_end), len(near_end), sample_rate * 5)
    far = far_end[:n].astype(np.float64)
    near = near_end[:n].astype(np.float64)
    far = far - far.mean()
    near = near - near.mean()
    corr = np.correlate(near, far, mode="full")
    mid = len(corr) // 2
    window = corr[mid - max_lag : mid + max_lag]
    peak_idx = int(np.argmax(np.abs(window)))
    return max(0, peak_idx - max_lag)


def nlms_aec(
    far_end: np.ndarray,
    near_end: np.ndarray,
    taps: int,
    mu: float,
    delay_samples: int = 0,
) -> np.ndarray:
    """Offline NLMS echo canceller. far_end and near_end must be the same
    length and sample rate. Returns the near-end residual after
    subtracting the adaptively-predicted echo of far_end.

    delay_samples (from estimate_delay_samples()) shifts the filter's
    window to start delay_samples behind the current sample instead of
    at it, so taps only needs to cover the residual echo-path spread
    (room reverb tail) around the true delay, not the true delay itself.

    Chronological (non-reversed) tap alignment: history[i:i+taps] is
    oldest-to-newest, and w is indexed the same way, so no per-sample
    reversal copy is needed."""
    if len(far_end) != len(near_end):
        raise ValueError("far_end and near_end must be the same length")
    n = len(near_end)
    eps = 1e-6
    w = np.zeros(taps, dtype=np.float64)
    history = np.concatenate(
        [
            np.zeros(taps - 1 + delay_samples, dtype=np.float64),
            far_end.astype(np.float64),
        ]
    )
    near = near_end.astype(np.float64)
    residual = np.empty(n, dtype=np.float64)
    for i in range(n):
        x = history[i : i + taps]
        y = np.dot(w, x)
        e = near[i] - y
        residual[i] = e
        w += (mu * e / (np.dot(x, x) + eps)) * x
    return np.clip(residual, -1.0, 1.0).astype(np.float32)


def rms(samples: np.ndarray) -> float:
    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))


def suppression_db(before: np.ndarray, after: np.ndarray) -> float:
    before_rms, after_rms = rms(before), rms(after)
    if after_rms <= 0.0:
        return float("inf")
    if before_rms <= 0.0:
        return 0.0
    return 20.0 * float(np.log10(before_rms / after_rms))


def window_slice(
    samples: np.ndarray, start_seconds: float, end_seconds: float
) -> np.ndarray:
    start = max(0, int(start_seconds * VAD_SAMPLE_RATE))
    end = min(len(samples), int(end_seconds * VAD_SAMPLE_RATE))
    return samples[start:end]


def run_vad(residual: np.ndarray, threshold: float) -> list[dict]:
    model = load_silero_vad()
    return get_speech_timestamps(
        torch.from_numpy(residual),
        model,
        threshold=threshold,
        sampling_rate=VAD_SAMPLE_RATE,
        return_seconds=True,
    )


def classify_segments(
    raw_segments: list[dict], tts_start_seconds: float, tts_end_seconds: float
) -> list[VadSegment]:
    segments = []
    for stamp in raw_segments:
        overlaps = stamp["start"] < tts_end_seconds and stamp["end"] > tts_start_seconds
        segments.append(
            VadSegment(
                start_seconds=stamp["start"],
                end_seconds=stamp["end"],
                overlaps_tts_window=overlaps,
            )
        )
    return segments


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--label",
        required=True,
        help="Run label for this room/distance condition, e.g. quiet-close.",
    )
    parser.add_argument(
        "--scenario",
        choices=("silent", "interrupt"),
        required=True,
        help="silent: stay quiet through the whole response (self-hearing "
        "case). interrupt: speak over Jarvis partway through (barge-in case).",
    )
    parser.add_argument("--text", default=DEFAULT_TEXT, help="Text Jarvis speaks.")
    parser.add_argument("--lead-in-seconds", type=float, default=2.0)
    parser.add_argument("--tail-seconds", type=float, default=2.0)
    parser.add_argument(
        "--taps",
        type=int,
        default=1024,
        help="NLMS filter length in samples at 16 kHz "
        "(1024 = 64 ms of echo-path coverage).",
    )
    parser.add_argument(
        "--mu", type=float, default=0.5, help="NLMS step size, 0 < mu <= 1."
    )
    parser.add_argument(
        "--max-delay-seconds",
        type=float,
        default=0.6,
        help="Search range for the coarse far-end/near-end delay estimate "
        "(device buffering latency, not just acoustic travel time).",
    )
    parser.add_argument(
        "--output-device",
        help="sounddevice output device index or name. Default: system default.",
    )
    parser.add_argument(
        "--input-device",
        help="sounddevice input device index or name, overriding "
        "config.microphone entirely (e.g. to try a WASAPI copy of the "
        "same physical mic instead of the configured MME one).",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser


async def main() -> None:
    args = build_arg_parser().parse_args()
    settings = load_settings()

    print(f"label: {args.label}")
    print(f"scenario: {args.scenario}")
    print(f"candidate: NLMS numpy adaptive filter, taps={args.taps}, mu={args.mu}")
    print(f"vad_threshold: {settings.vad.threshold}")
    print(f"microphone_device: {settings.microphone.device or '<default>'}")

    far_end_native, native_sample_rate = await synthesize_far_end(settings, args.text)
    print(f"native_sample_rate: {native_sample_rate}")

    devices = resolve_io_devices(settings, args.output_device, args.input_device)
    print(f"input_device_index: {devices[0]}")
    print(f"output_device: {devices[1]}")

    if args.scenario == "silent":
        print("Recording now - stay quiet.")
    else:
        print("Recording now - interrupt Jarvis partway through.")
    recording = pad_and_record(
        far_end_native,
        native_sample_rate,
        args.lead_in_seconds,
        args.tail_seconds,
        devices,
    )
    total_seconds = len(recording.near_end) / native_sample_rate
    print(f"recording_duration_seconds: {total_seconds:.2f}")
    print(
        f"tts_window_seconds: {recording.tts_start_seconds:.2f}-"
        f"{recording.tts_end_seconds:.2f}"
    )

    far_16k = resample_to_vad_rate(recording.far_end, native_sample_rate)
    near_16k = resample_to_vad_rate(recording.near_end, native_sample_rate)

    delay_probe_start = int(recording.tts_start_seconds * VAD_SAMPLE_RATE)
    delay_samples = estimate_delay_samples(
        far_16k[delay_probe_start:],
        near_16k[delay_probe_start:],
        args.max_delay_seconds,
    )
    print(f"estimated_delay_ms: {delay_samples / VAD_SAMPLE_RATE * 1000:.1f}")

    t0 = time.perf_counter()
    residual = nlms_aec(far_16k, near_16k, args.taps, args.mu, delay_samples)
    elapsed = time.perf_counter() - t0
    samples_per_20ms = int(VAD_SAMPLE_RATE * 0.02)
    est_ms_per_block = (elapsed / len(near_16k)) * samples_per_20ms * 1000.0
    print(f"aec_processing_seconds: {elapsed:.2f}")
    print(f"aec_estimated_ms_per_20ms_block: {est_ms_per_block:.3f}")

    near_window = window_slice(
        near_16k, recording.tts_start_seconds, recording.tts_end_seconds
    )
    residual_window = window_slice(
        residual, recording.tts_start_seconds, recording.tts_end_seconds
    )
    supp_db = suppression_db(near_window, residual_window)
    print(f"suppression_db: {supp_db:.2f}")

    raw_segments = run_vad(residual, settings.vad.threshold)
    segments = classify_segments(
        raw_segments, recording.tts_start_seconds, recording.tts_end_seconds
    )
    print(f"vad_segments_on_residual: {len(segments)}")
    for segment in segments:
        print(
            f"  segment: start={segment.start_seconds:.2f}s "
            f"end={segment.end_seconds:.2f}s "
            f"overlaps_tts_window={segment.overlaps_tts_window}"
        )
    any_overlap = any(segment.overlaps_tts_window for segment in segments)
    if args.scenario == "silent":
        verdict = (
            "FALSE POSITIVE - VAD fired on self-heard TTS" if any_overlap else "clean"
        )
        print(f"self_hearing_verdict: {verdict}")
    else:
        verdict = (
            "detected - verify manually this matches when you actually spoke"
            if any_overlap
            else "NOT DETECTED - the interrupt was missed"
        )
        print(f"interrupt_verdict: {verdict}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    prefix = args.out_dir / f"{args.label}-{args.scenario}"
    far_path, near_path, residual_path = (
        prefix.with_name(prefix.name + "-farend.wav"),
        prefix.with_name(prefix.name + "-nearend.wav"),
        prefix.with_name(prefix.name + "-residual.wav"),
    )
    sf.write(far_path, far_16k, VAD_SAMPLE_RATE)
    sf.write(near_path, near_16k, VAD_SAMPLE_RATE)
    sf.write(residual_path, residual, VAD_SAMPLE_RATE)
    print(f"far_end_wav: {far_path}")
    print(f"near_end_wav: {near_path}")
    print(f"residual_wav: {residual_path}")


if __name__ == "__main__":
    asyncio.run(main())
