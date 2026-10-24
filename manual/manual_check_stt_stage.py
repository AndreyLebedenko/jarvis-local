#!/usr/bin/env python3
"""Human-run check of the speech-to-text stage (task v2.1.0-3).

Handoff with every step: manual/stt-stage-handoff.md.

  python -m manual.manual_check_stt_stage guard --wavs DIR
  python -m manual.manual_check_stt_stage transcribe --wavs DIR [--limit N]

`guard` needs no Whisper: it prints, per recording, the seconds of speech the
Silero VAD finds, for the spikes' silence and noise controls and for the real
utterances in DIR, so you can see whether `[personal_proxy].stt_min_speech_seconds`
separates them. `transcribe` loads Whisper (GPU or CPU per `[personal_proxy]
.stt_device`) and sends each recording through the guarded function.
"""

from __future__ import annotations

import argparse
import io
import time
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import soundfile as sf

from jarvis.core.config import load_settings
from jarvis.personal_proxy.stt.guarded_transcription import transcribe_guarded
from jarvis.personal_proxy.stt.silero_probabilities import (
    SAMPLE_RATE,
    SileroSpeechProbabilities,
)
from jarvis.personal_proxy.stt.speech_guard import NoSpeech, speech_seconds
from jarvis.personal_proxy.stt.stt_whisper import FasterWhisperEngine
from manual.personal_proxy.audio import control_audio
from manual.personal_proxy.corpus import CONTROLS

DEFAULT_TRANSCRIBE_LIMIT = 5


def decode(source: Path | io.BytesIO) -> np.ndarray:
    samples, rate = sf.read(source, dtype="float32")
    if rate != SAMPLE_RATE:
        raise ValueError(f"expected {SAMPLE_RATE} Hz audio, got {rate}")
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    return samples.astype(np.float32)


def control_clips() -> list[tuple[str, np.ndarray]]:
    clips = []
    for control in CONTROLS:
        audio = control_audio(control)
        if audio is not None:
            clips.append((control.control_id, decode(io.BytesIO(audio))))
    return clips


def utterance_clips(wavs: Path) -> list[tuple[str, np.ndarray]]:
    paths = sorted(wavs.glob("*.wav"))
    if not paths:
        raise SystemExit(f"no .wav files in {wavs}")
    return [(path.stem, decode(path)) for path in paths]


def command_guard(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    threshold = settings.vad.threshold
    minimum = settings.personal_proxy.stt_min_speech_seconds
    probabilities = SileroSpeechProbabilities()
    print(f"[vad].threshold = {threshold}; stt_min_speech_seconds = {minimum}")
    print("kind       speech_s  length_s  verdict   id")
    measured: dict[str, list[float]] = {"control": [], "utterance": []}
    groups = (
        ("control", control_clips()),
        ("utterance", utterance_clips(args.wavs)),
    )
    for kind, clips in groups:
        for clip_id, clip in clips:
            heard = speech_seconds(probabilities(clip), threshold)
            measured[kind].append(heard)
            verdict = "speech" if heard >= minimum else "NO SPEECH"
            print(
                f"{kind:<10} {heard:8.2f}  {len(clip) / SAMPLE_RATE:8.2f}  "
                f"{verdict:<9} {clip_id}"
            )
    print(
        f"most speech in any control: {max(measured['control']):.2f} s; "
        f"least speech in any utterance: {min(measured['utterance']):.2f} s"
    )
    return 0


def command_transcribe(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    proxy = settings.personal_proxy
    print(f"loading {proxy.stt_model} on {proxy.stt_device} (local files only)...")
    started = time.perf_counter()
    engine = FasterWhisperEngine(proxy)
    print(f"loaded in {time.perf_counter() - started:.1f} s")
    probabilities = SileroSpeechProbabilities()
    clips = control_clips() + utterance_clips(args.wavs)[: args.limit]
    for clip_id, clip in clips:
        started = time.perf_counter()
        result = transcribe_guarded(
            clip,
            engine,
            probabilities,
            vad_threshold=settings.vad.threshold,
            minimum_speech_seconds=proxy.stt_min_speech_seconds,
        )
        elapsed = time.perf_counter() - started
        print(f"\n== {clip_id} ({elapsed:.2f} s including the guard)")
        if isinstance(result, NoSpeech):
            print(
                f"NO SPEECH: {result.speech_seconds:.2f} s heard, "
                f"{result.required_seconds:.2f} s required; engine not called"
            )
            continue
        print(f"text: {result.text}")
        for word in result.words:
            print(
                f"  {word.start_seconds:6.2f}-{word.end_seconds:6.2f} "
                f"p={word.probability:.3f} {word.word}"
            )
        for segment in result.segments:
            print(
                f"  segment avg_logprob={segment.avg_logprob:.3f} "
                f"no_speech_prob={segment.no_speech_prob:.3f} "
                f"compression_ratio={segment.compression_ratio:.2f}"
            )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    commands = parser.add_subparsers(dest="command", required=True)
    guard = commands.add_parser("guard")
    guard.add_argument("--wavs", type=Path, required=True)
    guard.set_defaults(handler=command_guard)
    transcribe = commands.add_parser("transcribe")
    transcribe.add_argument("--wavs", type=Path, required=True)
    transcribe.add_argument("--limit", type=int, default=DEFAULT_TRANSCRIBE_LIMIT)
    transcribe.set_defaults(handler=command_transcribe)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
