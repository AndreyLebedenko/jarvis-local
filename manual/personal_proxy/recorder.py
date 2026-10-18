"""Take-by-take recording flow of the personal-proxy corpus, without hardware.

The live microphone source and the terminal interaction are injected, so the
flow is tested with fakes. The WAVs it writes are the chunks of the production
VadChunker (voice-activity trimming and short-clip padding included), which is
the whole point of recording through the production capture path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from manual.personal_proxy.audio import (
    MANIFEST_NAME,
    ManifestEntry,
    sha256_hex,
    wav_duration_seconds,
    wav_path,
    write_manifest,
)
from manual.personal_proxy.corpus import CORPUS, Utterance, corpus_fingerprint

TAKE_TIMEOUT_SECONDS = 90.0
TOO_SHORT_RATIO = 0.5
TOO_LONG_RATIO = 2.0


class Choice(StrEnum):
    ACCEPT = "accept"
    REDO = "redo"
    PLAY = "play"
    QUIT = "quit"


class RecordingDirectoryError(RuntimeError):
    pass


class TakeSource(Protocol):
    async def next_take(self, timeout_seconds: float) -> bytes | None:
        """Drops anything captured so far, then returns the next utterance
        chunk, or None if nothing arrived in time."""
        ...


class Interaction(Protocol):
    async def announce(self, index: int, total: int, utterance: Utterance) -> None: ...

    async def wait_ready(self) -> None: ...

    async def review(self, seconds: float, advice: str | None) -> Choice: ...

    def play(self, wav: bytes) -> None: ...

    def info(self, message: str) -> None: ...


@dataclass(frozen=True)
class RecordSummary:
    recorded: int
    skipped: int
    quit_early: bool


def take_advice(seconds: float, utterance: Utterance) -> str | None:
    """A hint when the take looks cut or padded, judged against the reading
    speed the corpus assumes. The VAD cuts a take at a long pause."""
    expected = utterance.estimated_seconds
    if seconds < expected * TOO_SHORT_RATIO:
        return (
            f"only {seconds:.1f} s of about {expected:.1f} s expected; "
            "a long pause may have ended the take early"
        )
    if seconds > expected * TOO_LONG_RATIO:
        return (
            f"{seconds:.1f} s against about {expected:.1f} s expected; "
            "extra speech or noise may have been captured"
        )
    return None


def load_entries(directory: Path) -> dict[str, ManifestEntry]:
    path = directory / MANIFEST_NAME
    if not path.exists():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    if document["corpus_fingerprint"] != corpus_fingerprint():
        raise RecordingDirectoryError(
            f"{directory} holds recordings of a different corpus; use a new directory"
        )
    return {
        uid: ManifestEntry(uid, e["sha256"], e["bytes"], e["duration_seconds"])
        for uid, e in document["entries"].items()
    }


def pending(
    entries: dict[str, ManifestEntry], redo: set[str] | None = None
) -> list[Utterance]:
    redo = redo or set()
    return [
        u for u in CORPUS if u.utterance_id not in entries or u.utterance_id in redo
    ]


async def record_corpus(
    source: TakeSource,
    interaction: Interaction,
    directory: Path,
    *,
    redo: set[str] | None = None,
) -> RecordSummary:
    directory.mkdir(parents=True, exist_ok=True)
    entries = load_entries(directory)
    todo = pending(entries, redo)
    recorded = 0
    for index, utterance in enumerate(todo, start=1):
        wav = await _record_one(source, interaction, index, len(todo), utterance)
        if wav is None:
            return RecordSummary(recorded, len(CORPUS) - len(todo), quit_early=True)
        wav_path(directory, utterance.utterance_id).write_bytes(wav)
        entries[utterance.utterance_id] = ManifestEntry(
            utterance.utterance_id, sha256_hex(wav), len(wav), wav_duration_seconds(wav)
        )
        write_manifest(directory, list(entries.values()))
        recorded += 1
    return RecordSummary(recorded, len(CORPUS) - len(todo), quit_early=False)


async def _record_one(
    source: TakeSource,
    interaction: Interaction,
    index: int,
    total: int,
    utterance: Utterance,
) -> bytes | None:
    await interaction.announce(index, total, utterance)
    while True:
        await interaction.wait_ready()
        wav = await source.next_take(TAKE_TIMEOUT_SECONDS)
        if wav is None:
            interaction.info("Nothing was captured in time; try again.")
            continue
        seconds = wav_duration_seconds(wav)
        advice = take_advice(seconds, utterance)
        while True:
            choice = await interaction.review(seconds, advice)
            if choice is Choice.PLAY:
                interaction.play(wav)
            elif choice is Choice.ACCEPT:
                return wav
            elif choice is Choice.QUIT:
                return None
            else:
                break
