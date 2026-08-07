from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path

import pytest

from jarvis.dialog.thinking_mode import ReasoningLevel
from jarvis.journal.annotation import (
    AnnotationOverlayRepository,
    AnnotationSource,
    AnnotationStatus,
    AnnotationTarget,
)
from jarvis.journal.annotation_generator import (
    DEFAULT_ANNOTATION_INSTRUCTION,
    GENERATOR_AUTHOR,
    AnnotationBackendError,
    AnnotationBackendMetadata,
    AnnotationGenerationOutcome,
    AnnotationGenerationService,
    AnnotationMessage,
    AnnotationRun,
    OllamaAnnotationBackend,
    build_annotation_request,
    exceeds_source_bound,
    format_source_block,
)
from jarvis.journal.corpus import (
    HistoryCorpusEvent,
    HistoryEventRange,
    HistoryEventRangeRead,
    HistoryEventRangeStatus,
    HistorySessionMetadata,
    HistorySessionRead,
    HistorySessionReadStatus,
)
from jarvis.journal.events import JournalEventRef, JSONValue

_SESSION = "20260801-120000-ab12"
_TS = "2026-08-01T12:00:00+01:00"
_META = AnnotationBackendMetadata(
    model="fake-model", reasoning="off", options=(("num_ctx", "65536"),)
)


def _event(
    pos: int,
    text: str = "hello world",
    *,
    effective_text: str = "",
    role: str = "user",
    source: str = "voice",
) -> HistoryCorpusEvent:
    return HistoryCorpusEvent(
        reference=JournalEventRef(_SESSION, pos),
        timestamp=_TS,
        timestamp_sort=float(pos),
        role=role,
        source=source,
        text=text,
        media=(),
        media_count=0,
        transcript=None,
        metadata={},
        effective_text=effective_text,
    )


def _range(start: int, end: int, session: str = _SESSION) -> HistoryEventRange:
    return HistoryEventRange(
        JournalEventRef(session, start), JournalEventRef(session, end)
    )


def _target(start: int, end: int, session: str = _SESSION) -> AnnotationTarget:
    return AnnotationTarget(session, start, end)


def _whole(session: str = _SESSION) -> AnnotationTarget:
    return AnnotationTarget(session)


def _found(
    event_range: HistoryEventRange, events: Sequence[HistoryCorpusEvent]
) -> HistoryEventRangeRead:
    return HistoryEventRangeRead(
        HistoryEventRangeStatus.FOUND,
        requested_range=event_range,
        events=tuple(events),
        requested_count=event_range.requested_count,
    )


def _session_read(first: int, last: int, session: str = _SESSION) -> HistorySessionRead:
    return HistorySessionRead(
        HistorySessionReadStatus.FOUND,
        HistorySessionMetadata(
            session_id=session,
            first_timestamp=_TS,
            last_timestamp=_TS,
            first_event_position=first,
            last_event_position=last,
            event_count=last - first + 1,
        ),
    )


class _FakeSourceReader:
    def __init__(
        self,
        read: HistoryEventRangeRead,
        session_read: HistorySessionRead | None = None,
    ) -> None:
        self._read = read
        self._session_read = session_read or HistorySessionRead(
            HistorySessionReadStatus.UNKNOWN_SESSION
        )
        self.range_calls: list[HistoryEventRange] = []
        self.session_calls: list[str] = []

    def read_range(self, event_range: HistoryEventRange) -> HistoryEventRangeRead:
        self.range_calls.append(event_range)
        return self._read

    def read_session(self, session_id: str) -> HistorySessionRead:
        self.session_calls.append(session_id)
        return self._session_read


