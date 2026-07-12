#!/usr/bin/env python3
"""Manual handoff for task-04: live microphone check of audio_in.py.

Not an automated test - the microphone is hardware-dependent per
CLAUDE.md's testing protocol, so this is run by hand. Confirms real
speech triggers a chunk publish, silence does not, and end-of-utterance
latency feels reasonable for a conversational pace.

Usage:
  python -m manual.manual_check_audio_in
  (speak a few short sentences with pauses between them, then Ctrl+C)

Each published utterance is printed (timing, duration) and saved as a
wav file under manual_check_audio_out/ so you can listen back and
confirm the boundaries are sensible.
"""

import asyncio
import time
from pathlib import Path

from jarvis.audio.input import AudioInput, UtteranceChunk, VadChunker
from jarvis.core.bus import EventBus
from jarvis.core.config import load_settings

OUT_DIR = Path("manual_check_audio_out")


async def main() -> None:
    settings = load_settings()
    bus = EventBus()
    OUT_DIR.mkdir(exist_ok=True)
    count = 0
    last_publish = time.time()

    async def on_chunk(chunk: UtteranceChunk) -> None:
        nonlocal count, last_publish
        count += 1
        now = time.time()
        duration = chunk.end_seconds - chunk.start_seconds
        out_path = OUT_DIR / f"chunk_{count:03d}.wav"
        out_path.write_bytes(chunk.wav_bytes)
        print(
            f"[chunk {count}] {duration:.2f}s speech "
            f"({chunk.start_seconds:.2f}s-{chunk.end_seconds:.2f}s in buffer), "
            f"{now - last_publish:.2f}s since previous publish -> {out_path}"
        )
        last_publish = now

    bus.subscribe(UtteranceChunk, on_chunk)

    chunker = VadChunker(settings.vad)
    audio_input = AudioInput(bus=bus, chunker=chunker)

    print("Listening on the default microphone (16 kHz mono).")
    print("Speak a few short sentences with pauses between them.")
    print("Stay quiet for a few seconds too, to confirm silence publishes nothing.")
    print("Press Ctrl+C to stop.\n")
    await audio_input.run_microphone_loop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
