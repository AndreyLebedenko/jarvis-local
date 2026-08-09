"""Task v1.8.0-30: v1.8.1 (voice + annotation) release verification e2e.

Real HistoryCorpusRepository/SemanticPassageIndex/HistoryRetrievalService,
TranscriptOverlayRepository, AnnotationOverlayRepository, AnnotationSearchIndex,
and AnnotationSemanticIndex instances, wired through a real
HistoryProjectionLifecycle exactly as production wires them
(``jarvis.app``), driven through a real ``Orchestrator`` with a fake chat
backend where relevant. No live Ollama, network, or hardware - a
deterministic tagged fixture embedder stands in for the real backend, per
the project testing protocol.

Covers what task v1.8.0-29's text-only slice does not: a transcribed voice
turn becoming retrievable with provenance, an annotation becoming retrievable
through automatic retrieval with its typed "kind=annotation" framing,
editability, incremental (non-rebuild) reprojection for both, and
deletion-then-rebuild-cannot-resurrect extended to the transcript/annotation
overlay and projection stores that task 29 did not cover.

The production event flow this file mirrors (see src/jarvis/ui/transport.py's
``_journal_transcript_generate_handler``/``_journal_transcript_put_handler``
and src/jarvis/journal/annotation_generator.py's ``_publish_change``): a
transcript or annotation write is followed by publishing
``TranscriptOverlayChanged``/``AnnotationOverlayChanged`` on the event bus,
which ``HistoryProjectionLifecycle`` picks up to reproject just that one
event/annotation - never a whole-session rebuild.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jarvis.app import ConversationHistory, Orchestrator
from jarvis.core.bus import EventBus
from jarvis.core.config import HistorySemanticSettings
from jarvis.core.lifecycle import ModelRequestStarted, TextSubmissionReason
from jarvis.journal import (
    AnnotationHistoryProjection,
    AnnotationOverlayChanged,
    AnnotationOverlayRepository,
    AnnotationSearchIndex,
    AnnotationSearchRequest,
    AnnotationSemanticIndex,
    AnnotationSource,
    AnnotationTarget,
    CorpusHistoryProjection,
    HistoryCorpusRepository,
    HistoryProjectionLifecycle,
    HistoryRetrievalQuery,
    HistoryRetrievalService,
    JournalEvent,
    JournalHistoryService,
    JournalSearchIndex,
    JournalStore,
    JournalStoreEventReferenceResolver,
    JournalStoreTranscriptionSource,
    Pymorphy3Normalizer,
    SemanticPassageIndex,
    TranscriptHistoryProjection,
    TranscriptOverlayRepository,
    TranscriptSource,
)
from jarvis.journal.events import JournalEventRef
from jarvis.journal.transcript import (
    TranscriptOverlayChanged,
    TranscriptOverlayTextResolver,
)

# --- fixture embedder (mirrors test_history_core_scale_recovery_e2e.py) ---

_DIMENSION = 10
_ANNOTATION_CONCEPT = 0
_FIRST_FILLER_BUCKET = 1
_FILLER_BUCKET_COUNT = _DIMENSION - _FIRST_FILLER_BUCKET

VOICE_TRANSCRIPT_TEXT = "На кухне нужно заменить фильтр для воды до пятницы."
VOICE_EXPLICIT_QUERY = "фильтр для воды"
ANNOTATION_TEXT = "Пользователь попросил проверить давление в шинах в среду."
ANNOTATION_QUERY = "проверить давление в шинах"


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


class _CallCounter:
    """Wraps an object, counting calls to the named methods while
    transparently forwarding everything else (attributes and other
    methods), so the real production stores can be used unmodified
    everywhere except the assertions that need a rebuild-vs-incremental
    call count."""

    def __init__(self, inner: object, *, counted: tuple[str, ...]) -> None:
        self._inner = inner
        self.calls: dict[str, int] = dict.fromkeys(counted, 0)

    def __getattr__(self, name: str):
        attr = getattr(self._inner, name)
        if name in self.calls:

            def _wrapper(*args, **kwargs):
                self.calls[name] += 1
                return attr(*args, **kwargs)

            return _wrapper
        return attr


@dataclass
class _VoiceAnnotationJournal:
    root: Path
    store: JournalStore
    corpus: HistoryCorpusRepository
    semantic: SemanticPassageIndex
    transcripts: TranscriptOverlayRepository
    annotations: AnnotationOverlayRepository
    annotation_lexical: AnnotationSearchIndex
    annotation_semantic: AnnotationSemanticIndex
    voice_reference: JournalEventRef
    annotation_session_id: str
    annotation_id: str
    filler_session_id: str
    filler_reference: JournalEventRef

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


def _build_journal(root: Path, *, filler_events: int = 500) -> _VoiceAnnotationJournal:
    store = JournalStore(root / "journal")
    resolver = JournalStoreEventReferenceResolver(store)

    voice_reference = store.append(
        JournalEvent(
            session_id=_session_id(0),
            timestamp=_timestamp(0),
            source="voice",
            role="user",
            text="",
            media=(),
            transcript=None,
        )
    )

    annotation_session_id = _session_id(1)
    store.append(
        JournalEvent(
            session_id=annotation_session_id,
            timestamp=_timestamp(1),
            source="text",
            role="user",
            text="Какое давление должно быть в шинах моей машины?",
            media=(),
            transcript=None,
        )
    )
    store.append(
        JournalEvent(
            session_id=annotation_session_id,
            timestamp=_timestamp(1),
            source="assistant",
            role="assistant",
            text="Обычно 2.2-2.4 бар, но сверься с наклейкой на двери.",
            media=(),
            transcript=None,
        )
    )

    filler_session_id = _session_id(2)
    filler_reference = None
    for i in range(filler_events):
        session = _session_id(3 + i // 200)
        role = "user" if i % 2 == 0 else "assistant"
        source = "text" if role == "user" else "assistant"
        text = (
            f"Заметка {i}: обсуждали случайную тему номер {i % 40}, "
            "ничего важного не произошло."
        )
        reference = store.append(
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
        if i == 0:
            filler_session_id = session
            filler_reference = reference
    assert filler_reference is not None

    transcripts = TranscriptOverlayRepository(root / "derived", resolver)
    transcript_resolver = TranscriptOverlayTextResolver(transcripts)
    corpus = HistoryCorpusRepository(store, root / "derived", transcript_resolver)
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
    annotation_lexical.rebuild()
    annotation_semantic = AnnotationSemanticIndex(
        annotations, root / "derived", _settings(), _TaggedEmbedder(pinned)
    )
    annotation_semantic.rebuild()

    add_result = annotations.add_annotation(
        AnnotationTarget(annotation_session_id, None, None),
        ANNOTATION_TEXT,
        "annotation-generator",
        AnnotationSource.GENERATED,
    )
    assert add_result.accepted, add_result.status
    assert add_result.annotation_id is not None
    annotation_lexical.reproject_annotation(
        annotations.read_annotation(add_result.annotation_id).annotation
    )
    annotation_semantic.reproject_annotation(
        annotations.read_annotation(add_result.annotation_id).annotation
    )

    return _VoiceAnnotationJournal(
        root,
        store,
        corpus,
        semantic,
        transcripts,
        annotations,
        annotation_lexical,
        annotation_semantic,
        voice_reference,
        annotation_session_id,
        add_result.annotation_id,
        filler_session_id,
        filler_reference,
    )


# --- fake orchestration seam (mirrors test_history_core_scale_recovery_e2e.py) ---


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


class _RequestRecorder:
    def __init__(self, bus: EventBus) -> None:
        self.events: list[ModelRequestStarted] = []
        bus.subscribe(ModelRequestStarted, self._on_event)

    async def _on_event(self, event: ModelRequestStarted) -> None:
        self.events.append(event)


def _drive_turn(retrieval_service, bus: EventBus | None = None):
    bus = bus or EventBus()
    recorder = _RequestRecorder(bus)
    backend = _FakeBackend()
    orchestrator = Orchestrator(
        backend,
        ConversationHistory(),
        _FakeSoundCues(),
        bus=bus,
        history_retrieval_service=retrieval_service,
    )
    return orchestrator, backend, recorder


def _messages_content(messages: list[dict]) -> list[str]:
    return [str(message.get("content", "")) for message in messages]


# --- voice retrievability -------------------------------------------------


def test_voice_transcript_reachable_through_explicit_unfiltered_retrieval(
    tmp_path: Path,
) -> None:
    """A transcribed voice turn is retrievable with provenance through the
    same explicit (unfiltered-sources) path the search_history tool and the
    Journal UI use -- this is the "voice turns become retrievable after
    explicit local transcription" acceptance criterion."""

    journal = _build_journal(tmp_path)
    result = journal.transcripts.upsert_transcript(
        journal.voice_reference, VOICE_TRANSCRIPT_TEXT, TranscriptSource.GENERATED
    )
    assert result.accepted, result.status
    journal.corpus.project_event(_record_for(journal.store, journal.voice_reference))
    journal.semantic.project_event(_record_for(journal.store, journal.voice_reference))

    retrieval = journal.service().retrieve(
        HistoryRetrievalQuery(VOICE_EXPLICIT_QUERY, limit=5)
    )

    matches = [
        c for c in retrieval.candidates if c.reference == journal.voice_reference
    ]
    assert matches, retrieval
    [candidate] = matches
    assert candidate.text_is_transcript is True
    assert VOICE_TRANSCRIPT_TEXT in candidate.text