class _FakeBackend:
    def __init__(
        self,
        text: str = "a concise summary",
        error: Exception | None = None,
        metadata: AnnotationBackendMetadata = _META,
    ) -> None:
        self.text = text
        self.error = error
        self.metadata = metadata
        self.calls: list[tuple[AnnotationMessage, ...]] = []
        self.reasonings: list[ReasoningLevel] = []

    async def run_annotation(
        self,
        messages: Sequence[AnnotationMessage],
        reasoning: ReasoningLevel = ReasoningLevel.OFF,
    ) -> AnnotationRun:
        self.calls.append(tuple(messages))
        self.reasonings.append(reasoning)
        if self.error is not None:
            raise self.error
        return AnnotationRun(self.text, self.metadata)


class _AllExist:
    def event_exists(self, reference: JournalEventRef) -> bool:
        return True


class _NoneExist:
    def event_exists(self, reference: JournalEventRef) -> bool:
        return False


def _repo(tmp_path: Path, *, exists: bool = True) -> AnnotationOverlayRepository:
    resolver = _AllExist() if exists else _NoneExist()
    return AnnotationOverlayRepository(tmp_path / "derived", resolver)


def _service(
    reader: _FakeSourceReader,
    backend: _FakeBackend,
    repo: AnnotationOverlayRepository,
    **kwargs: object,
) -> AnnotationGenerationService:
    return AnnotationGenerationService(reader, backend, repo, **kwargs)


class TestPromptConstruction:
    def test_request_cites_every_event_and_instruction(self) -> None:
        event_range = _range(0, 1)
        events = [_event(0, "first message"), _event(1, "second message")]
        request = build_annotation_request(
            event_range, events, instruction="сделай саммари"
        )
        assert request.event_range == event_range
        assert request.source_references == (
            JournalEventRef(_SESSION, 0),
            JournalEventRef(_SESSION, 1),
        )
        assert request.source_char_count == len("first message") + len("second message")
        assert len(request.messages) == 1
        content = request.messages[0].content
        assert request.messages[0].role == "user"
        assert content.startswith("сделай саммари")
        assert "first message" in content
        assert "second message" in content
        assert "[#0]" in content and "[#1]" in content

    def test_format_source_block_marks_transcript(self) -> None:
        block = format_source_block(
            _SESSION,
            [_event(0, text="", effective_text="spoken words")],
        )
        assert f"session {_SESSION}" in block
        assert "[#0]" in block
        assert "(transcript)" in block
        assert "spoken words" in block

    def test_default_instruction_is_russian_with_attribution(self) -> None:
        text = DEFAULT_ANNOTATION_INSTRUCTION
        assert text.strip()
        # Russian framing (so a Russian conversation is summarized in Russian)
        assert any("Ѐ" <= c <= "ӿ" for c in text)
        # Attribution clause (load-bearing per the 2026-08-07 A/B; see module)
        assert "ассистент" in text.lower()


class TestSourceBounding:
    def test_within_bound_is_not_exceeded(self) -> None:
        assert not exceeds_source_bound(_range(0, 2), 3)

    def test_over_bound_is_exceeded(self) -> None:
        assert exceeds_source_bound(_range(0, 3), 3)

    def test_malformed_range_is_not_too_large(self) -> None:
        assert not exceeds_source_bound(_range(3, 0), 3)  # requested_count == 0


