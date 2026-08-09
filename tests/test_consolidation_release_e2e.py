"""Task v1.8.0-27: final integrated release verification, with consolidation
and the media lifecycle folded into the same picture cards 29/30 already
proved for text/voice/annotations.

Reuses the real HistoryCorpusRepository/SemanticPassageIndex/
HistoryRetrievalService/TranscriptOverlayRepository/AnnotationOverlayRepository
stack from tests/test_history_core_scale_recovery_e2e.py and
tests/test_voice_annotation_release_e2e.py, and adds the real
ConsolidationPlanner/ConsolidationExecutor/ArchiveOverlayRepository, wired
exactly as jarvis/app.py wires them.

Per the research behind this file: there is no age-based near/far window
anywhere in the shipped system (grepped - no ``[consolidation]`` config
section exists). Consolidation is entirely explicit and per-session: a
session becomes far-consolidation-eligible the moment it has audio media
*and* a transcript overlay for that exact event, and only an explicit
``execute_far_consolidation(session_id, ...)`` call ever removes bytes.
Consolidation's own crash-recovery, partial-failure, and per-session-lock
behavior are already thoroughly covered by
tests/test_consolidation_executor.py (task v1.8.0-25) and are not repeated
here. This file's job is the integration delta only: does everything cards
29/30 already verified - bounded prompt size, hybrid retrieval with
provenance, deletion-cannot-resurrect - still hold once consolidation has
actually run and removed some session's audio bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jarvis.app import ConversationHistory, Orchestrator
from jarvis.core.bus import EventBus
from jarvis.core.config import HistorySemanticSettings
from jarvis.core.lifecycle import TextSubmissionReason
from jarvis.journal import (
    AnnotationHistoryProjection,
    AnnotationOverlayRepository,
    AnnotationSearchIndex,
    AnnotationSemanticIndex,
    AnnotationSource,
    AnnotationTarget,
    ArchiveHistoryProjection,
    ArchiveOverlayRepository,
    ConsolidationExecutionOutcome,
    ConsolidationExecutor,
    ConsolidationPlanner,
    ConsolidationRunStatus,
    CorpusHistoryProjection,
    HistoryCorpusRepository,
    HistoryProjectionLifecycle,
    HistoryRetrievalQuery,
    HistoryRetrievalService,
    JournalEvent,
    JournalHistoryService,
    JournalSearchIndex,
    JournalStore,
    JournalStoreConsolidationSource,
    JournalStoreEventReferenceResolver,
    Pymorphy3Normalizer,
    SemanticPassageIndex,
    TranscriptHistoryProjection,
    TranscriptOverlayRepository,
    TranscriptSource,
)
from jarvis.journal.events import JournalEventRef
from jarvis.journal.transcript import TranscriptOverlayTextResolver

_DIMENSION = 8
_ANNOTATION_CONCEPT = 0
_FIRST_FILLER_BUCKET = 1
_FILLER_BUCKET_COUNT = _DIMENSION - _FIRST_FILLER_BUCKET

CANDIDATE_A_TRANSCRIPT = "Забронировал столик в кафе на восемь вечера."
CANDIDATE_A_QUERY = "столик в кафе"
CANDIDATE_B_TRANSCRIPT = "Нужно перезвонить электрику насчёт розетки."
CANDIDATE_B_QUERY = "перезвонить электрику"
ANNOTATION_TEXT = "Пользователь попросил напомнить про оплату интернета."
ANNOTATION_QUERY = "напомнить про оплату интернета"


class _TaggedEmbedder:
    def __init__(self, pinned: dict[str, int]) -> None:
        self._pinned = pinned

    def embed(self, texts):
        vectors = []
        for text in texts:
            vector = [0.0] * _DIMENSION
            bucket = self._pinned.get(text)
            if bucket is None:
                bucket = _FIRST_FILLER_BUCKET + (hash(text) % _FILLER_BUCKET_COUNT)
            vector[bucket] = 1.0
            vectors.append(tuple(vector))
        return vectors


def _settings() -> HistorySemanticSettings:
    return HistorySemanticSettings(
        model="tag-fixture",
        query_prefix="",
        passage_prefix="",
        separation=0.05,
        top_ratio=0.98,
        dimension=_DIMENSION,
    )


def _session_id(index: int) -> str:
    return f"20260101-{100000 + index:06d}-aa"


def _timestamp(day_offset: int) -> str:
    day = 1 + (day_offset % 27)
    month = 1 + (day_offset // 27) % 9
    return f"2026-{month:02d}-{day:02d}T09:00:00+00:00"


@dataclass
class _ConsolidationJournal:
    root: Path
    store: JournalStore
    corpus: HistoryCorpusRepository
    semantic: SemanticPassageIndex
    transcripts: TranscriptOverlayRepository
    annotations: AnnotationOverlayRepository
    annotation_lexical: AnnotationSearchIndex
    annotation_semantic: AnnotationSemanticIndex
    archive: ArchiveOverlayRepository
    consolidation_source: JournalStoreConsolidationSource
    planner: ConsolidationPlanner
    executor: ConsolidationExecutor
    candidate_a_reference: JournalEventRef
    candidate_b_reference: JournalEventRef
    annotation_id: str

    def service(self) -> HistoryRetrievalService:
        return HistoryRetrievalService(
            self.corpus,
            self.semantic,
            _settings(),
            Pymorphy3Normalizer(),
            annotation_lexical=self.annotation_lexical,
            annotation_semantic=self.annotation_semantic,
            annotation_repository=self.annotations,
        )

    def media_exists(self, reference: JournalEventRef, name: str) -> bool:
        return (self.store.root / reference.session_id / name).exists()


def _build_journal(root: Path, *, filler_events: int = 500) -> _ConsolidationJournal:
    store = JournalStore(root / "journal")
    resolver = JournalStoreEventReferenceResolver(store)

    candidate_a_session = _session_id(0)
    store.write_media(candidate_a_session, "utterance-0001.wav", b"fake-wav-bytes-a")
    candidate_a_reference = store.append(
        JournalEvent(
            session_id=candidate_a_session,
            timestamp=_timestamp(0),
            source="voice",
            role="user",
            text="",
            media=("utterance-0001.wav",),
            transcript=None,
        )
    )

    candidate_b_session = _session_id(1)
    store.write_media(candidate_b_session, "utterance-0001.wav", b"fake-wav-bytes-b")
    candidate_b_reference = store.append(
        JournalEvent(
            session_id=candidate_b_session,
            timestamp=_timestamp(1),
            source="voice",
            role="user",
            text="",
            media=("utterance-0001.wav",),
            transcript=None,
        )
    )

    annotation_session_id = _session_id(2)
    store.append(
        JournalEvent(
            session_id=annotation_session_id,
            timestamp=_timestamp(2),
            source="text",
            role="user",
            text="Не забыть оплатить счета в этом месяце.",
            media=(),
            transcript=None,
        )
    )

    for i in range(filler_events):
        session = _session_id(3 + i // 200)
        role = "user" if i % 2 == 0 else "assistant"
        source = "text" if role == "user" else "assistant"
        text = (
            f"Заметка {i}: обсуждали случайную тему номер {i % 40}, "
            "ничего важного не произошло."
        )
        store.append(
            JournalEvent(
                session_id=session,
                timestamp=_timestamp(3 + i // 200),
                source=source,
                role=role,
                text=text,
                media=(),
                transcript=None,
            )
        )

    transcripts = TranscriptOverlayRepository(root / "derived", resolver)
    transcript_resolver = TranscriptOverlayTextResolver(transcripts)
    corpus = HistoryCorpusRepository(store, root / "derived", transcript_resolver)

    for reference, text in (
        (candidate_a_reference, CANDIDATE_A_TRANSCRIPT),
        (candidate_b_reference, CANDIDATE_B_TRANSCRIPT),
    ):
        result = transcripts.upsert_transcript(
            reference, text, TranscriptSource.GENERATED
        )
        assert result.accepted, result.status

    corpus.rebuild()

    pinned = {
        ANNOTATION_TEXT: _ANNOTATION_CONCEPT,
        ANNOTATION_QUERY: _ANNOTATION_CONCEPT,
    }
    semantic = SemanticPassageIndex(
        corpus,
        root / "derived",
        _settings(),
        _TaggedEmbedder(pinned),
        transcripts=transcript_resolver,
    )
    semantic.rebuild()

    annotations = AnnotationOverlayRepository(root / "derived", resolver)
    annotation_lexical = AnnotationSearchIndex(annotations, root / "derived")
    annotation_semantic = AnnotationSemanticIndex(
        annotations, root / "derived", _settings(), _TaggedEmbedder(pinned)
    )
    add_result = annotations.add_annotation(
        AnnotationTarget(annotation_session_id, None, None),
        ANNOTATION_TEXT,
        "annotation-generator",
        AnnotationSource.GENERATED,
    )
    assert add_result.accepted, add_result.status
    assert add_result.annotation_id is not None
    written = annotations.read_annotation(add_result.annotation_id).annotation
    annotation_lexical.rebuild()
    annotation_semantic.rebuild()
    annotation_lexical.reproject_annotation(written)
    annotation_semantic.reproject_annotation(written)

    archive = ArchiveOverlayRepository(root / "journal")
    consolidation_source = JournalStoreConsolidationSource(store)
    planner = ConsolidationPlanner(consolidation_source, transcripts, annotations)
    executor = ConsolidationExecutor(planner, consolidation_source, archive)

    return _ConsolidationJournal(
        root,
        store,
        corpus,
        semantic,
        transcripts,
        annotations,
        annotation_lexical,
        annotation_semantic,
        archive,
        consolidation_source,
        planner,
        executor,
        candidate_a_reference,
        candidate_b_reference,
        add_result.annotation_id,
    )


def _no_active_session() -> str | None:
    return None


# --- consolidation removes audio, retrieval stays unaffected --------------


def test_consolidation_removes_audio_but_retrieval_stays_unaffected(
    tmp_path: Path,
) -> None:
    journal = _build_journal(tmp_path)
    reference = journal.candidate_a_reference
    assert journal.media_exists(reference, "utterance-0001.wav")

    before = journal.service().retrieve(
        HistoryRetrievalQuery(CANDIDATE_A_QUERY, limit=5)
    )
    before_matches = [c for c in before.candidates if c.reference == reference]
    assert before_matches, before

    result = journal.executor.execute_far_consolidation(
        reference.session_id, active_session_id_provider=_no_active_session
    )

    assert result.executed
    assert result.run is not None
    assert result.run.status is ConsolidationRunStatus.COMPLETED
    assert not journal.media_exists(reference, "utterance-0001.wav")

    after = journal.service().retrieve(
        HistoryRetrievalQuery(CANDIDATE_A_QUERY, limit=5)
    )
    after_matches = [c for c in after.candidates if c.reference == reference]
    assert after_matches, after
    assert after_matches[0].text == before_matches[0].text == CANDIDATE_A_TRANSCRIPT
    assert after_matches[0].text_is_transcript is True

    run_read = journal.archive.read_run(reference.session_id)
    assert run_read.found
    assert run_read.run.removed_count == 1


# --- active session is protected, at scale, alongside an eligible sibling --


def test_consolidation_never_touches_the_active_session(tmp_path: Path) -> None:
    journal = _build_journal(tmp_path)
    active_reference = journal.candidate_b_reference
    other_reference = journal.candidate_a_reference

    active_result = journal.executor.execute_far_consolidation(
        active_reference.session_id,
        active_session_id_provider=lambda: active_reference.session_id,
    )
    other_result = journal.executor.execute_far_consolidation(
        other_reference.session_id, active_session_id_provider=_no_active_session
    )

    assert active_result.outcome is ConsolidationExecutionOutcome.ACTIVE_SESSION
    assert not active_result.executed
    assert journal.media_exists(active_reference, "utterance-0001.wav")
    assert not journal.archive.read_run(active_reference.session_id).found

    assert other_result.executed
    assert not journal.media_exists(other_reference, "utterance-0001.wav")


# --- deletion clears the archive run too, and rebuild cannot resurrect it --


def test_deletion_after_consolidation_clears_archive_run_and_rebuild_cannot_resurrect(
    tmp_path: Path,
) -> None:
    journal = _build_journal(tmp_path)
    reference = journal.candidate_a_reference
    result = journal.executor.execute_far_consolidation(
        reference.session_id, active_session_id_provider=_no_active_session
    )
    assert result.executed
    assert journal.archive.read_run(reference.session_id).found

    # Deliberately routed through the real production deletion path -
    # JournalHistoryService.delete_session() + HistoryProjectionLifecycle -
    # not through manual per-store delete_session_projection() calls: only
    # the real fan-out proves app.py's actual wiring (which projections are
    # registered, in what order, under the same lock) actually clears the
    # archive run, not a hand-rolled substitute that could pass even if the
    # production wiring forgot a store.
    bus = EventBus()
    lifecycle = HistoryProjectionLifecycle(
        bus,
        projections=(
            CorpusHistoryProjection(journal.corpus),
            TranscriptHistoryProjection(journal.transcripts),
            AnnotationHistoryProjection(journal.annotations),
            ArchiveHistoryProjection(journal.archive),
        ),
        semantic_projection=journal.semantic,
        annotation_projections=(
            journal.annotation_lexical,
            journal.annotation_semantic,
        ),
        annotation_source=journal.annotations,
    )
    search_index = JournalSearchIndex(
        journal.store,
        journal.root / "derived",
        TranscriptOverlayTextResolver(journal.transcripts),
    )
    service = JournalHistoryService(journal.store, lifecycle, search_index)

    service.delete_session(reference.session_id)

    journal.corpus.rebuild()
    journal.semantic.rebuild()
    journal.transcripts.rebuild()
    journal.archive.rebuild()

    assert not journal.archive.read_run(reference.session_id).found
    remaining = {s.session_id for s in journal.store.list_sessions()}
    assert reference.session_id not in remaining
    after = journal.service().retrieve(
        HistoryRetrievalQuery(CANDIDATE_A_QUERY, limit=5)
    )
    assert not any(c.reference == reference for c in after.candidates)


# --- fully integrated: consolidation + scale + real Orchestrator turn -----


class _FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[list[dict], list[str] | None]] = []

    async def chat(self, messages, images_b64=None, reasoning_level=None) -> None:
        self.calls.append((messages, images_b64))


class _FakeSoundCues:
    def __init__(self) -> None:
        self.played: list[str] = []

    async def play(self, cue: str) -> None:
        self.played.append(cue)


async def test_annotation_reachable_via_automatic_retrieval_after_consolidation(
    tmp_path: Path,
) -> None:
    """The final integration proof: run a real far-consolidation on a large
    synthetic journal, then drive a real Orchestrator turn and confirm
    unrelated retrieval (here: an annotation, reaching automatic retrieval
    the same way task 30 proved) is completely unaffected by consolidation
    having removed a different session's audio bytes."""

    journal = _build_journal(tmp_path, filler_events=3000)
    consolidated = journal.executor.execute_far_consolidation(
        journal.candidate_a_reference.session_id,
        active_session_id_provider=_no_active_session,
    )
    assert consolidated.executed

    bus = EventBus()
    backend = _FakeBackend()
    orchestrator = Orchestrator(
        backend,
        ConversationHistory(),
        _FakeSoundCues(),
        bus=bus,
        history_retrieval_service=journal.service(),
    )

    result = await orchestrator.submit_text_input(ANNOTATION_QUERY)

    assert result.reason is TextSubmissionReason.ACCEPTED
    [(messages, _media)] = backend.calls
    contents = [str(m.get("content", "")) for m in messages]
    retrieved = next(c for c in contents if "Retrieved history" in c)
    assert ANNOTATION_TEXT in retrieved
    assert '"kind":"annotation"' in retrieved
