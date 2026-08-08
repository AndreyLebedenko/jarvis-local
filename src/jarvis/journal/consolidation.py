"""Historical consolidation planner (task v1.8.0-24).

Calculates a safe far-consolidation plan for one session without performing
any media or data mutation: no raw JSONL rewrite, no file deletion, no
database write. A plan is a deterministic, auditable dry-run report that an
operator - or the task v1.8.0-25 executor - inspects before anything actually
runs. This module only reads the raw journal and the transcript/annotation
overlay stores.

Scope decided with the owner before implementation (2026-08-08): audio is the
only media this planner ever proposes to remove, and the action is binary
KEEP/REMOVE - no compression or bitrate-reduction candidate. Images and other
non-audio media are untouched and never appear in a plan; that stays a
separate, later decision. Removing audio bytes never requires rewriting the
event's `media` list or any derived corpus/lexical/semantic/annotation
projection, because none of those index audio bytes - they index text,
transcripts, and annotations, none of which this planner ever proposes to
change. `projection_updates_required` is still computed explicitly (not
hand-waved) so a future action type that does touch text has a real field to
populate.

Audio is a REMOVE candidate only once a transcript overlay exists for the
exact event that owns it (`TranscriptOverlayRepository.read_transcript`,
keyed by `JournalEventRef`) - the deterministic check the story's transcript
overlay store already provides, so this planner never has to guess transcript
completeness (task 24's stop condition).

A plan must make raw text, transcript, annotation, and retrieval impact
visible (task 24 acceptance criteria), even though this planner never
proposes to change any of them. A bare count is not visibility - it cannot be
independently checked - so raw text is surfaced as `raw_text_range`, a
`RawTextRange` spanning the session's first and last event reference.
`RawTextRange` is defined in this module, not imported from
`jarvis.journal.corpus`, specifically so it is never confused with a
corpus-resolved range: it must be resolved by slicing
`JournalStore.read_session`/`JournalHistoryService.read_session` - the raw
journal this planner itself reads - never through
`HistoryCorpusRepository.read_events`. The corpus is a derived, rebuildable
projection that lags a fresh append or a not-yet-rebuilt startup (like every
other derived projection in this story); resolving through it could show an
auditor stale or incomplete text for a session this planner just read
completely from the authoritative source. `event_count` stays alongside it as
the same quick summary `HistorySessionMetadata` already reports for a
session. `annotation_count` reports how many annotations exist for the
session, per-item `reason` makes each media decision's transcript dependency
explicit, and `projection_updates_required` makes the (currently always
empty) retrieval impact an explicit, computed field rather than an implicit
assumption.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from jarvis.journal.annotation import AnnotationOverlayRepository
from jarvis.journal.events import JournalEvent, JournalEventRef
from jarvis.journal.store import JournalReplay, JournalStore
from jarvis.journal.transcript import TranscriptOverlayRepository
from jarvis.journal.transcription import select_audio_media


class ConsolidationPlanStatus(Enum):
    PLANNED = "planned"
    ACTIVE_SESSION = "active_session"
    UNKNOWN_SESSION = "unknown_session"


class MediaAction(Enum):
    KEEP = "keep"
    REMOVE = "remove"


class MediaActionReason(Enum):
    TRANSCRIBED = "transcribed"
    NO_TRANSCRIPT = "no_transcript"
    ALREADY_ABSENT = "already_absent"


@dataclass(frozen=True)
class MediaPlanItem:
    reference: JournalEventRef
    media: str
    action: MediaAction
    reason: MediaActionReason


@dataclass(frozen=True)
class RawTextRange:
    """A provenance pointer into the raw journal, not the derived corpus.

    Resolve by slicing `JournalStore.read_session`/
    `JournalHistoryService.read_session` between `start` and `end`
    (inclusive). Do not resolve through `HistoryCorpusRepository.read_events`:
    the corpus is a derived, eventually-consistent projection that can lag or
    be stale relative to the raw journal this range was built from.
    """

    start: JournalEventRef
    end: JournalEventRef

    @property
    def event_count(self) -> int:
        return self.end.event_position - self.start.event_position + 1


@dataclass(frozen=True)
class ConsolidationPlan:
    session_id: str
    status: ConsolidationPlanStatus
    event_count: int = 0
    raw_text_range: RawTextRange | None = None
    media_items: tuple[MediaPlanItem, ...] = ()
    annotation_count: int = 0
    projection_updates_required: tuple[str, ...] = ()

    @property
    def is_actionable(self) -> bool:
        return self.status is ConsolidationPlanStatus.PLANNED

    @property
    def removable_media(self) -> tuple[MediaPlanItem, ...]:
        return tuple(
            item for item in self.media_items if item.action is MediaAction.REMOVE
        )


class ConsolidationSource(Protocol):
    """Reads the authoritative raw journal and checks media presence on disk.

    Validation is against the raw journal, never a derived projection, for the
    same reason `TranscriptionEventSource` does this: a not-yet-rebuilt
    projection must never make a real session or a real media file look
    missing.
    """

    def read_session(self, session_id: str) -> JournalReplay: ...

    def media_exists(self, session_id: str, name: str) -> bool: ...


class JournalStoreConsolidationSource:
    """`ConsolidationSource` backed by the append-only journal store.

    Also implements the executor's `ConsolidationExecutionSource` (task
    v1.8.0-25, `consolidation_executor.py`): `media_size`/`delete_media` are
    the only two operations that read a media file's size or remove it from
    disk. One adapter serves both the read-only planner and the executor so
    session/media path resolution is not duplicated between them.
    """

    def __init__(self, store: JournalStore) -> None:
        self._store = store

    def read_session(self, session_id: str) -> JournalReplay:
        return self._store.read_session(session_id)

    def media_exists(self, session_id: str, name: str) -> bool:
        return (self._store.root / session_id / name).exists()

    def media_size(self, session_id: str, name: str) -> int:
        return (self._store.root / session_id / name).stat().st_size

    def delete_media(self, session_id: str, name: str) -> None:
        (self._store.root / session_id / name).unlink()


class ConsolidationPlanner:
    """Pure read-only planning over the raw journal and overlay stores.

    Never mutates a file or a database row - task v1.8.0-24's stop condition.
    Executing a returned plan is task v1.8.0-25's job.
    """

    def __init__(
        self,
        source: ConsolidationSource,
        transcripts: TranscriptOverlayRepository,
        annotations: AnnotationOverlayRepository,
    ) -> None:
        self._source = source
        self._transcripts = transcripts
        self._annotations = annotations

    def plan_far_consolidation(
        self, session_id: str, *, active_session_id: str | None
    ) -> ConsolidationPlan:
        if active_session_id is not None and session_id == active_session_id:
            return ConsolidationPlan(session_id, ConsolidationPlanStatus.ACTIVE_SESSION)

        replay = self._source.read_session(session_id)
        if not replay.records:
            return ConsolidationPlan(
                session_id, ConsolidationPlanStatus.UNKNOWN_SESSION
            )

        media_items = tuple(
            item
            for record in replay.records
            for item in self._plan_event_media(record.reference, record.event)
        )
        annotation_count = len(self._annotations.read_session_annotations(session_id))
        raw_text_range = RawTextRange(
            replay.records[0].reference, replay.records[-1].reference
        )
        return ConsolidationPlan(
            session_id,
            ConsolidationPlanStatus.PLANNED,
            event_count=len(replay.records),
            raw_text_range=raw_text_range,
            media_items=media_items,
            annotation_count=annotation_count,
            projection_updates_required=(),
        )

    def _plan_event_media(
        self, reference: JournalEventRef, event: JournalEvent
    ) -> tuple[MediaPlanItem, ...]:
        items: list[MediaPlanItem] = []
        for name in select_audio_media(event):
            if not self._source.media_exists(event.session_id, name):
                items.append(
                    MediaPlanItem(
                        reference,
                        name,
                        MediaAction.KEEP,
                        MediaActionReason.ALREADY_ABSENT,
                    )
                )
                continue
            if self._transcripts.read_transcript(reference).found:
                items.append(
                    MediaPlanItem(
                        reference,
                        name,
                        MediaAction.REMOVE,
                        MediaActionReason.TRANSCRIBED,
                    )
                )
            else:
                items.append(
                    MediaPlanItem(
                        reference,
                        name,
                        MediaAction.KEEP,
                        MediaActionReason.NO_TRANSCRIPT,
                    )
                )
        return tuple(items)