class TestGenerateHappyPath:
    async def test_generates_and_persists_annotation(self, tmp_path: Path) -> None:
        reader = _FakeSourceReader(
            _found(_range(0, 2), [_event(0), _event(1), _event(2)])
        )
        backend = _FakeBackend(text="  summary of turns  ")
        repo = _repo(tmp_path)
        service = _service(reader, backend, repo)

        result = await service.generate_annotation(_target(0, 2))

        assert result.outcome is AnnotationGenerationOutcome.GENERATED
        assert result.annotation == "summary of turns"
        assert result.annotation_id is not None
        assert result.source_references == (
            JournalEventRef(_SESSION, 0),
            JournalEventRef(_SESSION, 1),
            JournalEventRef(_SESSION, 2),
        )

        stored = repo.read_annotation(result.annotation_id).annotation
        assert stored is not None
        assert stored.text == "summary of turns"
        assert stored.author == GENERATOR_AUTHOR
        assert stored.source is AnnotationSource.GENERATED
        assert stored.status is AnnotationStatus.ACTIVE
        assert stored.target.start_position == 0
        assert stored.target.end_position == 2

    async def test_whole_session_reads_full_span_and_stores_whole_session(
        self, tmp_path: Path
    ) -> None:
        reader = _FakeSourceReader(
            _found(_range(0, 2), [_event(0), _event(1), _event(2)]),
            session_read=_session_read(0, 2),
        )
        backend = _FakeBackend(text="session summary")
        repo = _repo(tmp_path)
        service = _service(reader, backend, repo)

        result = await service.generate_annotation(_whole())

        assert result.outcome is AnnotationGenerationOutcome.GENERATED
        assert reader.session_calls == [_SESSION]
        assert reader.range_calls == [_range(0, 2)]  # resolved from session bounds
        assert len(result.source_references) == 3

        stored = repo.read_annotation(result.annotation_id or "").annotation
        assert stored is not None
        assert stored.target.is_whole_session
        assert stored.target.start_position is None
        assert stored.target.end_position is None

    async def test_whole_session_unknown_session(self, tmp_path: Path) -> None:
        # No session_read configured -> UNKNOWN_SESSION -> UNKNOWN_RANGE.
        reader = _FakeSourceReader(_found(_range(0, 0), [_event(0)]))
        backend = _FakeBackend()
        service = _service(reader, backend, _repo(tmp_path))

        result = await service.generate_annotation(_whole())

        assert result.outcome is AnnotationGenerationOutcome.UNKNOWN_RANGE
        assert result.detail == "unknown_session"
        assert reader.range_calls == []
        assert backend.calls == []

    async def test_stores_model_configuration_metadata(self, tmp_path: Path) -> None:
        reader = _FakeSourceReader(_found(_range(0, 0), [_event(0)]))
        backend = _FakeBackend(
            metadata=AnnotationBackendMetadata(
                model="real-model", reasoning="off", options=(("num_ctx", "65536"),)
            )
        )
        repo = _repo(tmp_path)
        service = _service(reader, backend, repo)

        result = await service.generate_annotation(_target(0, 0))

        assert result.metadata is not None
        assert result.metadata.model == "real-model"
        stored = repo.read_annotation(result.annotation_id or "").annotation
        assert stored is not None
        assert stored.metadata["model"] == "real-model"
        assert stored.metadata["reasoning"] == "off"
        assert stored.metadata["options"] == [["num_ctx", "65536"]]
        assert stored.metadata["source_event_count"] == 1

    async def test_backend_receives_cited_source(self, tmp_path: Path) -> None:
        reader = _FakeSourceReader(
            _found(_range(0, 1), [_event(0, "alpha fact"), _event(1, "beta fact")])
        )
        backend = _FakeBackend()
        service = _service(reader, backend, _repo(tmp_path))

        await service.generate_annotation(_target(0, 1))

        assert len(backend.calls) == 1
        content = backend.calls[0][0].content
        assert "alpha fact" in content
        assert "beta fact" in content

    async def test_configured_reasoning_reaches_backend(self, tmp_path: Path) -> None:
        reader = _FakeSourceReader(_found(_range(0, 0), [_event(0)]))
        backend = _FakeBackend()
        service = _service(
            reader, backend, _repo(tmp_path), reasoning=ReasoningLevel.MEDIUM
        )

        await service.generate_annotation(_target(0, 0))

        assert backend.reasonings == [ReasoningLevel.MEDIUM]
        assert service.reasoning is ReasoningLevel.MEDIUM


