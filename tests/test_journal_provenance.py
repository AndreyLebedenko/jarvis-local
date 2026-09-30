from __future__ import annotations

import pytest

from jarvis.journal.annotation import AnnotationTarget
from jarvis.journal.corpus import HistoryCorpusEvent
from jarvis.journal.events import JournalEventRef
from jarvis.journal.external_canvas import MCP_CANVAS_SOURCE
from jarvis.journal.provenance import (
    ProvenanceDescriptor,
    ProvenanceEligibility,
    ProvenanceSourceKind,
    ProvenanceTarget,
    provenance_descriptor_from_annotation_identity,
    provenance_descriptor_from_corpus_event,
    spoken_derivative_provenance_descriptor,
)
from jarvis.journal.retrieval import AnnotationCandidateIdentity

# The eligibility contract is fixed by the task-v1.9.1-1 card. These expected
# sets are the single place the mapping is asserted against; the exhaustive
# membership test below pins every enum member to exactly one of them.
_CANONICAL_ELIGIBILITY = frozenset(
    {
        ProvenanceEligibility.AUTO_RETRIEVAL,
        ProvenanceEligibility.MODEL_SEARCH,
        ProvenanceEligibility.JOURNAL_UI,
    }
)
_LOCATOR_ELIGIBILITY = frozenset({ProvenanceEligibility.LOCATOR_ONLY})
_EXTERNAL_ELIGIBILITY = frozenset(
    {ProvenanceEligibility.MODEL_SEARCH, ProvenanceEligibility.JOURNAL_UI}
)


def _ref(
    position: int = 0, session_id: str = "20260801-120000-ab12"
) -> JournalEventRef:
    return JournalEventRef(session_id, position)


class TestEligibilityContract:
    def test_canonical_surface_kinds_map_to_auto_model_and_ui(self) -> None:
        for kind in (
            ProvenanceSourceKind.RAW_EVENT,
            ProvenanceSourceKind.TRANSCRIPT,
            ProvenanceSourceKind.ANNOTATION,
        ):
            assert kind.eligibility == _CANONICAL_ELIGIBILITY

    def test_spoken_derivative_is_locator_only(self) -> None:
        assert (
            ProvenanceSourceKind.SPOKEN_DERIVATIVE.eligibility == _LOCATOR_ELIGIBILITY
        )

    def test_mapping_is_exhaustive_over_all_source_kinds(self) -> None:
        assert {kind: kind.eligibility for kind in ProvenanceSourceKind} == {
            ProvenanceSourceKind.RAW_EVENT: _CANONICAL_ELIGIBILITY,
            ProvenanceSourceKind.TRANSCRIPT: _CANONICAL_ELIGIBILITY,
            ProvenanceSourceKind.ANNOTATION: _CANONICAL_ELIGIBILITY,
            ProvenanceSourceKind.SPOKEN_DERIVATIVE: _LOCATOR_ELIGIBILITY,
            ProvenanceSourceKind.EXTERNAL_CANVAS: _EXTERNAL_ELIGIBILITY,
            ProvenanceSourceKind.EXTERNAL_ANNOTATION: _EXTERNAL_ELIGIBILITY,
        }

    def test_external_kinds_are_model_search_and_journal_ui_only(self) -> None:
        for kind in (
            ProvenanceSourceKind.EXTERNAL_CANVAS,
            ProvenanceSourceKind.EXTERNAL_ANNOTATION,
        ):
            assert kind.eligibility == _EXTERNAL_ELIGIBILITY

    def test_is_external_marks_exactly_the_two_external_kinds(self) -> None:
        assert {kind for kind in ProvenanceSourceKind if kind.is_external} == {
            ProvenanceSourceKind.EXTERNAL_CANVAS,
            ProvenanceSourceKind.EXTERNAL_ANNOTATION,
        }

    def test_external_kinds_are_not_eligible_for_auto_retrieval(self) -> None:
        for kind in (
            ProvenanceSourceKind.EXTERNAL_CANVAS,
            ProvenanceSourceKind.EXTERNAL_ANNOTATION,
        ):
            assert ProvenanceEligibility.AUTO_RETRIEVAL not in kind.eligibility


class TestProvenanceTarget:
    def test_event_target_holds_owning_event_ref(self) -> None:
        ref = _ref(7)
        target = ProvenanceTarget(event_ref=ref)
        assert target.event_ref == ref
        assert target.annotation is None

    def test_annotation_target_holds_session_anchor(self) -> None:
        annotation_target = AnnotationTarget("20260802-090000-cd34", 3, 9)
        target = ProvenanceTarget(annotation=annotation_target)
        assert target.event_ref is None
        assert target.annotation == annotation_target

    def test_construction_requires_exactly_one_anchor(self) -> None:
        annotation_target = AnnotationTarget("20260802-090000-cd34")
        with pytest.raises(ValueError):
            ProvenanceTarget()
        with pytest.raises(ValueError):
            ProvenanceTarget(event_ref=_ref(), annotation=annotation_target)


