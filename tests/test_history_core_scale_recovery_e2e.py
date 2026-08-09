"""Task v1.8.0-29: v1.8.0 core (cards 8-17) scale, recovery, and e2e.

Text-only slice: a large synthetic journal drives real
``HistoryCorpusRepository``/``SemanticPassageIndex``/``HistoryRetrievalService``
instances (no live Ollama, network access, or hardware -- a deterministic
tagged fixture embedder stands in for the real backend, per the project
testing protocol), wired into a real ``Orchestrator`` with a fake chat
backend. Covers: bounded prompt size under scale, semantic retrieval of an
old paraphrased fact with provenance, exact/lexical fallback for a literal
identifier, automatic-retrieval degradation (timeout vs unavailable),
projection rebuild recovery, and deletion irreversibility across
corpus/lexical/semantic projections.

The measured, owner-accepted latency characteristic of the semantic
brute-force scan (see ``tasks/bug_reports/2026-08-02-semantic-hot-path-scan-
remains-unbounded.md`` and its PROJECT.md entry) is recorded here as a
regression guard against catastrophic (not merely linear) blowup, not as a
requirement that it stay flat.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jarvis.app import ConversationHistory, Orchestrator
from jarvis.core.bus import EventBus
from jarvis.core.config import HistorySemanticSettings
from jarvis.core.lifecycle import ModelRequestStarted, TextSubmissionReason
from jarvis.journal import (
    HistoryCorpusRepository,
    HistoryRetrievalQuery,
    HistoryRetrievalService,
    JournalEvent,
    JournalStore,
    Pymorphy3Normalizer,
    SemanticCandidateResult,
    SemanticCandidateStatus,
    SemanticPassageIndex,
)
from jarvis.journal.corpus import HistorySearchRequest
from jarvis.journal.events import JournalEventRef
from jarvis.journal.semantic import SemanticCandidateQuery

# --- fixture embedder ----------------------------------------------------

_DIMENSION = 10
_GARAGE_CONCEPT = 0
_NEUTRAL_PROBE_CONCEPT = 1
_FIRST_FILLER_BUCKET = 2
_FILLER_BUCKET_COUNT = _DIMENSION - _FIRST_FILLER_BUCKET

OLD_FACT_TEXT = "Гараж запирается кодом Браво-Семь-Один-Девять."
PARAPHRASE_QUERY = "Расскажи про доступ к мастерской с инструментами."
IDENTIFIER_FACT_TEXT = "Код активации принтера: XK4821PLM."
IDENTIFIER_QUERY = "XK4821PLM"
NEUTRAL_QUERY = "Как сегодня погода?"


class _TaggedEmbedder:
    """Deterministic fixture embedder (no model, no VRAM, no network).

    A handful of pinned texts get an exact reserved-bucket one-hot vector;
    every other text (the synthetic filler) hashes into a disjoint noise
    bucket, so filler can never accidentally collide with a pinned concept
    and pollute a semantic-only assertion.
    """

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


class _TimeoutSemanticCandidates:
    def query(self, request: SemanticCandidateQuery) -> SemanticCandidateResult:
        del request
        return SemanticCandidateResult(SemanticCandidateStatus.TIMEOUT)


class _UnavailableSemanticCandidates:
    def query(self, request: SemanticCandidateQuery) -> SemanticCandidateResult:
        del request
        return SemanticCandidateResult(SemanticCandidateStatus.UNAVAILABLE)


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


def _filler_text(index: int) -> str:
    return (
        f"Заметка {index}: обсуждали случайную тему номер {index % 40}, "
        "ничего важного не произошло."
    )


@dataclass
class _ScaleJournal:
    store: JournalStore
    corpus: HistoryCorpusRepository
    semantic: SemanticPassageIndex
    old_fact_reference: JournalEventRef
    identifier_fact_reference: JournalEventRef

    def service(self, *, semantic_candidates=None) -> HistoryRetrievalService:
        return HistoryRetrievalService(
            self.corpus,
            semantic_candidates if semantic_candidates is not None else self.semantic,
            _settings(),
            Pymorphy3Normalizer(),
        )


def _build_scale_journal(root: Path, *, filler_events: int) -> _ScaleJournal:
    store = JournalStore(root / "journal")
    pinned: dict[str, int] = {
        OLD_FACT_TEXT: _GARAGE_CONCEPT,
        PARAPHRASE_QUERY: _GARAGE_CONCEPT,
        NEUTRAL_QUERY: _NEUTRAL_PROBE_CONCEPT,
    }

    # Automatic retrieval's default source filter only admits ``source="text"``
    # (typed/spoken user input) -- see ``_DEFAULT_SOURCES`` in
    # ``jarvis/history/automatic_retrieval.py`` -- matching the project
    # convention where a user turn's ``source`` is the input medium ("text"),
    # not its role. Both pinned facts must be user turns to be reachable by
    # the real automatic-retrieval pipeline exercised end to end here.
    old_fact_reference = store.append(
        JournalEvent(
            session_id=_session_id(0),
            timestamp=_timestamp(0),
            source="text",
            role="user",
            text=OLD_FACT_TEXT,
            media=(),
            transcript=None,
        )
    )
    identifier_fact_reference = store.append(
        JournalEvent(
            session_id=_session_id(1),
            timestamp=_timestamp(1),
            source="text",
            role="user",
            text=IDENTIFIER_FACT_TEXT,
            media=(),
            transcript=None,
        )
    )

    for i in range(filler_events):
        session = _session_id(2 + i // 200)
        role = "user" if i % 2 == 0 else "assistant"
        source = "text" if role == "user" else "assistant"
        store.append(
            JournalEvent(
                session_id=session,
                timestamp=_timestamp(2 + i // 200),
                source=source,
                role=role,
                text=_filler_text(i),
                media=(),
                transcript=None,
            )
        )

    corpus = HistoryCorpusRepository(store, root / "derived")
    corpus.rebuild()
    semantic = SemanticPassageIndex(
        corpus, root / "derived", _settings(), _TaggedEmbedder(pinned)
    )
    semantic.rebuild()
    return _ScaleJournal(
        store, corpus, semantic, old_fact_reference, identifier_fact_reference
    )


# --- fake orchestration seam ----------------------------------------------


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


def _drive_turn(retrieval_service, text: str):
    bus = EventBus()
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


# --- bounded prompt size under scale --------------------------------------


async def test_prompt_size_stays_bounded_as_synthetic_journal_scales(
    tmp_path: Path,
) -> None:
    message_counts = []
    token_counts = []
    for size_index, filler_events in enumerate((300, 3000, 12000)):
        journal = _build_scale_journal(
            tmp_path / f"scale-{size_index}", filler_events=filler_events
        )
        orchestrator, backend, recorder = _drive_turn(journal.service(), NEUTRAL_QUERY)

        result = await orchestrator.submit_text_input(NEUTRAL_QUERY)

        assert result.reason is TextSubmissionReason.ACCEPTED
        [(messages, _media)] = backend.calls
        message_counts.append(len(messages))
        [event] = recorder.events
        assert event.prompt_budget is not None
        token_counts.append(event.prompt_budget["estimated_prompt_tokens"])
        # The neutral probe is pinned to its own reserved concept bucket, so
        # it never matches the garage fact, the printer fact, or any filler
        # note regardless of how large the journal grows.
        assert event.prompt_budget["retrieval_message_count"] == 0

    assert message_counts == [message_counts[0]] * len(message_counts), (
        "assembled message count must not grow with journal size, "
        f"got {message_counts} across journal sizes 300/3000/12000"
    )
    assert token_counts == [token_counts[0]] * len(token_counts), (
        "estimated prompt tokens must not grow with journal size, "
        f"got {token_counts} across journal sizes 300/3000/12000"
    )


# --- semantic retrieval of an old paraphrased fact -------------------------


async def test_hybrid_retrieval_brings_old_paraphrased_fact_with_provenance(
    tmp_path: Path,
) -> None:
    journal = _build_scale_journal(tmp_path, filler_events=4000)
    orchestrator, backend, _recorder = _drive_turn(journal.service(), PARAPHRASE_QUERY)

    result = await orchestrator.submit_text_input(PARAPHRASE_QUERY)

    assert result.reason is TextSubmissionReason.ACCEPTED
    [(messages, _media)] = backend.calls
    contents = _messages_content(messages)
    retrieved = next(content for content in contents if "Retrieved history" in content)
    assert OLD_FACT_TEXT in retrieved
    assert journal.old_fact_reference.session_id in retrieved
    assert f'"event_position":{journal.old_fact_reference.event_position}' in retrieved
    # No lexical token overlap exists between the query and any filler note,
    # nor between the query and the garage fact itself -- only the fixture
    # embedder's shared concept bucket connects them, so this proves the
    # semantic path, not lexical luck, carried the fact.
    assert "Заметка" not in retrieved
    assert IDENTIFIER_FACT_TEXT not in retrieved


# --- exact/lexical fallback for a literal identifier ------------------------


async def test_lexical_fallback_retrieves_identifier_when_semantic_unavailable(
    tmp_path: Path,
) -> None:
    journal = _build_scale_journal(tmp_path, filler_events=4000)
    service = journal.service(semantic_candidates=_UnavailableSemanticCandidates())
    orchestrator, backend, recorder = _drive_turn(service, IDENTIFIER_QUERY)

    result = await orchestrator.submit_text_input(IDENTIFIER_QUERY)

    assert result.reason is TextSubmissionReason.ACCEPTED
    [(messages, _media)] = backend.calls
    contents = _messages_content(messages)
    retrieved = next(content for content in contents if "Retrieved history" in content)
    assert "XK4821PLM" in retrieved
    assert journal.identifier_fact_reference.session_id in retrieved
    [event] = recorder.events
    assert event.prompt_budget is not None
    assert event.prompt_budget["retrieval_lexical_by_unavailable"] is True
    assert event.prompt_budget["retrieval_lexical_by_timeout"] is False
    assert event.prompt_budget["retrieval_full_hybrid"] is False


# --- automatic retrieval degradation: timeout vs unavailable ---------------


async def test_retrieval_degrades_to_lexical_on_semantic_timeout_and_dispatches(
    tmp_path: Path,
) -> None:
    journal = _build_scale_journal(tmp_path, filler_events=4000)
    service = journal.service(semantic_candidates=_TimeoutSemanticCandidates())
    orchestrator, backend, recorder = _drive_turn(service, IDENTIFIER_QUERY)

    result = await orchestrator.submit_text_input(IDENTIFIER_QUERY)

    assert result.reason is TextSubmissionReason.ACCEPTED
    # Generation dispatched despite the semantic path failing -- the turn was
    # never held up waiting on it.
    assert len(backend.calls) == 1
    [(messages, _media)] = backend.calls
    retrieved = next(
        str(message.get("content", ""))
        for message in messages
        if "Retrieved history" in str(message.get("content", ""))
    )
    assert "XK4821PLM" in retrieved
    [event] = recorder.events
    assert event.prompt_budget is not None
    assert event.prompt_budget["retrieval_lexical_by_timeout"] is True
    assert event.prompt_budget["retrieval_lexical_by_unavailable"] is False
    assert event.prompt_budget["retrieval_full_hybrid"] is False


async def test_automatic_retrieval_fallback_mode_distinguishes_unavailable_from_timeout(
    tmp_path: Path,
) -> None:
    """Companion to the timeout test above: same query, opposite semantic
    failure mode, to prove the two are reported distinctly, not collapsed
    into one generic "degraded" flag."""

    journal = _build_scale_journal(tmp_path, filler_events=1000)
    service = journal.service(semantic_candidates=_UnavailableSemanticCandidates())
    orchestrator, backend, recorder = _drive_turn(service, IDENTIFIER_QUERY)

    result = await orchestrator.submit_text_input(IDENTIFIER_QUERY)

    assert result.reason is TextSubmissionReason.ACCEPTED
    assert len(backend.calls) == 1
    [event] = recorder.events
    assert event.prompt_budget is not None
    assert event.prompt_budget["retrieval_lexical_by_unavailable"] is True
    assert event.prompt_budget["retrieval_lexical_by_timeout"] is False


# --- projection rebuild recovery -------------------------------------------


def test_projection_rebuild_recovers_corpus_lexical_semantic_from_raw_journal(
    tmp_path: Path,
) -> None:
    journal = _build_scale_journal(tmp_path, filler_events=1500)

    before = journal.service().retrieve(
        HistoryRetrievalQuery(PARAPHRASE_QUERY, limit=5)
    )
    assert any(
        candidate.reference == journal.old_fact_reference
        for candidate in before.candidates
    )

    # Simulate a crash: the derived SQLite projections are gone, the raw
    # journal is untouched.
    journal.corpus.db_path.unlink()
    journal.semantic.db_path.unlink()

    journal.corpus.rebuild()
    journal.semantic.rebuild()

    after = journal.service().retrieve(HistoryRetrievalQuery(PARAPHRASE_QUERY, limit=5))
    assert any(
        candidate.reference == journal.old_fact_reference
        for candidate in after.candidates
    )
    lexical_hits = journal.corpus.search(HistorySearchRequest(query="Браво"))
    assert any(hit.reference == journal.old_fact_reference for hit in lexical_hits.hits)


def test_unavailable_semantic_fallback_still_serves_lexical_after_projection_loss(
    tmp_path: Path,
) -> None:
    journal = _build_scale_journal(tmp_path, filler_events=1500)
    journal.semantic.db_path.unlink()

    # An index file missing (not merely absent from disk yet) is exactly the
    # unavailable-projection case automatic retrieval must degrade around.
    result = journal.service().retrieve(
        HistoryRetrievalQuery(IDENTIFIER_QUERY, limit=5)
    )

    assert any(
        candidate.reference == journal.identifier_fact_reference
        for candidate in result.candidates
    )


# --- deletion cannot be resurrected by rebuild ------------------------------


def test_deletion_prevents_rebuild_resurrection_across_corpus_lexical_semantic(
    tmp_path: Path,
) -> None:
    journal = _build_scale_journal(tmp_path, filler_events=1500)
    victim_session = journal.old_fact_reference.session_id

    before = journal.service().retrieve(
        HistoryRetrievalQuery(PARAPHRASE_QUERY, limit=5)
    )
    assert any(
        candidate.reference == journal.old_fact_reference
        for candidate in before.candidates
    )

    journal.store.delete_session(victim_session)
    journal.corpus.delete_session_projection(victim_session)
    journal.semantic.delete_session_projection(victim_session)

    # Direct semantic-index check, deliberately not routed through
    # HistoryRetrievalService: its event-candidate hydration reads back
    # through the *corpus* table (already correctly deleted above), so a
    # stale row left behind purely in SemanticPassageIndex would be silently
    # dropped at hydration and never fail a retrieval-service-only
    # assertion. Query the semantic index's own contents directly instead.
    assert not any(
        p.reference.session_id == victim_session
        for p in journal.semantic.list_passages()
    )

    # A subsequent crash-recovery full rebuild has no raw data left to
    # resurrect the deleted session from.
    journal.corpus.rebuild()
    journal.semantic.rebuild()

    remaining_sessions = {
        summary.session_id for summary in journal.store.list_sessions()
    }
    assert victim_session not in remaining_sessions
    assert not any(
        p.reference.session_id == victim_session
        for p in journal.semantic.list_passages()
    )

    after = journal.service().retrieve(HistoryRetrievalQuery(PARAPHRASE_QUERY, limit=5))
    assert not any(
        candidate.reference == journal.old_fact_reference
        for candidate in after.candidates
    )
    lexical_hits = journal.corpus.search(HistorySearchRequest(query="Браво"))
    assert not any(
        hit.reference.session_id == victim_session for hit in lexical_hits.hits
    )


# --- retrieval never mutates raw journal or curated memory -----------------


async def test_retrieval_and_rebuild_never_modify_raw_journal_bytes(
    tmp_path: Path,
) -> None:
    journal = _build_scale_journal(tmp_path, filler_events=800)
    journal_root = tmp_path / "journal"
    snapshot = {
        path: path.read_bytes() for path in sorted(journal_root.rglob("*.jsonl"))
    }
    assert snapshot, "expected at least one raw session events.jsonl file"

    orchestrator, _backend, _recorder = _drive_turn(journal.service(), PARAPHRASE_QUERY)
    await orchestrator.submit_text_input(PARAPHRASE_QUERY)
    journal.service().retrieve(HistoryRetrievalQuery(IDENTIFIER_QUERY, limit=5))
    journal.corpus.rebuild()
    journal.semantic.rebuild()

    after = {path: path.read_bytes() for path in sorted(journal_root.rglob("*.jsonl"))}
    assert after == snapshot


# --- latency characteristic: known limit, not catastrophic -----------------


async def test_semantic_scan_latency_stays_within_a_generous_regression_guard(
    tmp_path: Path,
) -> None:
    """Records the measured, owner-accepted latency characteristic of the
    unbounded brute-force cosine scan (PROJECT.md, task v1.8.0-29 entry;
    tasks/bug_reports/2026-08-02-semantic-hot-path-scan-remains-unbounded.md):
    per-turn retrieval time grows with corpus size because
    ``SemanticPassageIndex.query()`` has no candidate cap. This is accepted
    for the personal-journal scale this project targets, not fixed here
    (fixing it is out of card 29's scope: no backend/feature change). This
    test is a regression guard against a *worse* (e.g. quadratic or
    unbounded-without-limit) blowup, not an assertion that growth is absent.
    """

    elapsed_ms_by_size: dict[int, int] = {}
    for filler_events in (500, 4000, 16000):
        journal = _build_scale_journal(
            tmp_path / f"latency-{filler_events}", filler_events=filler_events
        )
        orchestrator, _backend, recorder = _drive_turn(journal.service(), NEUTRAL_QUERY)

        await orchestrator.submit_text_input(NEUTRAL_QUERY)

        [event] = recorder.events
        assert event.prompt_budget is not None
        elapsed_ms_by_size[filler_events] = event.prompt_budget["retrieval_elapsed_ms"]

    # Generous ceiling at the largest tested size: several times the actually
    # measured cost (well under a second at this fixture's dimension), so
    # this fails loudly on a real algorithmic regression (e.g. an accidental
    # quadratic pass) while tolerating normal machine variance.
    assert elapsed_ms_by_size[16000] < 5000, (
        "semantic retrieval latency at 16000 events grew far beyond the "
        f"measured baseline: {elapsed_ms_by_size}"
    )