class TestBoundsAndRefusals:
    async def test_source_too_large_by_config(self, tmp_path: Path) -> None:
        reader = _FakeSourceReader(_found(_range(0, 5), [_event(0)]))
        repo = _repo(tmp_path)
        service = _service(reader, _FakeBackend(), repo, max_source_events=3)

        result = await service.generate_annotation(_target(0, 5))

        assert result.outcome is AnnotationGenerationOutcome.SOURCE_TOO_LARGE
        assert reader.range_calls == []  # rejected before any range read
        assert repo.count() == 0

    async def test_source_too_large_by_read_status(self, tmp_path: Path) -> None:
        reader = _FakeSourceReader(
            HistoryEventRangeRead(
                HistoryEventRangeStatus.TOO_MANY_EVENTS, requested_range=_range(0, 2)
            )
        )
        service = _service(reader, _FakeBackend(), _repo(tmp_path))

        result = await service.generate_annotation(_target(0, 2))

        assert result.outcome is AnnotationGenerationOutcome.SOURCE_TOO_LARGE

    async def test_unknown_range(self, tmp_path: Path) -> None:
        reader = _FakeSourceReader(
            HistoryEventRangeRead(
                HistoryEventRangeStatus.UNKNOWN_START_REFERENCE,
                requested_range=_range(0, 2),
            )
        )
        service = _service(reader, _FakeBackend(), _repo(tmp_path))

        result = await service.generate_annotation(_target(0, 2))

        assert result.outcome is AnnotationGenerationOutcome.UNKNOWN_RANGE
        assert result.detail == "unknown_start_reference"

    async def test_empty_source(self, tmp_path: Path) -> None:
        reader = _FakeSourceReader(
            _found(_range(0, 1), [_event(0, text=""), _event(1, text="")])
        )
        backend = _FakeBackend()
        service = _service(reader, backend, _repo(tmp_path))

        result = await service.generate_annotation(_target(0, 1))

        assert result.outcome is AnnotationGenerationOutcome.EMPTY_SOURCE
        assert backend.calls == []  # never reached the model

    async def test_source_text_too_large(self, tmp_path: Path) -> None:
        # Two events well within max_source_events but whose combined text
        # exceeds the source-size cap: rejected before the model.
        reader = _FakeSourceReader(
            _found(_range(0, 1), [_event(0, "x" * 40), _event(1, "y" * 40)])
        )
        backend = _FakeBackend()
        repo = _repo(tmp_path)
        service = _service(reader, backend, repo, max_source_chars=50)

        result = await service.generate_annotation(_target(0, 1))

        assert result.outcome is AnnotationGenerationOutcome.SOURCE_TEXT_TOO_LARGE
        assert result.detail == "80 > 50"
        assert backend.calls == []
        assert repo.count() == 0

    async def test_empty_annotation(self, tmp_path: Path) -> None:
        reader = _FakeSourceReader(_found(_range(0, 0), [_event(0)]))
        repo = _repo(tmp_path)
        service = _service(reader, _FakeBackend(text="   \n  "), repo)

        result = await service.generate_annotation(_target(0, 0))

        assert result.outcome is AnnotationGenerationOutcome.EMPTY_ANNOTATION
        assert repo.count() == 0

    async def test_output_too_long(self, tmp_path: Path) -> None:
        reader = _FakeSourceReader(_found(_range(0, 0), [_event(0)]))
        repo = _repo(tmp_path)
        service = _service(
            reader, _FakeBackend(text="x" * 51), repo, max_annotation_chars=50
        )

        result = await service.generate_annotation(_target(0, 0))

        assert result.outcome is AnnotationGenerationOutcome.OUTPUT_TOO_LONG
        assert repo.count() == 0

    async def test_store_rejection_is_reported(self, tmp_path: Path) -> None:
        reader = _FakeSourceReader(_found(_range(0, 0), [_event(0)]))
        # The overlay store rejects a target whose events do not exist.
        repo = _repo(tmp_path, exists=False)
        service = _service(reader, _FakeBackend(), repo)

        result = await service.generate_annotation(_target(0, 0))

        assert result.outcome is AnnotationGenerationOutcome.ANNOTATION_REJECTED
        assert result.detail == "unknown_reference"


