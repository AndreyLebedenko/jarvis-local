"""Typed provenance vocabulary for every text-bearing search surface.

One descriptor answers, for any retrievable passage: what kind of text this
is, which search surfaces may see it, what it points at, and whether it is
the canonical turn text or derived from it. The scattered signals this
centralizes (``HistoryCorpusEvent.text_is_transcript``, ``kind`` +
``AnnotationCandidateIdentity`` on a retrieval candidate, the out-of-band
``metadata["spoken_derivative"]``) remain the *inputs*; consumers read
provenance through this module instead of re-interpreting them (story-v1.9.1
task 1).

The eligibility contract encoded in this module is the single source of
truth: raw events, transcripts, and annotations are eligible for automatic
retrieval, model-facing search, and Journal UI search; the spoken derivative
is locator-only and must never enter model memory or automatic retrieval.

This module is pure: no sqlite, no filesystem, no network, no event bus.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from jarvis.journal.annotation import AnnotationTarget
from jarvis.journal.events import JournalEventRef

if TYPE_CHECKING:
    from jarvis.journal.corpus import HistoryCorpusEvent
    from jarvis.journal.retrieval import AnnotationCandidateIdentity


class ProvenanceSourceKind(Enum):
    """What a retrievable passage's text *is*.

    ``eligibility`` is the surface contract: encode here once, re-derive at
    no call site (task-v1.9.1-1).
    """

    RAW_EVENT = "raw_event"
    TRANSCRIPT = "transcript"
    ANNOTATION = "annotation"
    SPOKEN_DERIVATIVE = "spoken_derivative"

    @property
    def eligibility(self) -> frozenset[ProvenanceEligibility]:
        return _ELIGIBILITY_BY_SOURCE_KIND[self]


class ProvenanceEligibility(Enum):
    """The four search surfaces a source may be eligible for.

    ``AUTO_RETRIEVAL`` is the hybrid corpus feed assembled per turn,
    ``MODEL_SEARCH`` is the explicit ``search_history`` tool, ``JOURNAL_UI``
    is the user-facing Journal search, and ``LOCATOR_ONLY`` is a
    heard-phrase index whose hits return the owning event's canonical text.
    """

    AUTO_RETRIEVAL = "auto_retrieval"
    MODEL_SEARCH = "model_search"
    JOURNAL_UI = "journal_ui"
    LOCATOR_ONLY = "locator_only"


_CANONICAL_ELIGIBILITY = frozenset(
    {
        ProvenanceEligibility.AUTO_RETRIEVAL,
        ProvenanceEligibility.MODEL_SEARCH,
        ProvenanceEligibility.JOURNAL_UI,
    }
)
_LOCATOR_ELIGIBILITY = frozenset({ProvenanceEligibility.LOCATOR_ONLY})


@dataclass(frozen=True)
class ProvenanceTarget:
    """The anchor a passage points at.

    Exactly one of ``event_ref`` / ``annotation`` is set: event-anchored
    surfaces (raw event, transcript, spoken derivative) carry the owning
    ``JournalEventRef``; annotations carry their ``AnnotationTarget``-shaped
    whole-session or range anchor. Both set or both unset is a construction
    error. The whole-session vs range *shape* itself is the annotation
    overlay store's contract: this module carries the anchor faithfully and
    relies on its producer to have validated the positions.
    """

    event_ref: JournalEventRef | None = None
    annotation: AnnotationTarget | None = None

    def __post_init__(self) -> None:
        if (self.event_ref is None) == (self.annotation is None):
            raise ValueError("exactly one of event_ref or annotation must be set")


@dataclass(frozen=True)
class ProvenanceDescriptor:
    """The one typed provenance record for a retrievable passage.

    ``is_canonical`` distinguishes text that IS the canonical turn (a raw
    event) from text derived from or attached to it (transcript, annotation,
    spoken derivative). ``eligibility`` always equals
    ``source_kind.eligibility`` - the contract stays encoded in one place;
    a mismatching pair is a construction error. Field set is limited to
    what tasks 2-4 consume.
    """

    source_kind: ProvenanceSourceKind
    eligibility: frozenset[ProvenanceEligibility]
    target: ProvenanceTarget
    is_canonical: bool

    def __post_init__(self) -> None:
        if self.eligibility != self.source_kind.eligibility:
            raise ValueError(
                "eligibility must equal source_kind.eligibility; the "
                "eligibility contract is encoded only on ProvenanceSourceKind"
            )


def provenance_descriptor_from_corpus_event(
    event: HistoryCorpusEvent,
) -> ProvenanceDescriptor:
    """Map a corpus event to its descriptor.

    ``text_is_transcript`` decides raw vs transcript: the corpus indexes
    ``effective_text`` only when the raw text is empty, so a transcript-backed
    event's indexed text is derived, never canonical.
    """

    is_transcript = event.text_is_transcript
    source_kind = (
        ProvenanceSourceKind.TRANSCRIPT
        if is_transcript
        else ProvenanceSourceKind.RAW_EVENT
    )
    return ProvenanceDescriptor(
        source_kind=source_kind,
        eligibility=source_kind.eligibility,
        target=ProvenanceTarget(event_ref=event.reference),
        is_canonical=not is_transcript,
    )


def provenance_descriptor_from_annotation_identity(
    identity: AnnotationCandidateIdentity,
) -> ProvenanceDescriptor:
    """Map a retrieval annotation identity to its descriptor.

    The session/range shape is carried faithfully: both positions set for an
    inclusive range, both ``None`` for a whole-session annotation.
    """

    return ProvenanceDescriptor(
        source_kind=ProvenanceSourceKind.ANNOTATION,
        eligibility=ProvenanceSourceKind.ANNOTATION.eligibility,
        target=ProvenanceTarget(
            annotation=AnnotationTarget(
                session_id=identity.session_id,
                start_position=identity.start_position,
                end_position=identity.end_position,
            )
        ),
        is_canonical=False,
    )


def spoken_derivative_provenance_descriptor(
    reference: JournalEventRef,
) -> ProvenanceDescriptor:
    """Produce the spoken-derivative descriptor for an owning event.

    Defined here so the vocabulary is complete for tasks 3-4 (the locator
    index and its query path), even though task 1 has no runtime caller.
    The derivative is locator-only: never automatic retrieval, never model
    memory, never blended into ranked canonical candidates.
    """

    return ProvenanceDescriptor(
        source_kind=ProvenanceSourceKind.SPOKEN_DERIVATIVE,
        eligibility=ProvenanceSourceKind.SPOKEN_DERIVATIVE.eligibility,
        target=ProvenanceTarget(event_ref=reference),
        is_canonical=False,
    )


# The eligibility contract (task-v1.9.1-1 card): encode once, re-derive at no
# call site. Consulted only through ProvenanceSourceKind.eligibility.
_ELIGIBILITY_BY_SOURCE_KIND: dict[
    ProvenanceSourceKind, frozenset[ProvenanceEligibility]
] = {
    ProvenanceSourceKind.RAW_EVENT: _CANONICAL_ELIGIBILITY,
    ProvenanceSourceKind.TRANSCRIPT: _CANONICAL_ELIGIBILITY,
    ProvenanceSourceKind.ANNOTATION: _CANONICAL_ELIGIBILITY,
    ProvenanceSourceKind.SPOKEN_DERIVATIVE: _LOCATOR_ELIGIBILITY,
}
