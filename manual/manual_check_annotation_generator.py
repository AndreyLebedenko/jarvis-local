#!/usr/bin/env python3
"""Manual handoff for task-v1.8.0-22: live annotation generation against Ollama.

Not an automated test - it needs the live local Ollama endpoint and a built
history corpus, both environment-dependent per CLAUDE.md's testing protocol, so
it is run by hand.

It reads a bounded event range straight from the history corpus (the same typed
read API the service uses), asks the non-dialog AnnotationGenerationService to
summarize only that cited material, and writes the result to the annotation
overlay store beside the journal - raw JSONL events are never touched. The
stored annotation, its target range, and its model/config metadata are printed
back.

Usage:
  # List sessions and their event ranges:
  python -m manual.manual_check_annotation_generator --list

  # Summarize a whole session (the default when no range is given):
  python -m manual.manual_check_annotation_generator \
      --session 20260801-120000-ab12

  # Generate an annotation for an explicit range within one session:
  python -m manual.manual_check_annotation_generator \
      --session 20260801-120000-ab12 --start 0 --end 5

  # Probe an alternate model-facing framing without editing code:
  python -m manual.manual_check_annotation_generator \
      --session 20260801-120000-ab12 \
      --instruction "Summarize only the cited messages in one sentence."

The corpus must be built (start the app once, or the range read reports the
range as unknown). Re-running appends a new annotation each time.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from jarvis.core.bus import EventBus
from jarvis.core.config import Settings, load_settings
from jarvis.dialog.backend import OllamaBackend
from jarvis.dialog.thinking_mode import ReasoningLevel
from jarvis.journal.annotation import AnnotationOverlayRepository, AnnotationTarget
from jarvis.journal.annotation_generator import (
    AnnotationGenerationService,
    OllamaAnnotationBackend,
)
from jarvis.journal.corpus import HistoryCorpusRepository
from jarvis.journal.lifecycle import JournalStoreEventReferenceResolver
from jarvis.journal.store import JournalStore


def _print_sessions(store: JournalStore) -> None:
    summaries = store.list_sessions()
    if not summaries:
        print("No sessions found in the journal.")
        return
    print(f"{len(summaries)} session(s):")
    for summary in summaries:
        records = store.read_session(summary.session_id).records
        last = len(records) - 1
        print(f"  {summary.session_id}: events 0..{last} ({len(records)} total)")


def _target_label(target: AnnotationTarget) -> str:
    if target.is_whole_session:
        return f"{target.session_id} (whole session)"
    return f"{target.session_id} #{target.start_position}-{target.end_position}"


async def _generate(
    settings: Settings,
    store: JournalStore,
    backend: OllamaBackend,
    target: AnnotationTarget,
    instruction: str | None,
) -> None:
    # Build the service from the loaded [history.annotation] config, the same
    # way build_app() does, so this probe exercises the production limits,
    # reasoning, and instruction rather than library defaults. --instruction
    # still overrides.
    annotation_settings = settings.history.annotation
    kwargs: dict[str, object] = {
        "reasoning": ReasoningLevel(annotation_settings.reasoning),
        "max_concurrency": annotation_settings.max_concurrency,
        "max_source_events": annotation_settings.max_source_events,
        "max_source_chars": annotation_settings.max_source_chars,
        "max_annotation_chars": annotation_settings.max_annotation_chars,
    }
    effective_instruction = instruction or (
        annotation_settings.instruction
        if annotation_settings.instruction.strip()
        else None
    )
    if effective_instruction is not None:
        kwargs["instruction"] = effective_instruction

    corpus = HistoryCorpusRepository(store, store.root)
    overlays = AnnotationOverlayRepository(
        store.root, JournalStoreEventReferenceResolver(store)
    )
    service = AnnotationGenerationService(
        corpus, OllamaAnnotationBackend(backend), overlays, **kwargs
    )
    print(
        f"Config: reasoning={annotation_settings.reasoning}, "
        f"max_source_events={annotation_settings.max_source_events}, "
        f"max_source_chars={annotation_settings.max_source_chars}, "
        f"max_annotation_chars={annotation_settings.max_annotation_chars}"
    )
    if instruction is not None:
        print(f"Instruction override: {instruction}")
    print(f"Generating annotation for {_target_label(target)} ...")
    result = await service.generate_annotation(target)
    print(f"Outcome: {result.outcome.value}")
    if result.metadata is not None:
        print(f"Model:   {result.metadata.model}")
        print(f"Reason:  {result.metadata.reasoning}")
        print(f"Options: {result.metadata.options}")
    print(f"Sources: {len(result.source_references)} event(s)")
    if result.detail:
        print(f"Detail:  {result.detail}")
    if result.annotation is not None:
        print("\n--- annotation ---")
        print(result.annotation)
        print("--- end ---")

    if result.annotation_id is not None:
        stored = overlays.read_annotation(result.annotation_id).annotation
        if stored is not None:
            print(
                f"\nOverlay read-back: id={stored.annotation_id}, "
                f"target={_target_label(stored.target)}, "
                f"author={stored.author}, source={stored.source.value}"
            )


async def run(args: argparse.Namespace) -> None:
    settings: Settings = load_settings()
    store = JournalStore(Path(settings.journal.root))

    if args.list:
        _print_sessions(store)
        return

    if not args.session:
        print("Provide --session (with optional --start/--end), or use --list.")
        return
    if (args.start is None) != (args.end is None):
        print(
            "Provide both --start and --end for a range, or neither for the "
            "whole session."
        )
        return

    if not settings.history.annotation.enabled:
        print(
            "[history.annotation].enabled is false; generation is disabled in "
            "config. Enable it to run this probe against the production setup."
        )
        return

    # No --start/--end means the whole session (the default), stored as a
    # whole-session annotation rather than a frozen range.
    target = (
        AnnotationTarget(args.session)
        if args.start is None
        else AnnotationTarget(args.session, args.start, args.end)
    )
    bus = EventBus()
    backend = OllamaBackend(bus=bus, settings=settings.backend)
    await _generate(settings, store, backend, target, args.instruction)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true", help="list sessions and ranges")
    parser.add_argument("--session", help="session id to summarize")
    parser.add_argument(
        "--start",
        type=int,
        help="start event position (inclusive); omit for the whole session",
    )
    parser.add_argument(
        "--end",
        type=int,
        help="end event position (inclusive); omit for the whole session",
    )
    parser.add_argument(
        "--instruction",
        help="override the model-facing annotation instruction (framing probe)",
    )
    asyncio.run(run(parser.parse_args()))