class TestBackendFailure:
    async def test_backend_error_preserves_metadata(self, tmp_path: Path) -> None:
        reader = _FakeSourceReader(_found(_range(0, 0), [_event(0)]))
        error = AnnotationBackendError("ollama down", metadata=_META)
        repo = _repo(tmp_path)
        service = _service(reader, _FakeBackend(error=error), repo)

        result = await service.generate_annotation(_target(0, 0))

        assert result.outcome is AnnotationGenerationOutcome.BACKEND_FAILED
        assert result.metadata == _META
        assert repo.count() == 0

    async def test_plain_backend_exception(self, tmp_path: Path) -> None:
        reader = _FakeSourceReader(_found(_range(0, 0), [_event(0)]))
        service = _service(
            reader, _FakeBackend(error=RuntimeError("boom")), _repo(tmp_path)
        )

        result = await service.generate_annotation(_target(0, 0))

        assert result.outcome is AnnotationGenerationOutcome.BACKEND_FAILED
        assert result.metadata is None


class TestConstructorValidation:
    def test_rejects_zero_concurrency(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="max_concurrency"):
            _service(
                _FakeSourceReader(_found(_range(0, 0), [_event(0)])),
                _FakeBackend(),
                _repo(tmp_path),
                max_concurrency=0,
            )

    def test_rejects_zero_source_events(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="max_source_events"):
            _service(
                _FakeSourceReader(_found(_range(0, 0), [_event(0)])),
                _FakeBackend(),
                _repo(tmp_path),
                max_source_events=0,
            )

    def test_rejects_zero_source_chars(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="max_source_chars"):
            _service(
                _FakeSourceReader(_found(_range(0, 0), [_event(0)])),
                _FakeBackend(),
                _repo(tmp_path),
                max_source_chars=0,
            )

    def test_rejects_out_of_range_annotation_chars(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="max_annotation_chars"):
            _service(
                _FakeSourceReader(_found(_range(0, 0), [_event(0)])),
                _FakeBackend(),
                _repo(tmp_path),
                max_annotation_chars=0,
            )

    def test_rejects_empty_author(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="author"):
            _service(
                _FakeSourceReader(_found(_range(0, 0), [_event(0)])),
                _FakeBackend(),
                _repo(tmp_path),
                author="",
            )


class _RangeReader:
    """Synthesizes a FOUND read whose events match the requested range."""

    def read_range(self, event_range: HistoryEventRange) -> HistoryEventRangeRead:
        events = [
            _event(pos)
            for pos in range(
                event_range.start.event_position, event_range.end.event_position + 1
            )
        ]
        return _found(event_range, events)

    def read_session(self, session_id: str) -> HistorySessionRead:
        return HistorySessionRead(HistorySessionReadStatus.UNKNOWN_SESSION)


class TestConcurrency:
    async def test_semaphore_serializes_backend_calls(self, tmp_path: Path) -> None:
        active = 0
        peak = 0
        release = asyncio.Event()

        class _GatedBackend:
            async def run_annotation(
                self,
                messages: Sequence[AnnotationMessage],
                reasoning: ReasoningLevel = ReasoningLevel.OFF,
            ) -> AnnotationRun:
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                await release.wait()
                active -= 1
                return AnnotationRun("summary", _META)

        repo = _repo(tmp_path)
        service = AnnotationGenerationService(
            _RangeReader(), _GatedBackend(), repo, max_concurrency=1
        )

        jobs = [
            asyncio.ensure_future(service.generate_annotation(_target(pos, pos)))
            for pos in (0, 1)
        ]
        for _ in range(5):
            await asyncio.sleep(0)
        assert peak == 1  # only one backend call ran despite two queued jobs
        release.set()
        results = await asyncio.gather(*jobs)
        assert all(r.generated for r in results)
        assert peak == 1


