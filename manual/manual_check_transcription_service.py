#!/usr/bin/env python3
"""Manual handoff for task-v1.8.0-19: live transcription against real Ollama.

Not an automated test - it needs the live local Ollama endpoint and real
recorded voice audio in the journal, both hardware/environment-dependent per
CLAUDE.md's testing protocol, so it is run by hand.

It reads a recorded voice event's audio straight from the journal, runs the
non-dialog TranscriptionService through the verified `images` transport, and
writes the result to the transcript overlay store beside the journal - the raw
JSONL event is never touched. The transcript is then read back and printed.

Usage:
  # List voice events that have audio and can be transcribed:
  python -m manual.manual_check_transcription_service --list

  # Transcribe one event by reference:
  python -m manual.manual_check_transcription_service \
      --session 20260801-120000-ab12 --position 0

  # Transcribe the most recent transcribable voice event:
  python -m manual.manual_check_transcription_service --latest

  # Probe an alternate model-facing framing without editing code:
  python -m manual.manual_check_transcription_service --latest \
      --instruction "Transcribe this recording verbatim, word for word."

Both --session/--position and --latest write a GENERATED transcript overlay.
Re-running overwrites it (idempotent, retryable). `--instruction` overrides the
default framing - useful because `gemma4:12b-it-qat` will refuse ("provide the
audio file") for some phrasings even though the audio reaches it, so the exact
instruction wording is a live-tuning knob (see the transcription refusal bug
report).
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from jarvis.core.bus import EventBus
from jarvis.core.config import Settings, load_settings
from jarvis.dialog.backend import OllamaBackend
from jarvis.journal.events import JournalEventRef
from jarvis.journal.lifecycle import JournalStoreEventReferenceResolver
from jarvis.journal.store import JournalStore
from jarvis.journal.transcript import TranscriptOverlayRepository
from jarvis.journal.transcription import (
    JournalStoreTranscriptionSource,
    OllamaTranscriptionBackend,
    TranscriptionService,
    select_audio_media,
)


def _candidates(
    store: JournalStore,
) -> list[tuple[JournalEventRef, str, tuple[str, ...]]]:
    found: list[tuple[JournalEventRef, str, tuple[str, ...]]] = []
    for summary in store.list_sessions():
        for record in store.read_session(summary.session_id).records:
            audio = select_audio_media(record.event)
            if audio:
                found.append((record.reference, record.event.timestamp, audio))
    return found


def _print_candidates(store: JournalStore) -> None:
    candidates = _candidates(store)
    if not candidates:
        print("No voice events with audio media found in the journal.")
        return
    print(f"{len(candidates)} transcribable voice event(s):")
    for reference, timestamp, audio in candidates:
        print(
            f"  {reference.session_id} #{reference.event_position} "
            f"@ {timestamp} -> {', '.join(audio)}"
        )


async def _transcribe(
    store: JournalStore,
    backend: OllamaBackend,
    reference: JournalEventRef,
    instruction: str | None,
) -> None:
    overlays = TranscriptOverlayRepository(
        store.root, JournalStoreEventReferenceResolver(store)
    )
    service = TranscriptionService(
        JournalStoreTranscriptionSource(store),
        OllamaTranscriptionBackend(backend),
        overlays,
        **({} if instruction is None else {"instruction": instruction}),
    )
    if instruction is not None:
        print(f"Instruction override: {instruction}")
    print(f"Transcribing {reference.session_id} #{reference.event_position} ...")
    result = await service.transcribe_event(reference)
    print(f"Outcome: {result.outcome.value}")
    if result.metadata is not None:
        print(f"Model:   {result.metadata.model}")
        print(f"Reason:  {result.metadata.reasoning}")
        print(f"Options: {result.metadata.options}")
    print(f"Media:   {', '.join(result.source_media) or '-'}")
    if result.detail:
        print(f"Detail:  {result.detail}")
    if result.transcript is not None:
        print("\n--- transcript ---")
        print(result.transcript)
        print("--- end ---")

    read = overlays.read_transcript(reference)
    print(
        f"\nOverlay read-back: status={read.status.value}"
        + (f", source={read.overlay.source.value}" if read.overlay is not None else "")
    )


async def run(args: argparse.Namespace) -> None:
    settings: Settings = load_settings()
    store = JournalStore(Path(settings.journal.root))

    if args.list:
        _print_candidates(store)
        return

    if args.latest:
        candidates = _candidates(store)
        if not candidates:
            print("No transcribable voice events found.")
            return
        reference = candidates[-1][0]
    else:
        if not args.session or args.position is None:
            print("Provide --session and --position, or use --list / --latest.")
            return
        reference = JournalEventRef(args.session, args.position)

    bus = EventBus()
    backend = OllamaBackend(bus=bus, settings=settings.backend)
    await _transcribe(store, backend, reference, args.instruction)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true", help="list transcribable events")
    parser.add_argument("--latest", action="store_true", help="transcribe the newest")
    parser.add_argument("--session", help="session id of the event to transcribe")
    parser.add_argument(
        "--position", type=int, help="event position within the session"
    )
    parser.add_argument(
        "--instruction",
        help="override the model-facing transcription instruction (framing probe)",
    )
    asyncio.run(run(parser.parse_args()))
