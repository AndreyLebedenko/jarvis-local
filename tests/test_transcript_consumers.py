"""Effective-transcript retrieval consumers (task-v1.8.0-20).

A voice turn is recorded with empty text and its audio as media; its words
live only in a derived transcript overlay. These tests prove that the overlay
text becomes the effective text the corpus, lexical, and semantic projections
index and hydrate, that a transcript edit re-projects one event through the
lifecycle without rebuilding an unrelated session, and that the raw event text
stays empty (source-framed as a transcript, never rewritten).
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from jarvis.core.bus import EventBus
from jarvis.core.config import HistorySemanticSettings
from jarvis.journal.corpus import HistoryCorpusRepository, HistorySearchRequest
from jarvis.journal.events import JournalEvent, JournalEventRecord, JournalEventRef
from jarvis.journal.lifecycle import (
    CorpusHistoryProjection,
    HistoryProjectionLifecycle,
    JournalStoreEventReferenceResolver,
    TranscriptHistoryProjection,
    UnavailableSemanticHistoryProjection,
)
from jarvis.journal.retrieval import HistoryRetrievalQuery, HistoryRetrievalService
from jarvis.journal.search import JournalSearchIndex
from jarvis.journal.semantic import SemanticPassageIndex
from jarvis.journal.store import JournalStore
from jarvis.journal.transcript import (
    TranscriptOverlayChanged,
    TranscriptOverlayRepository,
    TranscriptOverlayTextResolver,
    TranscriptSource,
)
from jarvis.journal.transcription import JournalStoreTranscriptionSource

_SESSION = "20260801-120000-ab12"
_TRANSCRIPT = "секретный код альфа"


def _voice_event(position_timestamp: str, media: tuple[str, ...]) -> JournalEvent:
    return JournalEvent(
        session_id=_SESSION,
        timestamp=position_timestamp,
        source="voice",
        role="user",
        text="",
        media=media,
        transcript=None,
    )


def _build(
    tmp_path: Path,
) -> tuple[JournalStore, TranscriptOverlayRepository, HistoryCorpusRepository]:
    store = JournalStore(tmp_path / "journal")
    overlays = TranscriptOverlayRepository(
        tmp_path / "derived", JournalStoreEventReferenceResolver(store)
    )
    resolver = TranscriptOverlayTextResolver(overlays)
    corpus = HistoryCorpusRepository(store, tmp_path / "derived", resolver)
    return store, overlays, corpus


def test_corpus_indexes_and_hydrates_effective_transcript(tmp_path: Path) -> None:
    store, overlays, corpus = _build(tmp_path)
    store.append(_voice_event("2026-08-01T12:00:00+01:00", ("utterance.wav",)))
    reference = JournalEventRef(_SESSION, 0)
    overlays.upsert_transcript(reference, _TRANSCRIPT, TranscriptSource.GENERATED)

    corpus.rebuild()

    read = corpus.read_event(reference)
    assert read.found
    event = read.event
    assert event is not None
    # Raw text stays empty for provenance; the transcript is the effective text.
    assert event.text == ""
    assert event.effective_text == _TRANSCRIPT
    assert event.indexed_text == _TRANSCRIPT
    assert event.text_is_transcript is True

    hits = corpus.search(HistorySearchRequest(query="альфа", roles=("user",))).hits
    assert [hit.reference for hit in hits] == [reference]


def test_corpus_leaves_voice_event_unindexed_without_overlay(tmp_path: Path) -> None:
    store, _overlays, corpus = _build(tmp_path)
    store.append(_voice_event("2026-08-01T12:00:00+01:00", ("utterance.wav",)))

    corpus.rebuild()

    read = corpus.read_event(JournalEventRef(_SESSION, 0))
    assert read.event is not None
    assert read.event.effective_text == ""
    assert read.event.text_is_transcript is False
    result = corpus.search(HistorySearchRequest(query="альфа", roles=("user",)))
    assert result.hits == ()


def test_journal_search_finds_effective_transcript(tmp_path: Path) -> None:
    store, overlays, _corpus = _build(tmp_path)
    store.append(_voice_event("2026-08-01T12:00:00+01:00", ("utterance.wav",)))
    reference = JournalEventRef(_SESSION, 0)
    overlays.upsert_transcript(reference, _TRANSCRIPT, TranscriptSource.GENERATED)
    index = JournalSearchIndex(
        store,
        tmp_path / "derived",
        TranscriptOverlayTextResolver(overlays),
    )

    index.rebuild()

    hits = index.search("альфа")

    assert [(hit.session_id, hit.event_position) for hit in hits] == [
        (_SESSION, reference.event_position)
    ]


def test_semantic_projects_effective_transcript_on_rebuild(tmp_path: Path) -> None:
    store, overlays, corpus = _build(tmp_path)
    store.append(_voice_event("2026-08-01T12:00:00+01:00", ("utterance.wav",)))
    reference = JournalEventRef(_SESSION, 0)
    overlays.upsert_transcript(reference, _TRANSCRIPT, TranscriptSource.GENERATED)
    corpus.rebuild()

    embedder = _FakeEmbedder()
    resolver = TranscriptOverlayTextResolver(overlays)
    index = SemanticPassageIndex(
        corpus,
        tmp_path / "derived",
        _semantic_settings(),
        embedder,
        transcripts=resolver,
    )
    index.rebuild()

    passages = index.list_passages()
    assert [(passage.reference, passage.text) for passage in passages] == [
        (reference, _TRANSCRIPT)
    ]
    assert ("passage: " + _TRANSCRIPT,) in embedder.calls


def test_semantic_record_path_resolves_transcript(tmp_path: Path) -> None:
    store, overlays, corpus = _build(tmp_path)
    voice = _voice_event("2026-08-01T12:00:00+01:00", ("utterance.wav",))
    store.append(voice)
    reference = JournalEventRef(_SESSION, 0)
    corpus.rebuild()

    embedder = _FakeEmbedder()
    resolver = TranscriptOverlayTextResolver(overlays)
    index = SemanticPassageIndex(
        corpus,
        tmp_path / "derived",
        _semantic_settings(),
        embedder,
        transcripts=resolver,
    )
    index.rebuild()
    assert index.list_passages() == ()

    overlays.upsert_transcript(reference, _TRANSCRIPT, TranscriptSource.EDITED)
    index.project_event(JournalEventRecord(reference, voice))

    assert [passage.text for passage in index.list_passages()] == [_TRANSCRIPT]


def test_retrieval_returns_transcript_text_source_framed(tmp_path: Path) -> None:
    store, overlays, corpus = _build(tmp_path)
    store.append(_voice_event("2026-08-01T12:00:00+01:00", ("utterance.wav",)))
    reference = JournalEventRef(_SESSION, 0)
    overlays.upsert_transcript(reference, _TRANSCRIPT, TranscriptSource.GENERATED)
    corpus.rebuild()

    service = HistoryRetrievalService(
        corpus, _UnavailableSemantic(), _semantic_settings()
    )
    result = service.retrieve(HistoryRetrievalQuery(query="альфа"))

    assert [candidate.reference for candidate in result.candidates] == [reference]
    candidate = result.candidates[0]
    assert candidate.text == _TRANSCRIPT
    assert candidate.text_is_transcript is True


@pytest.mark.asyncio
async def test_lifecycle_reprojects_transcript_edit_into_search(
    tmp_path: Path,
) -> None:
    bus = EventBus()
    store, overlays, corpus = _build(tmp_path)
    store.append(_voice_event("2026-08-01T12:00:00+01:00", ("utterance.wav",)))
    reference = JournalEventRef(_SESSION, 0)
    lifecycle = HistoryProjectionLifecycle(
        bus,
        projections=(
            CorpusHistoryProjection(corpus),
            TranscriptHistoryProjection(overlays),
        ),
        semantic_projection=UnavailableSemanticHistoryProjection(),
        transcript_event_source=JournalStoreTranscriptionSource(store),
    )

    await lifecycle.start()
    try:
        # Not searchable before a transcript exists.
        assert corpus.search(HistorySearchRequest("альфа", roles=("user",))).hits == ()

        overlays.upsert_transcript(reference, _TRANSCRIPT, TranscriptSource.EDITED)
        await bus.publish(TranscriptOverlayChanged, TranscriptOverlayChanged(reference))
        await lifecycle.wait_for_idle()

        hits = corpus.search(HistorySearchRequest("альфа", roles=("user",))).hits
        assert [hit.reference for hit in hits] == [reference]
    finally:
        await lifecycle.close()


@pytest.mark.asyncio
async def test_lifecycle_serializes_concurrent_reprojections_for_one_event(
    tmp_path: Path,
) -> None:
    bus = EventBus()
    store, _overlays, _corpus = _build(tmp_path)
    store.append(_voice_event("2026-08-01T12:00:00+01:00", ("utterance.wav",)))
    reference = JournalEventRef(_SESSION, 0)
    projection = _GatedProjection()
    lifecycle = HistoryProjectionLifecycle(
        bus,
        projections=(projection,),
        semantic_projection=UnavailableSemanticHistoryProjection(),
        transcript_event_source=JournalStoreTranscriptionSource(store),
    )

    await lifecycle.start()
    try:
        await bus.publish(TranscriptOverlayChanged, TranscriptOverlayChanged(reference))
        # Wait until the first re-projection is inside project_event and gated.
        while not projection.entered.is_set():
            await asyncio.sleep(0.01)
        # A second change for the same event arrives mid-flight; it must be
        # coalesced into one rerun, never run concurrently with the first.
        await bus.publish(TranscriptOverlayChanged, TranscriptOverlayChanged(reference))
        # Give an un-serialized second run time to enter project_event
        # concurrently: without per-event serialization this window is exactly
        # when max_concurrent would climb to 2.
        await asyncio.sleep(0.05)
        projection.release.set()
        await lifecycle.wait_for_idle()
    finally:
        await lifecycle.close()

    assert projection.max_concurrent == 1
    assert projection.calls == 2


class _BlockingCorpusProjection:
    """Wraps the real corpus projection but blocks inside one project_event.

    Lets a test hold a transcript re-projection open (inside the lifecycle's
    write lock) while it attempts a concurrent session deletion, mirroring the
    annotation path's _BlockingSearchProjection.
    """

    name = "blocking-corpus"

    def __init__(self, corpus: HistoryCorpusRepository) -> None:
        self._corpus = corpus
        self.entered = threading.Event()
        self.release = threading.Event()

    def rebuild(self) -> None:
        self._corpus.rebuild()

    def project_event(self, record: JournalEventRecord) -> None:
        self.entered.set()
        self.release.wait(5)
        self._corpus.project_event(record)

    def delete_session_projection(self, session_id: str) -> None:
        self._corpus.delete_session_projection(session_id)


@pytest.mark.asyncio
async def test_deleted_session_does_not_reappear_via_inflight_transcript_reprojection(
    tmp_path: Path,
) -> None:
    bus = EventBus()
    store, overlays, corpus = _build(tmp_path)
    store.append(_voice_event("2026-08-01T12:00:00+01:00", ("utterance.wav",)))
    reference = JournalEventRef(_SESSION, 0)
    projection = _BlockingCorpusProjection(corpus)
    lifecycle = HistoryProjectionLifecycle(
        bus,
        projections=(projection,),
        semantic_projection=UnavailableSemanticHistoryProjection(),
        transcript_event_source=JournalStoreTranscriptionSource(store),
    )

    await lifecycle.start()
    try:
        overlays.upsert_transcript(reference, _TRANSCRIPT, TranscriptSource.EDITED)
        await bus.publish(TranscriptOverlayChanged, TranscriptOverlayChanged(reference))
        # The re-projection is now inside the write lock, mid-write.
        assert await asyncio.to_thread(projection.entered.wait, 5)

        deletion = asyncio.ensure_future(
            asyncio.to_thread(lifecycle.delete_session_projections, _SESSION)
        )
        await asyncio.sleep(0.05)
        # Best-effort liveness check: deletion should still be blocked on the
        # write lock here. It is scheduler-sensitive (a not-yet-started executor
        # task also reads as not done), so it is not the deterministic
        # discriminator - the hits==() assertion below is. Without the fix,
        # deletion clears the row, then the unblocked write re-adds it, so that
        # assertion fails regardless of how this one is scheduled.
        assert not deletion.done()

        projection.release.set()
        await deletion
        await lifecycle.wait_for_idle()

        result = corpus.search(HistorySearchRequest("альфа", roles=("user",)))
        assert result.hits == ()
    finally:
        projection.release.set()
        await lifecycle.close()


class _GatedProjection:
    name = "gated"

    def __init__(self) -> None:
        self.calls = 0
        self.max_concurrent = 0
        self._current = 0
        self._lock = threading.Lock()
        self.entered = threading.Event()
        self.release = threading.Event()
        self._gate_first = True

    def rebuild(self) -> None:
        return

    def delete_session_projection(self, session_id: str) -> None:
        del session_id

    def project_event(self, record: JournalEventRecord) -> None:
        del record
        with self._lock:
            self._current += 1
            self.calls += 1
            self.max_concurrent = max(self.max_concurrent, self._current)
            gate = self._gate_first
            self._gate_first = False
        if gate:
            self.entered.set()
            self.release.wait(timeout=5)
        with self._lock:
            self._current -= 1


class _FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def embed(self, texts: tuple[str, ...] | list[str]) -> list[tuple[float, ...]]:
        self.calls.append(tuple(texts))
        return [(float(len(text)), 1.0, 0.0, 0.0) for text in texts]


class _UnavailableSemantic:
    def query(self, request: object) -> object:
        from jarvis.journal.semantic import (
            SemanticCandidateResult,
            SemanticCandidateStatus,
        )

        del request
        return SemanticCandidateResult(SemanticCandidateStatus.UNAVAILABLE)


def _semantic_settings() -> HistorySemanticSettings:
    return HistorySemanticSettings(
        enabled=True,
        model="fake-model",
        query_prefix="query: ",
        passage_prefix="passage: ",
        dimension=4,
    )
