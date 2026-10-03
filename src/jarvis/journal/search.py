from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jarvis.journal.corpus import (
    HISTORY_SEARCH_MAX_RESULTS,
    EffectiveTranscriptResolver,
    HistoryCorpusEvent,
    HistoryCorpusRepository,
    HistoryLocatorRequest,
    HistorySearchOrder,
    HistorySearchRequest,
    HistorySearchStatus,
)
from jarvis.journal.events import JournalEventRef
from jarvis.journal.external_canvas import caller_name_from_metadata
from jarvis.journal.provenance import provenance_descriptor_from_corpus_event
from jarvis.journal.store import JournalStore

_UNKNOWN_EVENT_LABELS = ("", None)


@dataclass(frozen=True)
class JournalSearchHit:
    # ``kind`` separates the two search surfaces the Journal UI renders:
    # a canonical FTS hit and a task-4 locator hit (a phrase the user only
    # heard, matched against a mode-3 spoken derivative). A canonical hit
    # needs no canonical text - the event row already renders it; a locator
    # hit carries the hydrated canonical text plus the heard-phrase snippet.
    # ``caller_name`` is non-None only for an external answer.
    session_id: str
    timestamp: str
    event_position: int
    snippet: str
    kind: str = "canonical"
    canonical_text: str | None = None
    source: str = ""
    caller_name: str | None = None


def _event_labels(event: HistoryCorpusEvent) -> tuple[str, str | None]:
    """Externality is read from the provenance descriptor, the one way this
    codebase expresses it - not from a second source comparison here."""
    descriptor = provenance_descriptor_from_corpus_event(event)
    caller_name = (
        caller_name_from_metadata(event.metadata)
        if descriptor.source_kind.is_external
        else None
    )
    return event.source, caller_name


class JournalSearchIndex:
    def __init__(
        self,
        store: JournalStore,
        root: Path,
        transcripts: EffectiveTranscriptResolver | None = None,
    ) -> None:
        self._repository = HistoryCorpusRepository(store, root, transcripts)

    @property
    def repository(self) -> HistoryCorpusRepository:
        return self._repository

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
                roles=("user", "assistant"),
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
        labels = self._labels_of(tuple(hit.reference for hit in result.hits))
        found: list[JournalSearchHit] = []
        for hit in result.hits:
            source, caller_name = labels.get(hit.reference, _UNKNOWN_EVENT_LABELS)
            found.append(
                JournalSearchHit(
                    session_id=hit.reference.session_id,
                    timestamp=hit.timestamp,
                    event_position=hit.reference.event_position,
                    snippet=hit.snippet,
                    source=source,
                    caller_name=caller_name,
                )
            )
        return found

    def _labels_of(
        self, references: tuple[JournalEventRef, ...]
    ) -> dict[JournalEventRef, tuple[str, str | None]]:
        """One batched read: the caller lives in the event metadata, which the
        FTS rows do not carry. A reference the projection no longer holds is
        absent from the result - its hit keeps an empty source and no caller
        instead of failing the whole search."""
        read = self._repository.read_events(references)
        return {event.reference: _event_labels(event) for event in read.events}

    def search_locator(
        self,
        query: str,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 50,
    ) -> list[JournalSearchHit]:
        """Heard-phrase locator search (story-v1.9.1 task 4).

        Queries the task-3 derivative FTS only; each hit points at the
        owning assistant event with its canonical text hydrated. Locator
        matches never mix into `search` results - the Journal UI renders
        them as a distinctly labeled group.
        """
        if limit < 1:
            raise ValueError("limit must be positive")
        if limit > HISTORY_SEARCH_MAX_RESULTS:
            raise ValueError(f"limit must be at most {HISTORY_SEARCH_MAX_RESULTS}")

        result = self._repository.search_locator(
            HistoryLocatorRequest(
                query=query,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
            )
        )
        if result.status is HistorySearchStatus.UNAVAILABLE:
            return []
        if result.status is not HistorySearchStatus.ACCEPTED:
            raise ValueError(
                f"unsupported journal locator search request: {result.status.value}"
            )
        labels = self._labels_of(tuple(hit.reference for hit in result.hits))
        found: list[JournalSearchHit] = []
        for hit in result.hits:
            source, caller_name = labels.get(hit.reference, _UNKNOWN_EVENT_LABELS)
            found.append(
                JournalSearchHit(
                    session_id=hit.reference.session_id,
                    timestamp=hit.timestamp,
                    event_position=hit.reference.event_position,
                    snippet=hit.snippet,
                    kind="locator",
                    canonical_text=hit.canonical_text,
                    source=source,
                    caller_name=caller_name,
                )
            )
        return found
