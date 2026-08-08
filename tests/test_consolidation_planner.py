from __future__ import annotations

from pathlib import Path

from jarvis.journal.annotation import (
    AnnotationOverlayRepository,
    AnnotationSource,
    AnnotationStatus,
    AnnotationTarget,
)
from jarvis.journal.consolidation import (
    ConsolidationPlanner,
    ConsolidationPlanStatus,
    JournalStoreConsolidationSource,
    MediaAction,
    MediaActionReason,
)
from jarvis.journal.events import JournalEvent, JournalEventRef
from jarvis.journal.lifecycle import JournalStoreEventReferenceResolver
from jarvis.journal.store import JournalStore
from jarvis.journal.transcript import (
    TranscriptOverlayRepository,
    TranscriptSource,
)

_SESSION = "20260801-120000-ab12"
_TIMESTAMP = "2026-08-01T12:00:00+00:00"


def _event(*media: str, role: str = "user", source: str = "voice") -> JournalEvent:
    return JournalEvent(
        session_id=_SESSION,
        timestamp=_TIMESTAMP,
        source=source,
        role=role,
        text="",
        media=tuple(media),
        transcript=None,
        metadata={},
    )


def _planner(
    root: Path,
) -> tuple[ConsolidationPlanner, JournalStore, TranscriptOverlayRepository]:
    store = JournalStore(root)
    resolver = JournalStoreEventReferenceResolver(store)
    transcripts = TranscriptOverlayRepository(root, resolver)
    annotations = AnnotationOverlayRepository(root, resolver)
    planner = ConsolidationPlanner(
        JournalStoreConsolidationSource(store), transcripts, annotations
    )
    return planner, store, transcripts


def test_unknown_session_is_reported_and_nothing_is_read(tmp_path: Path) -> None:
    planner, _store, _transcripts = _planner(tmp_path)
    plan = planner.plan_far_consolidation("does-not-exist", active_session_id=None)
    assert plan.status is ConsolidationPlanStatus.UNKNOWN_SESSION
    assert plan.media_items == ()
    assert plan.raw_text_range is None
    assert not plan.is_actionable


def test_active_session_is_excluded_without_reading_its_events(tmp_path: Path) -> None:
    planner, store, _transcripts = _planner(tmp_path)
    store.write_media(_SESSION, "utterance-0001.wav", b"RIFFfakewav")
    store.append(_event("utterance-0001.wav"))

    plan = planner.plan_far_consolidation(_SESSION, active_session_id=_SESSION)

    assert plan.status is ConsolidationPlanStatus.ACTIVE_SESSION
    assert plan.media_items == ()
    assert plan.raw_text_range is None
    assert not plan.is_actionable


def test_transcribed_audio_is_planned_for_removal(tmp_path: Path) -> None:
    planner, store, transcripts = _planner(tmp_path)
    store.write_media(_SESSION, "utterance-0001.wav", b"RIFFfakewav")
    reference = store.append(_event("utterance-0001.wav"))
    transcripts.upsert_transcript(reference, "привет", TranscriptSource.GENERATED)

    plan = planner.plan_far_consolidation(_SESSION, active_session_id=None)

    assert plan.status is ConsolidationPlanStatus.PLANNED
    assert len(plan.media_items) == 1
    item = plan.media_items[0]
    assert item.reference == reference
    assert item.media == "utterance-0001.wav"
    assert item.action is MediaAction.REMOVE
    assert item.reason is MediaActionReason.TRANSCRIBED
    assert plan.removable_media == (item,)


def test_untranscribed_audio_is_kept(tmp_path: Path) -> None:
    planner, store, _transcripts = _planner(tmp_path)
    store.write_media(_SESSION, "utterance-0001.wav", b"RIFFfakewav")
    store.append(_event("utterance-0001.wav"))

    plan = planner.plan_far_consolidation(_SESSION, active_session_id=None)

    assert len(plan.media_items) == 1
    item = plan.media_items[0]
    assert item.action is MediaAction.KEEP
    assert item.reason is MediaActionReason.NO_TRANSCRIPT
    assert plan.removable_media == ()


def test_already_absent_media_is_kept_even_with_a_transcript(tmp_path: Path) -> None:
    """A file the operator (or a prior run) already removed must not be
    reported as an actionable REMOVE candidate again - existence is checked
    before the transcript gate, not after."""
    planner, store, transcripts = _planner(tmp_path)
    reference = store.append(_event("utterance-missing.wav"))
    transcripts.upsert_transcript(reference, "привет", TranscriptSource.GENERATED)

    plan = planner.plan_far_consolidation(_SESSION, active_session_id=None)

    item = plan.media_items[0]
    assert item.action is MediaAction.KEEP
    assert item.reason is MediaActionReason.ALREADY_ABSENT


