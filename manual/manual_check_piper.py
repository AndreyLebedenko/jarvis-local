#!/usr/bin/env python3
"""Manual handoff for a Piper-only local TTS check.

This is not an automated test. It is meant for the human to run on the
real machine after installing `piper-tts`. The script measures:
- Piper model load time;
- first-audio latency from the first streamed token to the first audible
  playback;
- total synthesis/playback time for each prompt.

The prompt set is intentionally short and mixed-language so the user can
hear basic Russian, English, numbers, and code-like text without the
extra moving parts from the larger TTS-engine spike.

Usage examples:
  python manual/manual_check_piper.py --model D:\\voices\\en_US-lessac-medium.onnx
  python manual/manual_check_piper.py --model D:\\voices\\en_US-lessac-medium.onnx --use-cuda
  python manual/manual_check_piper.py --model D:\\voices\\en_US-lessac-medium.onnx --config D:\\voices\\en_US-lessac-medium.onnx.json

Expected output fields:
  model, config, use_cuda, load_seconds
  prompt rows: label, first_audio_seconds, total_seconds, chunk_count
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import sounddevice as sd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from manual.manual_check_tts_engines import PROMPTS, split_text_into_chunks
except ModuleNotFoundError:
    from manual_check_tts_engines import PROMPTS, split_text_into_chunks

TOKEN_DELAY_SECONDS = 0.05
DEFAULT_MODEL_PATH = Path(
    ".local-models/piper/en_US-lessac-medium/en_US-lessac-medium.onnx"
)


@dataclass(frozen=True)
class PiperMeasurement:
    label: str
    first_audio_seconds: float
    total_seconds: float
    chunk_count: int


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        help=(
            "Path to the Piper .onnx model. Defaults to the repo-local "
            f"{DEFAULT_MODEL_PATH} if present."
        ),
    )
    parser.add_argument(
        "--config",
        help="Optional path to the Piper .json config (defaults to <model>.json if present)",
    )
    parser.add_argument(
        "--use-cuda",
        action="store_true",
        help="Pass use_cuda=True to PiperVoice.load()",
    )
    return parser


def resolve_config_path(model_path: Path, config_arg: str | None) -> Path | None:
    if config_arg:
        config_path = Path(config_arg)
        if not config_path.exists():
            raise FileNotFoundError(f"Piper config file does not exist: {config_path}")
        return config_path

    derived = Path(f"{model_path}.json")
    if derived.exists():
        return derived
    raise FileNotFoundError(
        f"No Piper config file was supplied and the default {derived} was not found."
    )


def resolve_model_path(model_arg: str | None) -> Path:
    if model_arg:
        model_path = Path(model_arg)
        if not model_path.exists():
            raise FileNotFoundError(f"Piper model file does not exist: {model_path}")
        return model_path

    if DEFAULT_MODEL_PATH.exists():
        return DEFAULT_MODEL_PATH

    raise FileNotFoundError(
        f"No Piper model was supplied and the default {DEFAULT_MODEL_PATH} was not found."
    )


def load_voice(model_path: Path, config_path: Path | None, use_cuda: bool):
    from piper.voice import PiperVoice

    load_started = time.perf_counter()
    voice = PiperVoice.load(
        model_path=model_path,
        config_path=config_path,
        use_cuda=use_cuda,
    )
    return voice, time.perf_counter() - load_started


def synthesize_and_play(voice, text: str) -> tuple[float, int]:
    first_play_at: float | None = None
    chunk_count = 0

    for chunk in voice.synthesize(text):
        chunk_count += 1
        if first_play_at is None:
            first_play_at = time.perf_counter()
        sd.play(chunk.audio_int16_array, chunk.sample_rate)
        sd.wait()

    if first_play_at is None:
        raise RuntimeError("Piper returned no audio chunks")

    return first_play_at, chunk_count


async def measure_prompt(voice, label: str, text: str) -> PiperMeasurement:
    start = time.perf_counter()
    for _chunk in split_text_into_chunks(text):
        # Simulate token arrival so the manual check measures
        # first-token-to-first-audio latency, not just raw synthesis time.
        await asyncio.sleep(TOKEN_DELAY_SECONDS)

    first_play_at, chunk_count = await asyncio.to_thread(
        synthesize_and_play, voice, text
    )
    total_seconds = time.perf_counter() - start
    return PiperMeasurement(
        label=label,
        first_audio_seconds=first_play_at - start,
        total_seconds=total_seconds,
        chunk_count=chunk_count,
    )


async def main() -> None:
    args = build_arg_parser().parse_args()
    model_path = resolve_model_path(args.model)
    config_path = resolve_config_path(model_path, args.config)

    voice, load_seconds = await asyncio.to_thread(
        load_voice, model_path, config_path, args.use_cuda
    )

    print("Piper-only manual check")
    print(f"model: {model_path}")
    print(f"config: {config_path if config_path is not None else 'unset'}")
    print(f"use_cuda: {args.use_cuda}")
    print(f"load_seconds: {load_seconds:.2f}")
    print("prompt,label,first_audio_seconds,total_seconds,chunk_count")

    for prompt in PROMPTS:
        measurement = await measure_prompt(voice, prompt.label, prompt.text)
        print(
            f"prompt,{measurement.label},{measurement.first_audio_seconds:.2f},"
            f"{measurement.total_seconds:.2f},{measurement.chunk_count}"
        )


if __name__ == "__main__":
    asyncio.run(main())
