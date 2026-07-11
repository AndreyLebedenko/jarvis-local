#!/usr/bin/env python3
"""Manual handoff for story-v1.2.8-task-2: live speaker check of the
speech-markup TTS integration, no LLM involved.

Not an automated test - speaker output is hardware-dependent per
CLAUDE.md's testing protocol, so this is run by hand. Streams a real
Gemma4-style marked-up answer (the Shakespeare example from the
2026-07-09 session, trimmed) through the full production path:
SpeechMarkupStream -> per-language sentence buffering -> SileroEngine ->
ordered playback. The runtime engine is still Silero-only, so English
segments are heard through the transliteration fallback - the point of
this check is markup handling, not English pronunciation quality (that
waits for the engine-routing task).

Usage:
  python setup_tts_model.py           # once, requires network - see tts.py
  python manual/manual_check_speech_markup.py
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
from tts import TtsOutput

# A trimmed version of the real marked-up Gemma4 answer, kept verbatim in
# shape: <speak> wrapper, per-sentence <lang> blocks, short English
# inserts, and the Love/и/Dove single-word alternation (the connective
# carry case). Deliberately split into chunks that cut one tag in half
# ("<lang xml:l" + "ang=...") to exercise the incremental scanner's
# held-back tail on the real audio path, not just in unit tests.
SCRIPTED_TOKENS = [
    "<speak>\n",
    '<lang xml:lang="ru">Здравствуйте. Я проанализировал ваш вопрос ',
    "о поэзии Уильяма Шекспира.</lang>\n",
    '<lang xml:l',
    'ang="en">William Shakespeare</lang>\n',
    '<lang xml:lang="ru">Основная причина кроется в его предпочтении ',
    "белого стиха.</lang>\n",
    '<lang xml:lang="en">Blank verse</lang>\n',
    '<lang xml:lang="ru">Это пятистопный ямб без конечной рифмы. ',
    "Он передает естественную речь, сохраняя поэтический ритм.</lang>\n",
    '<lang xml:lang="ru">Классическая пара рифм:</lang>\n',
    '<lang xml:lang="en">Love</lang>\n',
    '<lang xml:lang="ru">и</lang>\n',
    '<lang xml:lang="en">Dove</lang>\n',
    '<lang xml:lang="ru">Таким образом, отсутствие явной рифмы - это ',
    "осознанный художественный выбор автора.</lang>\n",
    "</speak>",
]


async def main() -> None:
    settings = load_settings()
    tts = TtsOutput(settings.tts)

    print("Streaming a marked-up Shakespeare answer through the real")
    print("markup scanner, sentence buffer, Silero synthesis, and speaker")
    print("playback (no LLM). Run `python setup_tts_model.py` once first")
    print("if the model isn't cached yet.\n")
    print("Listen for:")
    print(" 1. NO spoken tag junk anywhere - no 'lang', 'xml', 'speak',")
    print("    angle-bracket noise, or English attribute words between")
    print("    sentences (the old HTMLParser bug class).")
    print(" 2. 'William Shakespeare' and 'Blank verse' spoken (via the")
    print("    transliteration fallback - accented, but present), even")
    print("    though the first tag arrives split across two chunks.")
    print(" 3. The 'Love' / 'и' / 'Dove' run: 'и' must NOT be its own")
    print("    tiny utterance - it should glue to 'Dove' as one unit.")
    print(" 4. Sentence flow: multi-sentence Russian blocks split at")
    print("    sentence boundaries as before, English inserts start")
    print("    without waiting for a following period.")
    print(" 5. Order: everything plays in reading order, no overlaps.\n")

    start = time.time()
    for piece in SCRIPTED_TOKENS:
        await tts.on_token(ResponseToken(text=piece))
        await asyncio.sleep(0.05)  # simulate token arrival pace

    await tts.on_response_complete(
        ResponseComplete(
            metrics=LatencyMetrics(
                load_seconds=0.0, prompt_eval_seconds=0.0, eval_seconds=0.0, eval_count=0
            )
        )
    )
    await tts.wait_for_pending()
    print(f"\nDone in {time.time() - start:.1f}s total.")


if __name__ == "__main__":
    asyncio.run(main())