def _record_for(store: JournalStore, reference: JournalEventRef):
    from jarvis.journal.events import JournalEventRecord

    replay = store.read_session(reference.session_id)
    event = replay.records[reference.event_position].event
    return JournalEventRecord(reference=reference, event=event)


async def test_voice_transcript_is_not_reached_by_automatic_retrieval_by_default(
    tmp_path: Path,
) -> None:
    """Regression guard for a real, documented limitation: automatic
    (implicit, pre-turn) retrieval defaults to sources=("text",), so a
    transcribed voice turn (source="voice") does not enter the automatic
    working context even though it is explicitly retrievable (see the test
    above). README.md/PROJECT.md must describe this precisely, not claim
    voice is unconditionally "retrievable" now."""

    journal = _build_journal(tmp_path)
    upsert = journal.transcripts.upsert_transcript(
        journal.voice_reference, VOICE_TRANSCRIPT_TEXT, TranscriptSource.GENERATED
    )
    assert upsert.accepted
    journal.corpus.project_event(_record_for(journal.store, journal.voice_reference))
    journal.semantic.project_event(_record_for(journal.store, journal.voice_reference))

    orchestrator, backend, _recorder = _drive_turn(journal.service())
    result = await orchestrator.submit_text_input(VOICE_EXPLICIT_QUERY)

    assert result.reason is TextSubmissionReason.ACCEPTED
    [(messages, _media)] = backend.calls
    contents = _messages_content(messages)
    retrieved_blocks = [c for c in contents if "Retrieved history" in c]
    assert not any(VOICE_TRANSCRIPT_TEXT in block for block in retrieved_blocks)


