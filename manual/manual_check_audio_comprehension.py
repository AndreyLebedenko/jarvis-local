#!/usr/bin/env python3
"""Does the model still comprehend speech, or only respond politely to it?

Human-run: this talks to the live Ollama endpoint.

**Why this replaced the earlier check.** The first version asked whether
the model "heard" the audio and accepted "Да, я вас отлично слышу" as a
yes. The owner destroyed that criterion in one move: with the microphone
gain at zero, on a recording where nothing is intelligible, the model
still answered that it hears fine. A question like "как ты меня слышишь"
can be answered from the placeholder alone - no comprehension required -
so every earlier "heard" result proves only that the model did not
refuse.

A usable criterion has to be unanswerable without the content. The
journal holds exactly that: on 2026-07-17 the model answered spoken
questions with cyclic cosmology, AI addiction, and sycophancy. Those
answers cannot be produced from a placeholder. Replaying those same wavs
today, in a fresh context, asks the only question that matters - can the
model still do what it demonstrably did then?

Read the output as three separate facts:

- **replay, fresh context** - today's answer beside July's. Same subject
  means comprehension still works; a generic offer to help means it does
  not, and the refusals are a symptom rather than the disease.
- **replay, after a refusal** - the same audio with one refusal in
  history. This is the confirmed self-consistency effect; here it is
  measured against content instead of politeness.
- **negative control** - a recording with nothing intelligible in it
  (`--quiet-wav`). Any confident, specific answer here is a bluff, and
  calibrates how much to trust the other two.

Usage:
  python -m manual.manual_check_audio_comprehension
  python -m manual.manual_check_audio_comprehension --quiet-wav path/to/silent.wav
"""

import argparse
import asyncio
import base64
import json
import time
from pathlib import Path

import httpx

from jarvis.audio.input import SAMPLE_RATE
from jarvis.core.bus import EventBus
from jarvis.core.config import load_settings
from jarvis.core.lifecycle import VOICE_PLACEHOLDER_TEXT
from jarvis.dialog.backend import OllamaBackend
from jarvis.dialog.thinking_mode import ReasoningLevel
from jarvis.dialog.time_context import format_time_context

# Utterances whose 2026-07-17 answers prove comprehension outright: none
# of them can be produced from "[голосовое сообщение]" alone.
KNOWN_GOOD = [
    (
        "journal/20260717-222941-402ff9/utterance-20260717-223230-0004.wav",
        "Циклическая модель вселенной - космология, объяснение по существу",
    ),
    (
        "journal/20260717-233350-b8280f/utterance-20260717-233414-0002.wav",
        "Why people get addicted to AI - substantive explanation",
    ),
    (
        "journal/20260717-233350-b8280f/utterance-20260717-233739-0005.wav",
        "Sycophancy in AI - named the phenomenon and explained it",
    ),
]

REFUSAL_HISTORY = [
    {"role": "user", "content": VOICE_PLACEHOLDER_TEXT},
    {
        "role": "assistant",
        "content": (
            "Я не могу прослушать голосовое сообщение напрямую. "
            "Пожалуйста, напишите текстом то, что вы хотели сказать."
        ),
    },
]


async def ask(
    backend: OllamaBackend,
    client: httpx.AsyncClient,
    system_prompt: str,
    audio_b64: str,
    history: list | None = None,
) -> str:
    """One turn composed exactly as app.py's _start_turn composes it."""
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history or [])
    messages.append({"role": "system", "content": format_time_context(time.time())})
    messages.append({"role": "user", "content": VOICE_PLACEHOLDER_TEXT})
    payload = backend.build_payload(messages, [audio_b64], ReasoningLevel.OFF)
    payload["stream"] = False
    response = await client.post("/api/chat", json=payload)
    response.raise_for_status()
    return " ".join(json.loads(response.text)["message"]["content"].split())


def encoded(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"Missing wav: {path}")
    return base64.b64encode(path.read_bytes()).decode()


def synthetic_silence(seconds: float) -> str:
    """A wav with literally nothing in it, as the engine would encode one.

    The model tokenizes audio directly rather than transcribing it first
    (owner, 2026-07-25), so silence, noise without intelligible speech,
    and no audio at all are three different inputs and need not produce
    the same answer. This is the first of the three."""
    import io

    import numpy as np
    import soundfile as sf

    buffer = io.BytesIO()
    samples = np.zeros(int(SAMPLE_RATE * seconds), dtype=np.float32)
    sf.write(buffer, samples, SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return base64.b64encode(buffer.getvalue()).decode()


async def main_async(args: argparse.Namespace) -> None:
    settings = load_settings(args.config)
    print(f"model:    {settings.backend.model}")
    print(f"endpoint: {settings.backend.endpoint}\n")

    backend = OllamaBackend(EventBus(), settings.backend)
    async with httpx.AsyncClient(
        base_url=settings.backend.endpoint,
        timeout=httpx.Timeout(10.0, read=settings.backend.read_timeout_seconds),
    ) as client:
        for wav, july_answer in [] if args.skip_replays else KNOWN_GOOD:
            audio_b64 = encoded(Path(wav))
            print(f"--- {wav}")
            print(f"    2026-07-17: {july_answer}")
            fresh = await ask(backend, client, settings.prompts.system, audio_b64)
            print(f"RESULT|case=fresh context   |answer={fresh[:300]}")
            poisoned = await ask(
                backend, client, settings.prompts.system, audio_b64, REFUSAL_HISTORY
            )
            print(f"RESULT|case=after a refusal |answer={poisoned[:300]}\n")

        if args.silence_seconds:
            print(
                f"--- synthetic silence, {args.silence_seconds:g}s "
                "(control: nothing at all in the audio)"
            )
            answer = await ask(
                backend,
                client,
                settings.prompts.system,
                synthetic_silence(args.silence_seconds),
            )
            print(f"RESULT|case=silence        |answer={answer[:300]}\n")

        if args.quiet_wav:
            audio_b64 = encoded(Path(args.quiet_wav))
            print(f"--- {args.quiet_wav} (negative control: nothing intelligible)")
            answer = await ask(backend, client, settings.prompts.system, audio_b64)
            print(f"RESULT|case=unintelligible |answer={answer[:300]}\n")

    print(
        "Comprehension means today's answer is about July's subject. A claim\n"
        "to hear you well is not comprehension - a barely-audible recording\n"
        "produces one too. The refusal wording ('I cannot listen to audio')\n"
        "is what digital silence produces, so read it as 'there was nothing\n"
        "in this audio', not as the model denying it can hear at all."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--silence-seconds",
        type=float,
        default=0.0,
        help="also send a synthesized silent wav of this length",
    )
    parser.add_argument(
        "--skip-replays",
        action="store_true",
        help="run only the controls, without the three known-good replays",
    )
    parser.add_argument(
        "--quiet-wav",
        help="a recording with nothing intelligible in it, e.g. the zero-gain one",
    )
    parser.add_argument("--config", default="config.toml")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main_async(parse_args()))