class TestCancellation:
    async def test_cancel_pending_job_reports_cancelled(self, tmp_path: Path) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        class _BlockingBackend:
            async def run_annotation(
                self,
                messages: Sequence[AnnotationMessage],
                reasoning: ReasoningLevel = ReasoningLevel.OFF,
            ) -> AnnotationRun:
                started.set()
                await release.wait()
                return AnnotationRun("summary", _META)

        target = _target(0, 0)
        reader = _FakeSourceReader(_found(_range(0, 0), [_event(0)]))
        repo = _repo(tmp_path)
        service = AnnotationGenerationService(reader, _BlockingBackend(), repo)

        task = asyncio.ensure_future(service.generate_annotation(target))
        await started.wait()
        assert service.cancel(target)
        result = await task

        assert result.outcome is AnnotationGenerationOutcome.CANCELLED
        assert repo.count() == 0


class _FakeChatStream:
    def __init__(
        self,
        chunks: Sequence[Mapping[str, JSONValue]],
        payload: Mapping[str, JSONValue],
        error: Exception | None = None,
    ) -> None:
        self._chunks = chunks
        self._payload = payload
        self._error = error
        self.reasoning_levels: list[ReasoningLevel] = []

    def build_payload(
        self,
        messages: Sequence[Mapping[str, object]],
        images_b64: Sequence[str] | None = None,
        reasoning_level: ReasoningLevel = ReasoningLevel.OFF,
    ) -> Mapping[str, JSONValue]:
        self.reasoning_levels.append(reasoning_level)
        return self._payload

    async def iter_chat(
        self,
        messages: Sequence[Mapping[str, object]],
        images_b64: Sequence[str] | None = None,
        reasoning_level: ReasoningLevel = ReasoningLevel.OFF,
    ) -> AsyncIterator[Mapping[str, JSONValue]]:
        self.reasoning_levels.append(reasoning_level)
        if self._error is not None:
            raise self._error
        for chunk in self._chunks:
            yield chunk


class TestOllamaAnnotationBackendAdapter:
    async def test_collects_content_and_reads_metadata(self) -> None:
        stream = _FakeChatStream(
            chunks=[
                {"message": {"content": "part one "}},
                {"message": {"thinking": "ignored reasoning"}},
                {"message": {"content": "part two"}},
                {"done": True},
            ],
            payload={
                "model": "gemma4:12b-it-qat",
                "think": False,
                "options": {"num_ctx": 65536},
            },
        )
        backend = OllamaAnnotationBackend(stream)

        run = await backend.run_annotation(
            [AnnotationMessage(role="user", content="summarize")]
        )

        assert run.text == "part one part two"
        assert run.metadata.model == "gemma4:12b-it-qat"
        assert run.metadata.reasoning == "off"
        assert run.metadata.options == (("num_ctx", "65536"),)

    async def test_forwards_reasoning_level(self) -> None:
        stream = _FakeChatStream(chunks=[], payload={"model": "m", "think": "high"})
        backend = OllamaAnnotationBackend(stream)

        await backend.run_annotation(
            [AnnotationMessage(role="user", content="x")], ReasoningLevel.HIGH
        )

        assert stream.reasoning_levels == [ReasoningLevel.HIGH, ReasoningLevel.HIGH]

    async def test_stream_error_wraps_with_metadata(self) -> None:
        stream = _FakeChatStream(
            chunks=[],
            payload={"model": "m", "think": False},
            error=RuntimeError("stream broke"),
        )
        backend = OllamaAnnotationBackend(stream)

        with pytest.raises(AnnotationBackendError) as exc_info:
            await backend.run_annotation([AnnotationMessage(role="user", content="x")])
        assert exc_info.value.metadata is not None
        assert exc_info.value.metadata.model == "m"
