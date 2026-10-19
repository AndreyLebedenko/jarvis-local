#!/usr/bin/env python3
"""Human-run recorder of the personal-proxy spike corpus.

Reads each scripted utterance aloud through the production capture path (the
configured microphone, the Silero VAD chunker, the short-clip padding), saving
one WAV per utterance plus a manifest. Uses the microphone and the speakers,
so the human runs it.

Usage:
  python -m manual.manual_record_personal_proxy_corpus
  python -m manual.manual_record_personal_proxy_corpus --out DIR
  python -m manual.manual_record_personal_proxy_corpus --redo id_email --redo q_judge

Per utterance: read the shown text after pressing Enter. Then Enter accepts the
take, r records it again, p plays it back, q quits (accepted takes are kept;
run again to continue where you stopped).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import sys
from collections.abc import Sequence
from pathlib import Path

import sounddevice as sd
import soundfile as sf

from jarvis.audio.input import (
    AudioInput,
    MicrophoneCaptureFailed,
    UtteranceChunk,
    VadChunker,
    stream_factory_for_device,
)
from jarvis.core.bus import EventBus
from jarvis.core.config import load_settings
from manual.personal_proxy.corpus import CORPUS, Utterance, corpus_problems
from manual.personal_proxy.corpus_v2 import (
    OWNER_VOICE,
    corpus_v2_fingerprint,
    corpus_v2_problems,
    utterances_of_voice,
)
from manual.personal_proxy.recorder import (
    Choice,
    RecordingDirectoryError,
    record_corpus,
)

DEFAULT_OUT = Path("personal_proxy_corpus_wavs")
DEFAULT_OUT_V2 = Path("personal_proxy_corpus_v2_wavs")
DEFAULT_CONFIG = Path("config.toml")
_CHOICES = {"": Choice.ACCEPT, "r": Choice.REDO, "p": Choice.PLAY, "q": Choice.QUIT}


class LiveTakeSource:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.failure: str | None = None

    async def on_chunk(self, chunk: UtteranceChunk) -> None:
        await self._queue.put(chunk.wav_bytes)

    async def on_failure(self, failure: MicrophoneCaptureFailed) -> None:
        self.failure = failure.reason

    async def next_take(self, timeout_seconds: float) -> bytes | None:
        while not self._queue.empty():
            self._queue.get_nowait()
        if self.failure is not None:
            raise RuntimeError(f"microphone capture failed: {self.failure}")
        try:
            return await asyncio.wait_for(self._queue.get(), timeout_seconds)
        except TimeoutError:
            return None


class TerminalInteraction:
    async def announce(self, index: int, total: int, utterance: Utterance) -> None:
        print(
            f"\n[{index}/{total}] {utterance.utterance_id} "
            f"(~{utterance.estimated_seconds:.0f} s)\n",
            flush=True,
        )
        print(f"    {utterance.text}\n", flush=True)

    async def wait_ready(self) -> None:
        await asyncio.to_thread(input, "Press Enter, then read the text aloud... ")
        print("Recording. Read now; stay silent when you finish.", flush=True)

    async def review(self, seconds: float, advice: str | None) -> Choice:
        print(f"Captured {seconds:.1f} s." + (f" NOTE: {advice}." if advice else ""))
        while True:
            answer = await asyncio.to_thread(
                input, "Enter=accept  r=redo  p=play  q=quit > "
            )
            choice = _CHOICES.get(answer.strip().lower())
            if choice is not None:
                return choice

    def play(self, wav: bytes) -> None:
        samples, rate = sf.read(io.BytesIO(wav), dtype="float32")
        sd.play(samples, rate)
        sd.wait()

    def info(self, message: str) -> None:
        print(message, flush=True)


async def run_recorder(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    source = LiveTakeSource()
    bus = EventBus()
    bus.subscribe(UtteranceChunk, source.on_chunk)
    bus.subscribe(MicrophoneCaptureFailed, source.on_failure)
    audio_input = AudioInput(
        bus,
        VadChunker(settings.vad),
        stream_factory_for_device(
            settings.microphone.device, settings.microphone.host_api
        ),
    )
    loop_task = asyncio.create_task(audio_input.run_microphone_loop())
    try:
        summary = await record_corpus(
            source,
            TerminalInteraction(),
            args.out,
            redo=set(args.redo),
            corpus=recording_corpus(args),
            fingerprint=recording_fingerprint(args),
        )
    finally:
        await audio_input.stop()
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task
    state = "stopped early" if summary.quit_early else "complete"
    print(
        f"\nRecorded {summary.recorded} now, {summary.skipped} already present "
        f"({state}). Directory: {args.out}"
    )
    return 0


def recording_corpus(args: argparse.Namespace) -> tuple[Utterance, ...]:
    if args.corpus == "v2":
        return utterances_of_voice(OWNER_VOICE)
    return CORPUS


def recording_fingerprint(args: argparse.Namespace) -> str | None:
    return corpus_v2_fingerprint() if args.corpus == "v2" else None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", choices=("v1", "v2"), default="v1")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--redo", action="append", default=[], metavar="UTTERANCE_ID")
    args = parser.parse_args(argv)
    if args.out is None:
        args.out = DEFAULT_OUT_V2 if args.corpus == "v2" else DEFAULT_OUT
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    problems = corpus_v2_problems() if args.corpus == "v2" else corpus_problems()
    if problems:
        print("The frozen corpus is inconsistent:\n  " + "\n  ".join(problems))
        return 2
    try:
        return asyncio.run(run_recorder(args))
    except (RecordingDirectoryError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
