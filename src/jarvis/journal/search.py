from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jarvis.journal.corpus import (
    HISTORY_SEARCH_MAX_RESULTS,
    HistoryCorpusRepository,
    HistorySearchOrder,
    HistorySearchRequest,
    HistorySearchStatus,
)
from jarvis.journal.store import JournalStore


@dataclass(frozen=True)
class JournalSearchHit:
    session_id: str
    timestamp: str
    event_position: int
    snippet: str


class JournalSearchIndex:
    def __init__(self, store: JournalStore, root: Path) -> None:
        self._repository = HistoryCorpusRepository(store, root)

    def rebuild(self) -> None:
        self._repository.rebuild()

    def update_session(self, session_id: str) -> None:
        self._repository.update_session_projection(session_id)

    def delete_session(self, session_id: str) -> None:
        self._repository.delete_session_projection(session_id)

    def search(
        self,
        query: str,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 50,
    ) -> list[JournalSearchHit]:
        if limit < 1:
            raise ValueError("limit must be positive")
        if limit > HISTORY_SEARCH_MAX_RESULTS:
            raise ValueError(f"limit must be at most {HISTORY_SEARCH_MAX_RESULTS}")

        result = self._repository.search(
            HistorySearchRequest(
                query=query,
                date_from=date_from,
                date_to=date_to,
                roles=("assistant",),
                limit=limit,
                order=HistorySearchOrder.CHRONOLOGICAL,
            )
        )
        if result.status is HistorySearchStatus.UNAVAILABLE:
            return []
        if result.status is not HistorySearchStatus.ACCEPTED:
            raise ValueError(
                f"unsupported journal search request: {result.status.value}"
            )
        return [
            JournalSearchHit(
                session_id=hit.reference.session_id,
                timestamp=hit.timestamp,
                event_position=hit.reference.event_position,
                snippet=hit.snippet,
            )
            for hit in result.hits
        ]
