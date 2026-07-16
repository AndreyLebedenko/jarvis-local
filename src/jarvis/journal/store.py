from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jarvis.journal.events import JournalEvent, parse_journal_timestamp

_EVENTS_FILE_NAME = "events.jsonl"


@dataclass(frozen=True)
class JournalReplay:
    events: list[JournalEvent]
    corrupt_lines: int


@dataclass(frozen=True)
class JournalSessionSummary:
    session_id: str
    first_timestamp: str
    last_timestamp: str


class JournalStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def append(self, event: JournalEvent) -> None:
        session_dir = self._root / event.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        with (session_dir / _EVENTS_FILE_NAME).open("a", encoding="utf-8") as file:
            file.write(event.to_json_line())
            file.flush()

    def read_session(self, session_id: str) -> JournalReplay:
        events_file = self._root / session_id / _EVENTS_FILE_NAME
        if not events_file.exists():
            return JournalReplay(events=[], corrupt_lines=0)

        events: list[JournalEvent] = []
        corrupt_lines = 0
        with events_file.open("r", encoding="utf-8") as file:
            for line in file:
                try:
                    events.append(JournalEvent.from_json_line(line))
                except (ValueError, TypeError):
                    corrupt_lines += 1
        return JournalReplay(events=events, corrupt_lines=corrupt_lines)

    def list_sessions(self) -> list[JournalSessionSummary]:
        summaries = []
        if not self._root.exists():
            return summaries

        for session_dir in self._root.iterdir():
            if not session_dir.is_dir():
                continue
            replay = self.read_session(session_dir.name)
            if not replay.events:
                continue
            summaries.append(
                JournalSessionSummary(
                    session_id=session_dir.name,
                    first_timestamp=replay.events[0].timestamp,
                    last_timestamp=replay.events[-1].timestamp,
                )
            )
        return sorted(
            summaries,
            key=lambda summary: parse_journal_timestamp(summary.first_timestamp),
        )