# --- annotation retrievability, editability, traceability -----------------


async def test_annotation_reachable_through_automatic_retrieval_with_typed_framing(
    tmp_path: Path,
) -> None:
    """Annotations bypass the roles/sources filter entirely (unlike voice
    events), so a session annotation should reach the ordinary automatic
    retrieval path -- exercised here through a real Orchestrator turn."""

    journal = _build_journal(tmp_path)
    orchestrator, backend, _recorder = _drive_turn(journal.service())

    result = await orchestrator.submit_text_input(ANNOTATION_QUERY)

    assert result.reason is TextSubmissionReason.ACCEPTED
    [(messages, _media)] = backend.calls
    contents = _messages_content(messages)
    retrieved = next(c for c in contents if "Retrieved history" in c)
    assert ANNOTATION_TEXT in retrieved
    assert '"kind":"annotation"' in retrieved
    assert journal.annotation_id in retrieved
    assert journal.annotation_session_id in retrieved
    assert '"source":"generated"' in retrieved


def test_annotation_edit_is_reflected_and_traceable_to_its_target(
    tmp_path: Path,
) -> None:
    journal = _build_journal(tmp_path)
    edited_text = "ОБНОВЛЕНО: давление в шинах проверять каждый вторник."
    update = journal.annotations.update_annotation(
        journal.annotation_id, text=edited_text, source=AnnotationSource.EDITED
    )
    assert update.accepted, update.status
    updated = journal.annotations.read_annotation(journal.annotation_id).annotation
    journal.annotation_lexical.reproject_annotation(updated)
    journal.annotation_semantic.reproject_annotation(updated)

    result = journal.service().retrieve(
        HistoryRetrievalQuery(ANNOTATION_QUERY, limit=5)
    )

    matches = [
        c
        for c in result.candidates
        if c.annotation is not None
        and c.annotation.annotation_id == journal.annotation_id
    ]
    assert matches
    [candidate] = matches
    assert candidate.text == edited_text
    assert ANNOTATION_TEXT not in candidate.text
    assert candidate.annotation.source == "edited"
    assert candidate.annotation.session_id == journal.annotation_session_id
    assert candidate.annotation.is_whole_session


