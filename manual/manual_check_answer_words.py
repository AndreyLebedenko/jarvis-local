#!/usr/bin/env python3
"""Human-run check of short spoken answers (handoff A of task v2.1.0-8).

Handoff with every step: manual/answer-words-handoff.md.

  python -m manual.manual_check_answer_words run [--repetitions N]

For each phrase of `manual.personal_proxy.answer_words.PHRASES` the tool asks you
to say it, ten times by default, through the production capture path (the
configured microphone and the Silero VAD chunker), then runs the take through the
guarded speech-to-text stage of task v2.1.0-3 and classifies the Whisper text
with `classify_answer`. It prints per take the Whisper text, the class, the
seconds of speech and whether the speech guard rejected the clip, then a table
per phrase. It uses the microphone, so the human runs it.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import sys
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

from jarvis.audio.input import (
    AudioInput,
    MicrophoneCaptureFailed,
    UtteranceChunk,
    VadChunker,
    stream_factory_for_device,
)
from jarvis.core.bus import EventBus
from jarvis.core.config import Settings, load_settings
from jarvis.personal_proxy.confirmation.confirmation_vocabulary import AnswerKind
from jarvis.personal_proxy.stt.silero_probabilities import SileroSpeechProbabilities
from jarvis.personal_proxy.stt.stt_whisper import FasterWhisperEngine
from manual.manual_check_stt_stage import decode
from manual.personal_proxy.answer_words import (
    PHRASES,
    REPETITIONS,
    Phrase,
    Trial,
    measure,
    render,
    render_trial,
    summarize,
)
from manual.personal_proxy.recorder import TAKE_TIMEOUT_SECONDS

NO_TAKE_MESSAGE = "no take arrived within the timeout; counted as rejected"


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


@contextlib.asynccontextmanager
async def live_takes(settings: Settings) -> AsyncIterator[LiveTakeSource]:
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
        yield source
    finally:
        await audio_input.stop()
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task


def print_settings(settings: Settings) -> None:
    proxy = settings.personal_proxy
    print(
        f"[vad].threshold = {settings.vad.threshold}; "
        f"[vad].request_end_pause_seconds = {settings.vad.request_end_pause_seconds}; "
        f"stt_min_speech_seconds = {proxy.stt_min_speech_seconds}; "
        f"stt_model = {proxy.stt_model}; stt_device = {proxy.stt_device}; "
        f"stt_language = {proxy.stt_language}"
    )


async def say_once(source: LiveTakeSource, phrase: Phrase) -> bytes | None:
    await asyncio.to_thread(input, f"Press Enter, then say: {phrase.text}  > ")
    return await source.next_take(TAKE_TIMEOUT_SECONDS)


async def command_run(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    proxy = settings.personal_proxy
    print_settings(settings)
    engine = FasterWhisperEngine(proxy)
    probabilities = SileroSpeechProbabilities()
    trials: list[Trial] = []
    async with live_takes(settings) as source:
        for phrase in PHRASES:
            for _ in range(args.repetitions):
                take = await say_once(source, phrase)
                if take is None:
                    print(NO_TAKE_MESSAGE)
                    trial = Trial(
                        phrase.text, phrase.expected, 0.0, True, "", AnswerKind.UNCLEAR
                    )
                else:
                    clip = decode(io.BytesIO(take))
                    trial = await asyncio.to_thread(
                        measure,
                        phrase,
                        clip,
                        engine,
                        probabilities,
                        vad_threshold=settings.vad.threshold,
                        minimum_speech_seconds=proxy.stt_min_speech_seconds,
                    )
                trials.append(trial)
                print(render_trial(len(trials), trial), flush=True)
    print("\n" + render(summarize(trials)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--repetitions", type=int, default=REPETITIONS)
    run.set_defaults(handler=command_run)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(args.handler(args))
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
