#!/usr/bin/env python3
"""Manual handoff for task-05: live speaker check of tts.py.

Not an automated test - speaker output is hardware-dependent per
CLAUDE.md's testing protocol, so this is run by hand. Confirms audio
starts promptly once the first sentence is ready (no unexpected
synthesis/queueing delay), no clipped audio at sentence boundaries, and
correct Russian pronunciation. This is a component check on tts.py's own
synthesis+playback slice, not the end-to-end target - task-07 measures
the full pipeline from audio_in.py's publish to first audio.

Usage:
  python setup_tts_model.py  # once, requires network - see tts.py
  python manual/manual_check_tts.py
"""

import asyncio
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jarvis.core.config import load_settings
from jarvis.dialog.backend import LatencyMetrics, ResponseComplete, ResponseToken
from jarvis.audio.tts import TtsOutput

# Deliberately includes a decimal number and a known abbreviation, so the
# sentence buffer's handling of both is also audible, not just tested.
SCRIPTED_TOKENS = [
    "Привет! ",
    "Это тестовое ",
    "предложение, ",
    "чтобы проверить, ",
    "как звучит ",
    "синтез речи. ",
    "А вот и второе, ",
    "чуть подлиннее, ",
    "предложение с числом 3.14 ",
    "и сокращением т.е. ",
    "так далее. ",
    "Последнее предложение без пробела в конце",
]


async def main() -> None:
    settings = load_settings()
    tts = TtsOutput(settings.tts)

    print("Streaming a scripted response through the real sentence buffer,")
    print("Silero synthesis, and speaker playback. If you haven't already,")
    print("run `python setup_tts_model.py` once first (requires network) -")
    print("this script raises a clear error rather than reaching for the")
    print("network itself if the model isn't cached yet.")
    print("Listen for: prompt start, no clipping at sentence boundaries,")
    print("correct Russian pronunciation, that '3.14' is actually SPOKEN")
    print("(as 'три целых четырнадцать сотых', not silence - Silero's own")
    print("symbol set has no digits, normalize_numbers() works around it),")
    print("and that 'т.е.' is not cut mid-abbreviation.\n")

    start = time.time()
    for piece in SCRIPTED_TOKENS:
        await tts.on_token(ResponseToken(text=piece))
        await asyncio.sleep(0.05)  # simulate token arrival pace

    await tts.on_response_complete(
        ResponseComplete(
            metrics=LatencyMetrics(
                load_seconds=0.0,
                prompt_eval_seconds=0.0,
                eval_seconds=0.0,
                eval_count=0,
            )
        )
    )
    await tts.wait_for_pending()
    print(f"\nDone in {time.time() - start:.1f}s total.")


if __name__ == "__main__":
    asyncio.run(main())
