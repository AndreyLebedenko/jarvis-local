#!/usr/bin/env python3
"""Manual handoff for tasks/done/task-config-generation-profiles.md.

Reads the debug transcript written by `python -m jarvis --status-console
--debug` and prints, for every model exchange at or after --since, the
reasoning value sent (`think`), the generation options sent, and the start
of the first message - enough to tell the request kinds apart and to see
which options each one carried. No live Ollama access; it only reads the
file the run already wrote.

Example:

  python -m manual.manual_check_generation_profiles --since 2026-09-26T21:05:00
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from jarvis.core.config import load_settings
from jarvis.core.debug_transcript import TRANSCRIPT_FILE_NAME

_PREVIEW_CHARS = 60


@dataclass(frozen=True)
class ExchangeSummary:
    timestamp: str
    think: object
    options: dict[str, object]
    first_message: str


def summarize_exchanges(lines: Iterable[str], since: str) -> list[ExchangeSummary]:
    summaries = []
    for line in lines:
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("kind") != "exchange" or record["timestamp"] < since:
            continue
        request = record["request"]
        messages = request.get("messages") or [{}]
        first = messages[0]
        preview = f"{first.get('role', '?')}: {first.get('content', '')}"
        summaries.append(
            ExchangeSummary(
                timestamp=record["timestamp"],
                think=request.get("think"),
                options=request.get("options") or {},
                first_message=" ".join(preview.split())[:_PREVIEW_CHARS],
            )
        )
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print what each model exchange in the debug transcript sent."
    )
    parser.add_argument(
        "--since",
        required=True,
        help="local ISO timestamp, e.g. 2026-09-26T21:05:00; earlier are skipped",
    )
    args = parser.parse_args()
    path = Path(load_settings().logging.directory) / TRANSCRIPT_FILE_NAME
    with path.open(encoding="utf-8") as transcript:
        summaries = summarize_exchanges(transcript, args.since)
    print(f"{len(summaries)} exchange(s) in {path} since {args.since}")
    for summary in summaries:
        print(f"\n{summary.timestamp}  think={summary.think!r}")
        print(f"  first message: {summary.first_message}")
        print(f"  options: {json.dumps(summary.options, sort_keys=True)}")


if __name__ == "__main__":
    main()
