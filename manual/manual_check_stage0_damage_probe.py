#!/usr/bin/env python3
"""Human-run stage-0 damage/inertness probe (card task-v1.9.2-9).

Local-only: reads the Journal, samples completed text turns by the frozen
rule, dispatches one revision call per pre-marked-correct text-mode turn to
the configured local Ollama endpoint, and persists raw artifacts plus a
scoring template. Talks to the live local endpoint, so the human runs it;
no cloud, no runtime change. See
tasks/task-v1.9.2-9-stage0-damage-and-inertness-probe.md
and tasks/v1.9.2-stage0-stop-rule.md.

Usage:
  # Sample and print the selection (no model calls):
  python -m manual.manual_check_stage0_damage_probe sample

  # Dispatch revisions for the turns pre-marked correct with mode text
  # (reads pre-marks from the scoring sheet CSV; never resamples):
  python -m manual.manual_check_stage0_damage_probe run

  # Repair a damaged scoring sheet without losing filled columns:
  python -m manual.manual_check_stage0_damage_probe template

  # After an interrupted run: resolve one blocking turn at a time
  # (completed <turn_id> / failed <turn_id> / reset <turn_id>):
  python -m manual.manual_check_stage0_damage_probe resume completed <turn_id>
  python -m manual.manual_check_stage0_damage_probe resume failed <turn_id>
  python -m manual.manual_check_stage0_damage_probe resume reset <turn_id>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx

from jarvis.core.bus import EventBus
from jarvis.core.config import load_settings
from jarvis.dialog.backend import OllamaBackend
from jarvis.dialog.thinking_mode import ReasoningLevel
from jarvis.journal.store import JournalStore
from jarvis.memory.files import MemoryFileLoader, build_memory_file_specs
from manual.stage0_probe import (
    PROTOCOL_CARD,
    RAW_OUTPUT_ROOT,
    RUN_ID,
    SAMPLE_SIZE,
    SEED,
    DispatchLedger,
    EligibleTurn,
    build_revision_messages,
    build_scoring_template,
    eligible_completed_turns,
    load_frozen_selection,
    merge_scoring_template,
    partition_pre_marked,
    persist_run_artifacts,
    read_pre_marked_sheet,
    select_sample,
    validate_endpoint,
    write_scoring_sheet,
)

OUT_DIR = RAW_OUTPUT_ROOT / RUN_ID
LEDGER_PATH = OUT_DIR / "ledger.jsonl"
SCORING_SHEET = OUT_DIR / "scoring_sheet.csv"
_SELECTION_FILE = OUT_DIR / "selection.json"


def _load_settings():
    settings = load_settings()
    validate_endpoint(settings.backend.endpoint, settings.backend.model)
    return settings


def _effective_system_prompt(settings) -> str:
    """The same system prompt a live turn gets (app.py's provider).

    Production composes [prompts].system with the curated memory files
    (self.md, memory.md) via MemoryFileLoader, so a draft written under
    that prompt can rely on remembered facts. The reviser must see the
    same blocks, or it "fixes" memory-grounded claims it cannot verify -
    a bench artifact recorded as damage. Only compose_system_prompt is
    applied, not _compose_effective_system_prompt /
    _compose_response_mode_contract: the probe dispatches with reasoning
    OFF and revises text-mode turns only, and app.py's tables select no
    section for either (no OFF key in _REASONING_PROMPT_FIELD_BY_LEVEL,
    no TEXT key in _RESPONSE_MODE_PROMPT_FIELD_BY_MODE), so both layers
    return the prompt unchanged for exactly this configuration.
    """
    loader = MemoryFileLoader(build_memory_file_specs(settings.memory))
    return loader.compose_system_prompt(settings.prompts.system, include_memory=True)


def _read_frozen_turns() -> list[EligibleTurn]:
    """The frozen sample from disk; run and template never resample.

    Resampling between pre-marking and dispatch would shift the window and
    send revisions to turns the owner never marked.
    """
    if not _SELECTION_FILE.exists():
        raise SystemExit(f"selection not found: {_SELECTION_FILE}. Run 'sample' first.")
    return load_frozen_selection(OUT_DIR)


def _sample_turns(store: JournalStore) -> tuple[list[EligibleTurn], int, int]:
    if _SELECTION_FILE.exists():
        raise SystemExit(
            f"selection already exists: {_SELECTION_FILE}. Sampling is once "
            "per run-id; delete the run directory deliberately to resample, "
            "or use 'template' to rebuild the scoring sheet without losing "
            "the filled columns."
        )
    sessions = []
    for summary in store.list_sessions():
        pairs = eligible_completed_turns(store.read_session(summary.session_id).records)
        sessions.append((summary.session_id, pairs))
    selected, ineligible, pool_size, out_of_window = select_sample(sessions)
    persist_run_artifacts(
        OUT_DIR,
        turns=selected,
        ineligible=ineligible,
        scoring_rows=build_scoring_template(selected),
        selected_count=len(selected),
        pool_size=pool_size,
        out_of_window=out_of_window,
    )
    return selected, pool_size, out_of_window


def _read_sheet_rows() -> dict[str, dict[str, str]]:
    if not SCORING_SHEET.exists():
        raise SystemExit(
            f"scoring sheet not found: {SCORING_SHEET}. Run 'sample', then "
            "pre-mark the pre_mark and mode columns by hand."
        )
    return read_pre_marked_sheet(SCORING_SHEET)


def _fail_on_unresolved(unresolved: list[tuple[str, str]]) -> None:
    lines = ", ".join(f"{turn_id} ({reason})" for turn_id, reason in unresolved)
    raise SystemExit(
        "pre-marking is not complete; nothing was dispatched: "
        f"{lines}. Finish the mode and pre_mark columns, then re-run."
    )


async def _dispatch_revision(
    client: httpx.AsyncClient,
    backend: OllamaBackend,
    turn_id: str,
    messages: list[dict[str, str]],
    seed: int,
    out_dir: Path,
    ledger: DispatchLedger,
) -> None:
    payload = backend.build_payload(messages, None, reasoning_level=ReasoningLevel.OFF)
    options = dict(payload.get("options") or {})
    options["seed"] = seed
    payload["options"] = options
    artifact_name = f"revision-{turn_id.replace('#', '__')}.json"
    ledger.record_dispatched(turn_id)
    chunks: list[dict[str, object]] = []
    error: str | None = None
    started = time.perf_counter()
    try:
        async with client.stream("POST", "/api/chat", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.strip():
                    chunks.append(json.loads(line))
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        error = str(exc)
    except asyncio.CancelledError:
        wall_seconds = time.perf_counter() - started
        _write_revision_artifact(
            out_dir,
            artifact_name,
            turn_id,
            seed,
            wall_seconds,
            chunks,
            "cancelled",
            error="interrupted before completion",
        )
        ledger.record_interrupted(turn_id)
        raise
    wall_seconds = time.perf_counter() - started
    content = "".join(
        chunk.get("message", {}).get("content", "")
        for chunk in chunks
        if isinstance(chunk.get("message"), dict)
    )
    done_chunk = next((chunk for chunk in chunks if chunk.get("done")), None)
    if error is not None or done_chunk is None:
        _write_revision_artifact(
            out_dir,
            artifact_name,
            turn_id,
            seed,
            wall_seconds,
            chunks,
            "failed",
            error=error or "stream ended without done:true",
        )
        ledger.record_failed(turn_id, error or "stream ended without done:true")
        print(f"FAILED  {turn_id}: {error or 'stream ended without done:true'}")
    else:
        _write_revision_artifact(
            out_dir,
            artifact_name,
            turn_id,
            seed,
            wall_seconds,
            chunks,
            "completed",
            revision_text=content,
        )
        ledger.record_completed(turn_id, artifact_name)
        print(f"OK      {turn_id} ({wall_seconds:.1f}s, {len(content)} chars)")


def _write_revision_artifact(
    out_dir: Path,
    artifact_name: str,
    turn_id: str,
    seed: int,
    wall_seconds: float,
    chunks: list[dict[str, object]],
    status: str,
    *,
    revision_text: str = "",
    error: str | None = None,
) -> None:
    done_chunk = next((chunk for chunk in chunks if chunk.get("done")), None)
    artifact = {
        "turn_id": turn_id,
        "seed": seed,
        "wall_seconds": round(wall_seconds, 3),
        "eval_count": done_chunk.get("eval_count") if done_chunk else None,
        "revision_text": revision_text,
        "done": done_chunk is not None,
        "status": status,
        "error": error,
        "protocol_card": PROTOCOL_CARD,
    }
    (out_dir / artifact_name).write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _interrupt_guard(ledger: DispatchLedger) -> None:
    """Print the ledger's state after Ctrl+C."""
    unresolved = sorted(
        turn_id
        for turn_id, record in ledger.records.items()
        if str(record.get("status")) in DispatchLedger.BLOCKING_STATUSES
    )
    if unresolved:
        print(
            "Interrupted. Unresolved ledger records (dispatched/interrupted): "
            f"{', '.join(unresolved)}. Decide each with the resume command, "
            "then re-run dispatch."
        )


async def _run_dispatch(pre_marked: list[EligibleTurn]) -> None:
    settings = _load_settings()
    system_prompt = _effective_system_prompt(settings)
    ledger = DispatchLedger(LEDGER_PATH)
    planned = [turn.turn_id for turn in pre_marked]
    unresolved = ledger.blocking_turn_ids(planned)
    if unresolved:
        raise SystemExit(
            "ledger has unresolved dispatched/interrupted records: "
            f"{', '.join(unresolved)}. Decide each with the resume command "
            "(completed / failed / reset <turn_id>), then re-run."
        )
    pending = ledger.pending_turn_ids(planned)
    if not pending:
        print("Nothing pending; all planned turns already have terminal status.")
        return
    turns_by_id = {turn.turn_id: turn for turn in pre_marked}
    timeout = httpx.Timeout(10.0, read=settings.backend.read_timeout_seconds)
    async with httpx.AsyncClient(
        base_url=settings.backend.endpoint, timeout=timeout
    ) as client:
        backend = OllamaBackend(EventBus(), settings.backend, client=client)
        try:
            for turn_id in pending:
                await _dispatch_revision(
                    client,
                    backend,
                    turn_id,
                    build_revision_messages(
                        turns_by_id[turn_id], system_prompt=system_prompt
                    ),
                    SEED,
                    OUT_DIR,
                    ledger,
                )
        except BaseException:
            # Ctrl+C arrives here both as KeyboardInterrupt and as
            # CancelledError propagating out of the in-flight stream
            # (asyncio.run on SIGINT). CancelledError is caught in
            # _dispatch_revision, which marks the in-flight turn
            # interrupted; a KeyboardInterrupt arriving outside the
            # stream leaves the in-flight record dispatched. Both
            # statuses are blocking, so either way the next run stops
            # for the owner's explicit resume decision - only the hint
            # is printed here.
            _interrupt_guard(ledger)
            raise


def _resume(ledger: DispatchLedger, action: str, turn_id: str) -> None:
    record = ledger.records.get(turn_id)
    if record is None:
        raise SystemExit(f"no ledger record for {turn_id}")
    status = str(record.get("status"))
    if status in DispatchLedger.TERMINAL_STATUSES:
        print(f"{turn_id} already has terminal status {status}; nothing to do.")
        return
    if status not in DispatchLedger.BLOCKING_STATUSES:
        raise SystemExit(
            f"{turn_id} has status {status}; only dispatched/interrupted "
            "records can be resolved."
        )
    if action == "reset":
        ledger.record_reset(turn_id)
        print(f"{turn_id} reset to pending; it will be dispatched on the next run.")
        return
    artifact_name = f"revision-{turn_id.replace('#', '__')}.json"
    if action == "completed":
        ledger.record_completed(turn_id, artifact_name)
        print(
            f"{turn_id} recorded completed against {artifact_name}; verify the "
            "artifact holds the finished response before scoring it."
        )
    else:
        ledger.record_failed(turn_id, "resolved by the owner after an interruption")
        print(f"{turn_id} recorded failed; it will not be dispatched again.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "sample",
        help="build the selection, scoring sheet, and packets (no model calls)",
    )
    subparsers.add_parser(
        "run",
        help="dispatch pre-marked-correct text-mode revisions from the frozen "
        "selection (never resamples)",
    )
    subparsers.add_parser(
        "template",
        help="rebuild scoring-sheet rows from the frozen selection, keeping "
        "every filled column",
    )
    resume = subparsers.add_parser(
        "resume",
        help="resolve one dispatched/interrupted ledger record after an "
        "interrupted run",
    )
    resume.add_argument(
        "action",
        choices=("completed", "failed", "reset"),
        help="completed/failed record the owner's outcome; reset queues re-dispatch",
    )
    resume.add_argument("turn_id", help="turn id as printed by the run command")
    args = parser.parse_args(argv)
    if args.command == "run":
        turns = _read_frozen_turns()
        partition = partition_pre_marked(turns, _read_sheet_rows())
        print(
            f"Pre-marked: {len(partition.to_dispatch)} correct/text to dispatch, "
            f"{len(partition.not_correct)} not_correct, "
            f"{len(partition.mode_excluded)} mode-excluded "
            f"({', '.join(f'{t}: {m}' for t, m in partition.mode_excluded) or '-'}), "
            f"{len(partition.unresolved)} unresolved."
        )
        if partition.unresolved:
            _fail_on_unresolved(partition.unresolved)
        if not partition.to_dispatch:
            print("Nothing to dispatch.")
            return
        asyncio.run(_run_dispatch(partition.to_dispatch))
        return
    if args.command == "resume":
        _resume(DispatchLedger(LEDGER_PATH), args.action, args.turn_id)
        return
    if args.command == "template":
        turns = _read_frozen_turns()
        existing = read_pre_marked_sheet(SCORING_SHEET)
        rows = merge_scoring_template(turns, existing)
        write_scoring_sheet(SCORING_SHEET, rows)
        print(f"Template rows: {len(rows)}; sheet: {SCORING_SHEET}")
        return
    settings = _load_settings()
    store = JournalStore(Path(settings.journal.root))
    turns, pool_size, out_of_window = _sample_turns(store)
    print(
        f"Pool: {pool_size} eligible turns in the frozen period "
        f"({out_of_window} journal items outside the window); selected "
        f"{len(turns)} (target {SAMPLE_SIZE}). Scoring sheet: {SCORING_SHEET}"
    )
    if len(turns) < SAMPLE_SIZE:
        print(
            "Shortfall: fewer eligible turns than the frozen sample size; "
            "the selection record carries N and the exclusions."
        )
    print(f"Selection record: {_SELECTION_FILE}")
    print(
        "Next: pre-mark the pre_mark column (correct / not_correct) and "
        "confirm the mode column (text / voice / text_voice)."
    )


if __name__ == "__main__":
    main()
