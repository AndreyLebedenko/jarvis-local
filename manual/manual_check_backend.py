#!/usr/bin/env python3
"""Manual handoff for task-03: live check of backend.py against real Ollama.

Not an automated test - the live Ollama endpoint is hardware/environment
-dependent per CLAUDE.md's testing protocol, so this is run by hand.
Confirms OllamaBackend.chat() succeeds end-to-end with a real audio clip
and a real screenshot, and that measured latency is in the neighborhood
of PROJECT.md's day-0 numbers (load ~0.3 s warm, prefill ~0.1-0.3 s,
~87 tok/s generation).

Usage:
  python manual/manual_check_backend.py audio audio/a1.wav
  python manual/manual_check_backend.py image path/to/screenshot.png
"""

import argparse
import asyncio
import base64
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jarvis.core.bus import EventBus
from jarvis.core.config import load_settings
from jarvis.dialog.backend import OllamaBackend, ResponseComplete, ResponseToken


def b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


async def run(kind: str, path: str) -> None:
    settings = load_settings()
    bus = EventBus()

    async def on_token(token: ResponseToken) -> None:
        print(token.text, end="", flush=True)

    async def on_complete(event: ResponseComplete) -> None:
        m = event.metrics
        tok_per_s = m.eval_count / m.eval_seconds if m.eval_seconds else 0.0
        print(
            f"\n\n[load {m.load_seconds:.1f}s | prefill {m.prompt_eval_seconds:.1f}s "
            f"| gen {m.eval_seconds:.1f}s | {m.eval_count} tokens | ~{tok_per_s:.0f} tok/s]"
        )

    bus.subscribe(ResponseToken, on_token)
    bus.subscribe(ResponseComplete, on_complete)

    backend = OllamaBackend(bus=bus, settings=settings.backend)

    prompt = (
        "Transcribe this recording verbatim, word for word."
        if kind == "audio"
        else "Read all text visible in this screenshot, preserving layout."
    )
    messages = [{"role": "user", "content": prompt}]

    t0 = time.time()
    await backend.chat(messages=messages, images_b64=[b64(path)])
    print(f"\n[wall clock: {time.time() - t0:.1f}s]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["audio", "image"])
    parser.add_argument("path")
    args = parser.parse_args()
    asyncio.run(run(args.kind, args.path))
