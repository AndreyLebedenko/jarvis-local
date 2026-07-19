from __future__ import annotations

import shutil
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


@dataclass(frozen=True)
class JournalSessionUsage:
    session_id: str
    bytes: int


@dataclass(frozen=True)
class JournalUsage:
    total_bytes: int
    sessions: list[JournalSessionUsage]


class JournalStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def append(self, event: JournalEvent) -> None:
        session_dir = self._root / event.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        with (session_dir / _EVENTS_FILE_NAME).open("a", encoding="utf-8") as file:
            file.write(event.to_json_line())
            file.flush()

    def write_media(self, session_id: str, name: str, contents: bytes) -> None:
        media_path = self._root / session_id / name
        media_path.parent.mkdir(parents=True, exist_ok=True)
        media_path.write_bytes(contents)

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

    def usage(self) -> JournalUsage:
        summaries = self.list_sessions()
        sessions = [
            JournalSessionUsage(
                session_id=summary.session_id,
                bytes=self._directory_size_bytes(self._session_dir(summary.session_id)),
            )
            for summary in summaries
        ]
        return JournalUsage(
            total_bytes=sum(session.bytes for session in sessions),
            sessions=sessions,
        )

    def delete_session(self, session_id: str) -> None:
        session_dir = self._existing_session_dir(session_id)
        shutil.rmtree(session_dir)

    def _existing_session_dir(self, session_id: str) -> Path:
        real_session_ids = {summary.session_id for summary in self.list_sessions()}
        if session_id not in real_session_ids:
            raise KeyError(session_id)
        return self._session_dir(session_id)

    def _session_dir(self, session_id: str) -> Path:
        root = self._root.resolve()
        candidate = (root / session_id).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            raise KeyError(session_id) from None
        if not candidate.is_dir():
            raise KeyError(session_id)
        return candidate

    @staticmethod
    def _directory_size_bytes(session_dir: Path) -> int:
        total = 0
        for path in session_dir.rglob("*"):
            if path.is_file():
                total += path.stat().st_size
        return total
