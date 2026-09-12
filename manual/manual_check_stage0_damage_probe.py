#!/usr/bin/env python3
"""Human-run stage-0 damage/inertness probe (card task-v1.9.2-9).

Local-only: reads the Journal, samples completed text turns by the frozen
rule, dispatches one revision call per pre-marked-correct turn to the
configured local Ollama endpoint, and persists raw artifacts plus a scoring
template. Talks to the live local endpoint, so the human runs it; no cloud,
no runtime change. See tasks/task-v1.9.2-9-stage0-damage-and-inertness-probe.md
and tasks/v1.9.2-stage0-stop-rule.md.

Usage:
  # Sample and print the selection (no model calls):
  python -m manual.manual_check_stage0_damage_probe sample

  # Dispatch revisions for the turns pre-marked correct
  # (reads pre-marks from the scoring sheet CSV):
  python -m manual.manual_check_stage0_damage_probe run

  # Rebuild the scoring template after dispatch (does not rescore):
  python -m manual.manual_check_stage0_damage_probe template
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import time
from pathlib import Path

import httpx

from jarvis.core.bus import EventBus
from jarvis.core.config import load_settings
from jarvis.dialog.backend import OllamaBackend
from jarvis.dialog.thinking_mode import ReasoningLevel
from jarvis.journal.store import JournalStore
from manual.stage0_probe import (
    PROTOCOL_CARD,
    RAW_OUTPUT_ROOT,
    RUN_ID,
    SEED,
    DispatchLedger,
    EligibleTurn,
    build_revision_messages,
    build_scoring_template,
    eligible_completed_turns,
    persist_run_artifacts,
    select_sample,
    validate_endpoint,
)

OUT_DIR = RAW_OUTPUT_ROOT / RUN_ID
LEDGER_PATH = OUT_DIR / "ledger.jsonl"
SCORING_SHEET = OUT_DIR / "scoring_sheet.csv"
_PACKETS_FILE = OUT_DIR / "packets.jsonl"

_PRE_MARK_COLUMN = "pre_mark"
_PRE_MARK_CORRECT = "correct"


def _load_settings_and_store():
    settings = load_settings()
    validate_endpoint(settings.backend.endpoint, settings.backend.model)
    store = JournalStore(Path(settings.journal.root))
    return settings, store


def _sample_turns(store: JournalStore) -> tuple[list[EligibleTurn], int]:
    sessions = []
    pool_total = 0
    for summary in store.list_sessions():
        pairs = eligible_completed_turns(store.read_session(summary.session_id).records)
        sessions.append((summary.session_id, pairs))
        pool_total += sum(1 for eligible, _ in pairs if eligible is not None)
    selected, ineligible = select_sample(sessions)
    persist_run_artifacts(
        OUT_DIR,
        turns=selected,
        ineligible=ineligible,
        scoring_rows=build_scoring_template(selected),
        selected_count=len(selected),
    )
    return selected, pool_total


def _read_pre_marked_turns(
    turns: list[EligibleTurn],
) -> tuple[list[EligibleTurn], int]:
    """Turns the human pre-marked correct, read from the scoring sheet.

    The sheet is the single pre-marking record: rows the human marked
    "correct" before any revision existed are the damage denominator; rows
    marked "not_correct" are recorded and excluded.
    """
    if not SCORING_SHEET.exists():
        raise SystemExit(
            f"scoring sheet not found: {SCORING_SHEET}. Run 'sample', then "
            "pre-mark the pre_mark column (correct / not_correct) by hand."
        )
    pre_marks: dict[str, str] = {}
    with SCORING_SHEET.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            turn_id = (row.get("turn_id") or "").strip()
            pre_mark = (row.get(_PRE_MARK_COLUMN) or "").strip().lower()
            if turn_id:
                pre_marks[turn_id] = pre_mark
    selected = []
    not_correct = 0
    for turn in turns:
        pre_mark = pre_marks.get(turn.turn_id, "")
        if pre_mark == _PRE_MARK_CORRECT:
            selected.append(turn)
        else:
            not_correct += 1
    return selected, not_correct


def _load_payload_records() -> list[dict[str, str]]:
    if not _PACKETS_FILE.exists():
        raise SystemExit(f"packets not found: {_PACKETS_FILE}. Run 'sample' first.")
    records = []
    with _PACKETS_FILE.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                records.append(json.loads(line))
    return records


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
    wall_seconds = time.perf_counter() - started
    content = "".join(
        chunk.get("message", {}).get("content", "")
        for chunk in chunks
        if isinstance(chunk.get("message"), dict)
    )
    done_chunk = next((chunk for chunk in chunks if chunk.get("done")), None)
    artifact = {
        "turn_id": turn_id,
        "seed": seed,
        "wall_seconds": round(wall_seconds, 3),
        "eval_count": done_chunk.get("eval_count") if done_chunk else None,
        "revision_text": content,
        "done": done_chunk is not None,
        "error": error,
        "protocol_card": PROTOCOL_CARD,
    }
    (out_dir / artifact_name).write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if error is not None or done_chunk is None:
        ledger.record_failed(turn_id, error or "stream ended without done:true")
        print(f"FAILED  {turn_id}: {error or 'stream ended without done:true'}")
    else:
        ledger.record_completed(turn_id, artifact_name)
        print(f"OK      {turn_id} ({wall_seconds:.1f}s, {len(content)} chars)")


async def _run_dispatch(pre_marked: list[EligibleTurn]) -> None:
    settings, _store = _load_settings_and_store()
    payloads = {record["turn_id"]: record for record in _load_payload_records()}
    ledger = DispatchLedger(LEDGER_PATH)
    pending = ledger.pending_turn_ids([turn.turn_id for turn in pre_marked])
    unresolved = ledger.dispatched_without_terminal_status()
    if unresolved:
        raise SystemExit(
            "ledger has dispatched records without a terminal status: "
            f"{', '.join(unresolved)}. Review the interrupted run; use "
            "explicit resume only after deciding each record's outcome."
        )
    if not pending:
        print("Nothing pending; all planned turns already have terminal status.")
        return
    timeout = httpx.Timeout(10.0, read=settings.backend.read_timeout_seconds)
    async with httpx.AsyncClient(
        base_url=settings.backend.endpoint, timeout=timeout
    ) as client:
        backend = OllamaBackend(EventBus(), settings.backend, client=client)
        for turn_id in pending:
            record = payloads[turn_id]
            await _dispatch_revision(
                client,
                backend,
                turn_id,
                build_revision_messages(_turn_with_texts(record)),
                SEED,
                OUT_DIR,
                ledger,
            )


def _turn_with_texts(record: dict[str, str]) -> EligibleTurn:
    turn_id = record["turn_id"]
    session_id, position = turn_id.rsplit("#", 1)
    return EligibleTurn(
        session_id=session_id,
        user_position=0,
        assistant_position=int(position),
        request_text=record["request"],
        answer_text=record["draft"],
        timestamp="",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("sample", "run", "template"),
        help="sample: build selection+sheet; run: dispatch pre-marked-correct "
        "revisions; template: rebuild the scoring sheet rows",
    )
    args = parser.parse_args()
    if args.command == "run":
        _settings, store = _load_settings_and_store()
        turns, _pool = _sample_turns(store)
        pre_marked, not_correct = _read_pre_marked_turns(turns)
        print(
            f"Pre-marked: {len(pre_marked)} correct, {not_correct} "
            "not_correct/excluded."
        )
        asyncio.run(_run_dispatch(pre_marked))
        return
    _settings, store = _load_settings_and_store()
    turns, pool_total = _sample_turns(store)
    if args.command == "sample":
        print(
            f"Pool: {pool_total} eligible turns; selected {len(turns)} "
            f"(target {30}). Scoring sheet: {SCORING_SHEET}"
        )
        if len(turns) < 30:
            print(
                "Shortfall: fewer eligible turns than the frozen sample size; "
                "report N and exclusions in the sampling record."
            )
        print(f"Selection record: {OUT_DIR / 'selection.json'}")
        print("Next: pre-mark the pre_mark column (correct / not_correct).")
        return
    rows = build_scoring_template(turns)
    print(f"Template rows: {len(rows)}; sheet: {SCORING_SHEET}")


if __name__ == "__main__":
    main()
