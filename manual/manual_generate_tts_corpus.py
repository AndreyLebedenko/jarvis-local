#!/usr/bin/env python3
"""Synthesizes the TTS voices of the second corpus (spike v2.1.0-9).

Reads each phrase of `manual.personal_proxy.corpus_v2` with the Silero voices
`eugene` and `baya` (model `v3_1_ru`, the production engine, including its
number and Latin preprocessing), shapes the audio like the production capture
(16 kHz mono, padded as `[vad]` in the config says), and adds the WAVs and
manifest entries to the corpus directory next to the owner's recordings.

  python -m manual.manual_generate_tts_corpus
  python -m manual.manual_generate_tts_corpus --out DIR --config config.toml
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from jarvis.audio.tts_silero import SileroEngine
from jarvis.core.config import SileroTtsSettings, VadSettings, load_settings
from manual.personal_proxy.audio import (
    ManifestEntry,
    sha256_hex,
    wav_duration_seconds,
    wav_path,
    write_manifest,
)
from manual.personal_proxy.corpus_v2 import (
    OWNER_VOICE,
    VOICES,
    corpus_v2_fingerprint,
    corpus_v2_problems,
    utterances_of_voice,
)
from manual.personal_proxy.recorder import load_entries
from manual.personal_proxy.tts_corpus import to_capture_wav

DEFAULT_OUT = Path("personal_proxy_corpus_v2_wavs")
DEFAULT_CONFIG = Path("config.toml")
TTS_VOICES = tuple(v for v in VOICES if v != OWNER_VOICE)
SYNTHESIS_RATE = 24000


async def synthesize_voice(
    voice: str, out: Path, vad: VadSettings, entries: dict[str, ManifestEntry]
) -> int:
    engine = SileroEngine(SileroTtsSettings(speaker=voice, sample_rate=SYNTHESIS_RATE))
    made = 0
    for utterance in utterances_of_voice(voice):
        raw = await engine.synthesize(utterance.text)
        wav = to_capture_wav(raw, vad)
        wav_path(out, utterance.utterance_id).write_bytes(wav)
        entries[utterance.utterance_id] = ManifestEntry(
            utterance.utterance_id, sha256_hex(wav), len(wav), wav_duration_seconds(wav)
        )
        made += 1
        seconds = entries[utterance.utterance_id].duration_seconds
        print(f"{utterance.utterance_id}: {seconds:.1f} s")
    return made


async def run(args: argparse.Namespace) -> int:
    vad = load_settings(args.config).vad
    args.out.mkdir(parents=True, exist_ok=True)
    fingerprint = corpus_v2_fingerprint()
    entries = load_entries(args.out, fingerprint)
    total = 0
    for voice in TTS_VOICES:
        total += await synthesize_voice(voice, args.out, vad, entries)
    write_manifest(args.out, list(entries.values()), fingerprint)
    print(f"Wrote {total} recordings to {args.out}")
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    problems = corpus_v2_problems()
    if problems:
        print("The corpus is inconsistent:\n  " + "\n  ".join(problems))
        return 2
    return asyncio.run(run(parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