class TestProvenanceDescriptor:
    def test_descriptor_is_frozen(self) -> None:
        descriptor = ProvenanceDescriptor(
            source_kind=ProvenanceSourceKind.RAW_EVENT,
            eligibility=_CANONICAL_ELIGIBILITY,
            target=ProvenanceTarget(event_ref=_ref()),
            is_canonical=True,
        )
        with pytest.raises(AttributeError):
            descriptor.source_kind = ProvenanceSourceKind.TRANSCRIPT  # type: ignore[misc]

    def test_mismatched_eligibility_is_a_construction_error(self) -> None:
        with pytest.raises(ValueError):
            ProvenanceDescriptor(
                source_kind=ProvenanceSourceKind.RAW_EVENT,
                eligibility=_LOCATOR_ELIGIBILITY,
                target=ProvenanceTarget(event_ref=_ref()),
                is_canonical=True,
            )


class TestCorpusEventMapping:
    def test_raw_text_event_maps_to_raw_event_canonical(self) -> None:
        reference = _ref(2)
        event = _corpus_event(reference, text="plain answer", effective_text="")
        descriptor = provenance_descriptor_from_corpus_event(event)
        assert descriptor.source_kind is ProvenanceSourceKind.RAW_EVENT
        assert descriptor.is_canonical is True
        assert descriptor.eligibility == _CANONICAL_ELIGIBILITY
        assert descriptor.target.event_ref == reference

    def test_transcript_backed_event_maps_to_transcript_non_canonical(self) -> None:
        reference = _ref(4)
        event = _corpus_event(reference, text="", effective_text="transcribed question")
        descriptor = provenance_descriptor_from_corpus_event(event)
        assert descriptor.source_kind is ProvenanceSourceKind.TRANSCRIPT
        assert descriptor.is_canonical is False
        assert descriptor.eligibility == _CANONICAL_ELIGIBILITY
        assert descriptor.target.event_ref == reference

    def test_mcp_canvas_event_maps_to_external_canvas_canonical(self) -> None:
        reference = _ref(6)
        event = _corpus_event(
            reference,
            text="canvas from another assistant",
            effective_text="",
            role="assistant",
            source=MCP_CANVAS_SOURCE,
        )
        descriptor = provenance_descriptor_from_corpus_event(event)
        assert descriptor.source_kind is ProvenanceSourceKind.EXTERNAL_CANVAS
        assert descriptor.is_canonical is True
        assert descriptor.eligibility == _EXTERNAL_ELIGIBILITY
        assert descriptor.target.event_ref == reference

    def test_ordinary_assistant_event_is_not_external(self) -> None:
        event = _corpus_event(
            _ref(1),
            text="own answer",
            effective_text="",
            role="assistant",
            source="assistant",
        )
        descriptor = provenance_descriptor_from_corpus_event(event)
        assert descriptor.source_kind is ProvenanceSourceKind.RAW_EVENT


class TestAnnotationIdentityMapping:
    def test_whole_session_annotation_maps_with_target_faithfully(self) -> None:
        identity = AnnotationCandidateIdentity(
            annotation_id="a1", session_id="20260802-090000-cd34", source="generated"
        )
        descriptor = provenance_descriptor_from_annotation_identity(identity)
        assert descriptor.source_kind is ProvenanceSourceKind.ANNOTATION
        assert descriptor.is_canonical is False
        assert descriptor.eligibility == _CANONICAL_ELIGIBILITY
        assert descriptor.target.event_ref is None
        assert descriptor.target.annotation == AnnotationTarget("20260802-090000-cd34")

    def test_ranged_annotation_maps_positions_faithfully(self) -> None:
        identity = AnnotationCandidateIdentity(
            annotation_id="a2",
            session_id="20260802-090000-cd34",
            source="edited",
            start_position=3,
            end_position=9,
        )
        descriptor = provenance_descriptor_from_annotation_identity(identity)
        assert descriptor.target.event_ref is None
        assert descriptor.target.annotation == AnnotationTarget(
            "20260802-090000-cd34", 3, 9
        )

    def test_annotation_of_an_external_session_maps_to_external_annotation(
        self,
    ) -> None:
        identity = AnnotationCandidateIdentity(
            annotation_id="a3", session_id="20260802-090000-cd34", source="generated"
        )
        descriptor = provenance_descriptor_from_annotation_identity(
            identity, target_is_external=True
        )
        assert descriptor.source_kind is ProvenanceSourceKind.EXTERNAL_ANNOTATION
        assert descriptor.is_canonical is False
        assert descriptor.eligibility == _EXTERNAL_ELIGIBILITY
        assert descriptor.target.annotation == AnnotationTarget("20260802-090000-cd34")


class TestSpokenDerivativeMapping:
    def test_derivative_from_ref_maps_to_locator_only_non_canonical(self) -> None:
        ref = _ref(5)
        descriptor = spoken_derivative_provenance_descriptor(ref)
        assert descriptor.source_kind is ProvenanceSourceKind.SPOKEN_DERIVATIVE
        assert descriptor.is_canonical is False
        assert descriptor.eligibility == _LOCATOR_ELIGIBILITY
        assert descriptor.target.event_ref == ref
        assert descriptor.target.annotation is None


def _corpus_event(
    reference: JournalEventRef,
    *,
    text: str,
    effective_text: str,
    role: str = "user",
    source: str = "voice",
) -> HistoryCorpusEvent:
    return HistoryCorpusEvent(
        reference=reference,
        timestamp="2026-08-01T12:00:00+00:00",
        timestamp_sort=1785576000.0,
        role=role,
        source=source,
        text=text,
        media=(),
        media_count=0,
        transcript=None,
        metadata={},
        effective_text=effective_text,
    )