# --- incremental update: no whole-session/whole-corpus rebuild -------------


async def test_transcript_and_annotation_edits_reproject_incrementally(
    tmp_path: Path,
) -> None:
    journal = _build_journal(tmp_path)
    bus = EventBus()

    corpus = _CallCounter(journal.corpus, counted=("rebuild", "project_event"))
    semantic = _CallCounter(journal.semantic, counted=("rebuild", "project_event"))
    annotation_lexical = _CallCounter(
        journal.annotation_lexical, counted=("rebuild", "reproject_annotation")
    )
    annotation_semantic = _CallCounter(
        journal.annotation_semantic,
        counted=("rebuild_if_backend_changed", "reproject_annotation"),
    )

    lifecycle = HistoryProjectionLifecycle(
        bus,
        projections=(
            CorpusHistoryProjection(corpus),
            TranscriptHistoryProjection(journal.transcripts),
            AnnotationHistoryProjection(journal.annotations),
        ),
        semantic_projection=semantic,
        transcript_event_source=JournalStoreTranscriptionSource(journal.store),
        annotation_projections=(annotation_lexical, annotation_semantic),
        annotation_source=journal.annotations,
    )
    await lifecycle.start()
    try:
        # Snapshot an unrelated session's corpus text before touching anything.
        before = journal.corpus.list_events()
        untouched_before = {
            e.reference: e.effective_text
            for e in before
            if e.reference.session_id == journal.filler_session_id
        }

        # Baseline after startup rebuild: reset deltas from here.
        for counter in (corpus, semantic, annotation_lexical, annotation_semantic):
            for key in counter.calls:
                counter.calls[key] = 0

        upsert = journal.transcripts.upsert_transcript(
            journal.voice_reference, VOICE_TRANSCRIPT_TEXT, TranscriptSource.GENERATED
        )
        assert upsert.accepted
        await bus.publish(
            TranscriptOverlayChanged, TranscriptOverlayChanged(journal.voice_reference)
        )
        await lifecycle.wait_for_idle()

        edited_text = "ОБНОВЛЕНО: давление в шинах проверять каждый вторник."
        update = journal.annotations.update_annotation(
            journal.annotation_id, text=edited_text, source=AnnotationSource.EDITED
        )
        assert update.accepted
        await bus.publish(
            AnnotationOverlayChanged,
            AnnotationOverlayChanged(
                journal.annotation_session_id, journal.annotation_id
            ),
        )
        await lifecycle.wait_for_idle()

        assert corpus.calls["rebuild"] == 0
        assert corpus.calls["project_event"] == 1
        assert semantic.calls["rebuild"] == 0
        assert semantic.calls["project_event"] == 1
        assert annotation_lexical.calls["rebuild"] == 0
        assert annotation_lexical.calls["reproject_annotation"] == 1
        assert annotation_semantic.calls["reproject_annotation"] == 1

        after = journal.corpus.list_events()
        untouched_after = {
            e.reference: e.effective_text
            for e in after
            if e.reference.session_id == journal.filler_session_id
        }
        assert untouched_after == untouched_before
    finally:
        await lifecycle.close()