def test_non_audio_media_is_never_a_plan_candidate(tmp_path: Path) -> None:
    planner, store, transcripts = _planner(tmp_path)
    store.write_media(_SESSION, "utterance-0001.wav", b"RIFFfakewav")
    store.write_media(_SESSION, "shot-0001.png", b"fakepng")
    reference = store.append(_event("utterance-0001.wav", "shot-0001.png"))
    transcripts.upsert_transcript(reference, "привет", TranscriptSource.GENERATED)

    plan = planner.plan_far_consolidation(_SESSION, active_session_id=None)

    assert len(plan.media_items) == 1
    assert plan.media_items[0].media == "utterance-0001.wav"


def test_plan_reports_raw_text_event_count(tmp_path: Path) -> None:
    planner, store, _transcripts = _planner(tmp_path)
    store.append(_event(role="user", source="text"))
    store.append(_event(role="assistant", source="text"))
    store.append(_event(role="user", source="text"))

    plan = planner.plan_far_consolidation(_SESSION, active_session_id=None)

    assert plan.event_count == 3


def test_plan_reports_a_verifiable_raw_text_range_not_just_a_count(
    tmp_path: Path,
) -> None:
    """A bare count cannot be independently checked. raw_text_range is a
    provenance-bearing pointer (first/last JournalEventRef) an auditor
    resolves against the raw journal, not the derived corpus, to see the
    exact preserved text."""
    planner, store, _transcripts = _planner(tmp_path)
    store.append(_event(role="user", source="text"))
    store.append(_event(role="assistant", source="text"))
    store.append(_event(role="user", source="text"))

    plan = planner.plan_far_consolidation(_SESSION, active_session_id=None)

    assert plan.raw_text_range is not None
    assert plan.raw_text_range.start == JournalEventRef(_SESSION, 0)
    assert plan.raw_text_range.end == JournalEventRef(_SESSION, 2)
    assert plan.raw_text_range.event_count == plan.event_count == 3


def test_raw_text_range_resolves_against_the_raw_journal(tmp_path: Path) -> None:
    """The documented resolution path: slice JournalStore.read_session by
    position, not HistoryCorpusRepository.read_events (a derived, rebuildable
    projection that can lag the raw journal this planner itself reads)."""
    planner, store, _transcripts = _planner(tmp_path)
    store.append(_event(role="user", source="text"))
    store.append(_event(role="assistant", source="text"))
    store.append(_event(role="user", source="text"))

    plan = planner.plan_far_consolidation(_SESSION, active_session_id=None)
    assert plan.raw_text_range is not None

    replay = store.read_session(_SESSION)
    start_pos = plan.raw_text_range.start.event_position
    end_pos = plan.raw_text_range.end.event_position
    resolved = replay.records[start_pos : end_pos + 1]
    assert len(resolved) == plan.raw_text_range.event_count
    assert [r.reference for r in resolved] == [
        JournalEventRef(_SESSION, 0),
        JournalEventRef(_SESSION, 1),
        JournalEventRef(_SESSION, 2),
    ]


def test_plan_reports_annotation_count_without_touching_annotations(
    tmp_path: Path,
) -> None:
    planner, store, _transcripts = _planner(tmp_path)
    store.append(_event())
    resolver = JournalStoreEventReferenceResolver(store)
    annotations = AnnotationOverlayRepository(tmp_path, resolver)
    annotations.add_annotation(
        AnnotationTarget(_SESSION, None, None),
        "summary",
        "jarvis",
        AnnotationSource.GENERATED,
        AnnotationStatus.ACTIVE,
    )

    plan = planner.plan_far_consolidation(_SESSION, active_session_id=None)

    assert plan.annotation_count == 1
    assert plan.projection_updates_required == ()
    # Still exactly one annotation row: planning must not add, edit, or drop it.
    assert len(annotations.read_session_annotations(_SESSION)) == 1


def test_plan_is_deterministic_for_fixed_session_state(tmp_path: Path) -> None:
    planner, store, transcripts = _planner(tmp_path)
    store.write_media(_SESSION, "utterance-0001.wav", b"RIFFfakewav")
    reference = store.append(_event("utterance-0001.wav"))
    transcripts.upsert_transcript(reference, "привет", TranscriptSource.GENERATED)

    first = planner.plan_far_consolidation(_SESSION, active_session_id=None)
    second = planner.plan_far_consolidation(_SESSION, active_session_id=None)

    assert first == second


def test_planning_never_mutates_the_raw_journal_or_media_files(tmp_path: Path) -> None:
    planner, store, transcripts = _planner(tmp_path)
    store.write_media(_SESSION, "utterance-0001.wav", b"RIFFfakewav")
    reference = store.append(_event("utterance-0001.wav"))
    transcripts.upsert_transcript(reference, "привет", TranscriptSource.GENERATED)

    events_file = tmp_path / _SESSION / "events.jsonl"
    media_file = tmp_path / _SESSION / "utterance-0001.wav"
    events_before = events_file.read_bytes()
    media_before = media_file.read_bytes()

    planner.plan_far_consolidation(_SESSION, active_session_id=None)

    assert events_file.read_bytes() == events_before
    assert media_file.read_bytes() == media_before