# --- deletion cannot be resurrected by rebuild, extended to all six stores -


def test_deletion_prevents_rebuild_resurrection_of_transcript_and_annotation(
    tmp_path: Path,
) -> None:
    journal = _build_journal(tmp_path)
    upsert = journal.transcripts.upsert_transcript(
        journal.voice_reference, VOICE_TRANSCRIPT_TEXT, TranscriptSource.GENERATED
    )
    assert upsert.accepted
    journal.corpus.project_event(_record_for(journal.store, journal.voice_reference))
    journal.semantic.project_event(_record_for(journal.store, journal.voice_reference))
    voice_session = journal.voice_reference.session_id
    annotation_session = journal.annotation_session_id
    annotation_id = journal.annotation_id

    before = journal.service().retrieve(
        HistoryRetrievalQuery(ANNOTATION_QUERY, limit=5)
    )
    assert any(
        c.annotation is not None and c.annotation.annotation_id == annotation_id
        for c in before.candidates
    )

    # Deliberately routed through the real production deletion path -
    # JournalHistoryService.delete_session() + HistoryProjectionLifecycle -
    # not manual per-store delete_session_projection() calls: only the real
    # fan-out proves app.py's actual wiring (which projections are
    # registered, in what order, under the same lock) actually clears every
    # store, not a hand-rolled substitute that could pass even if the
    # production wiring forgot one.
    bus = EventBus()
    lifecycle = HistoryProjectionLifecycle(
        bus,
        projections=(
            CorpusHistoryProjection(journal.corpus),
            TranscriptHistoryProjection(journal.transcripts),
            AnnotationHistoryProjection(journal.annotations),
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

    service.delete_session(voice_session)
    service.delete_session(annotation_session)

    # Direct index-level checks, deliberately not routed through
    # HistoryRetrievalService: its candidate hydration re-reads the
    # *overlay* store (already correctly emptied above) and silently drops
    # any candidate it can't find there, regardless of whether the lexical/
    # semantic index row itself was actually purged. A stale row sitting in
    # AnnotationSearchIndex/AnnotationSemanticIndex would therefore pass a
    # retrieval-service-only assertion undetected - query each index
    # directly, both right after delete_session_projection() (isolating
    # deletion from rebuild) and again after rebuild() below.
    _assert_annotation_absent_from_indexes(journal, annotation_id)

    journal.corpus.rebuild()
    journal.semantic.rebuild()
    journal.transcripts.rebuild()
    journal.annotations.rebuild()
    journal.annotation_lexical.rebuild()
    journal.annotation_semantic.rebuild()

    remaining_sessions = {s.session_id for s in journal.store.list_sessions()}
    assert voice_session not in remaining_sessions
    assert annotation_session not in remaining_sessions
    assert journal.transcripts.read_transcript(journal.voice_reference).overlay is None
    assert journal.annotations.read_annotation(annotation_id).annotation is None
    _assert_annotation_absent_from_indexes(journal, annotation_id)

    after = journal.service().retrieve(HistoryRetrievalQuery(ANNOTATION_QUERY, limit=5))
    assert not any(
        c.annotation is not None and c.annotation.annotation_id == annotation_id
        for c in after.candidates
    )
    voice_query = journal.service().retrieve(
        HistoryRetrievalQuery(VOICE_EXPLICIT_QUERY, limit=5)
    )
    assert not any(
        c.reference == journal.voice_reference for c in voice_query.candidates
    )


def _assert_annotation_absent_from_indexes(
    journal: _VoiceAnnotationJournal, annotation_id: str
) -> None:
    lexical_hits = journal.annotation_lexical.search(
        AnnotationSearchRequest(query="давление")
    )
    assert not any(hit.annotation_id == annotation_id for hit in lexical_hits.hits)
    semantic_passages = journal.annotation_semantic.list_passages()
    assert not any(p.annotation_id == annotation_id for p in semantic_passages)
