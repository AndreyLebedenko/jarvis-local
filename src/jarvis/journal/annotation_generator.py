"""Historical annotation generator (task-v1.8.0-22).

Explicit, source-grounded, non-dialog local Ollama generation of session
annotations. It never runs on its own initiative: a user or UI command names a
whole session or a bounded event range, the service reads exactly that material
through the history read API (`HistoryCorpusRepository`), asks the local model
to summarize only the cited material, and writes the result to the annotation
overlay store (task-v1.8.0-21) anchored to that same target.

Source grounding is structural, not just instructional: the model sees only the
events read for the requested target, and the stored annotation's target is
exactly that target, so every generated annotation is traceable to the material
it summarized. The model is never handed unrelated context to "summarize".

This is deliberately not part of the live dialog path, mirroring the
transcription service (task-v1.8.0-19):

- It does not publish `ResponseToken`, so a generated annotation never reaches
  TTS or the conversation record. It collects the model's answer text directly.
- Model calls pass through a bounded semaphore so historical generation
  competes predictably with a live turn instead of fanning out unboundedly and
  fighting the live generation for VRAM.
- It writes only to the derived annotation overlay; raw journal events are
  never rewritten.

Auditing: the model and generation options recorded on a result and stored in
the annotation's metadata are the ones the backend actually built for the
request (`AnnotationRun` carries them back from the backend seam), never an
independently supplied string that could drift from the real call. Failures
carry that metadata too, so a retryable attempt stays auditable.

Out of scope for this card (see the story card): an automatic scheduler, UI,
retrieval-projection integration, and consolidation. This module is a pure
in-process service with injected seams so request construction, source
bounding, and job state are testable without live Ollama.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TypeVar

from jarvis.dialog.thinking_mode import ReasoningLevel
from jarvis.journal.annotation import (
    ANNOTATION_MAX_TEXT_LENGTH,
    AnnotationSource,
    AnnotationStatus,
    AnnotationTarget,
    AnnotationWriteResult,
)
from jarvis.journal.corpus import (
    HistoryCorpusEvent,
    HistoryEventRange,
    HistoryEventRangeRead,
    HistoryEventRangeStatus,
    HistorySessionRead,
    HistorySessionReadStatus,
)
from jarvis.journal.events import JournalEventRef, JSONValue

logger = logging.getLogger(__name__)

DEFAULT_MAX_CONCURRENCY = 1
DEFAULT_MAX_SOURCE_EVENTS = 100
DEFAULT_MAX_SOURCE_CHARS = 24000
DEFAULT_MAX_ANNOTATION_CHARS = 4000
DEFAULT_REASONING = ReasoningLevel.OFF
GENERATOR_AUTHOR = "annotation-generator"

# Model-facing instruction (not user-facing TTS/dialog text; normal Russian
# typography applies). Russian framing so a summary of a Russian conversation
# comes back in Russian, kept configurable for live tuning. The explicit
# attribution clause is load-bearing, not decorative: a live A/B (2026-08-07,
# gemma4:12b-it-qat, reasoning off) showed that under a Russian instruction
# *without* it, terse summaries flattened the assistant's own claim into a bare
# user fact (3/3 samples) - exactly the promotion story-v1.8.0 decision 5
# forbids - while adding it drove that to 0/3. Input format was not the lever:
# a JSONL source block did not fix the flattening and cost ~10% more tokens, so
# the delimited label block in format_source_block() was kept. Summarizing only
# the cited excerpt (together with the fact that only cited events are in the
# prompt) is what keeps a generated annotation grounded in its source range.
DEFAULT_ANNOTATION_INSTRUCTION = (
    "Напиши краткое фактическое резюме приведённого фрагмента разговора. "
    "Резюмируй только то, что прямо сказано в процитированных сообщениях; "
    "ничего не додумывай, не выдумывай и не переводи. "
    "Указывай, кто сделал каждое утверждение (пользователь или ассистент); "
    "не выдавай реплики ассистента за факты пользователя. "
    "Выведи только текст резюме."
)

_T = TypeVar("_T")

# One chat message as this service builds it: role plus text content.
ChatMessageValue = str | Sequence[str]


class AnnotationGenerationOutcome(Enum):
    GENERATED = "generated"
    UNKNOWN_RANGE = "unknown_range"
    SOURCE_TOO_LARGE = "source_too_large"
    SOURCE_TEXT_TOO_LARGE = "source_text_too_large"
    EMPTY_SOURCE = "empty_source"
    EMPTY_ANNOTATION = "empty_annotation"
    OUTPUT_TOO_LONG = "output_too_long"
    ANNOTATION_REJECTED = "annotation_rejected"
    BACKEND_FAILED = "backend_failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class AnnotationMessage:
    role: str
    content: str


@dataclass(frozen=True)
class AnnotationBackendMetadata:
    """What the backend actually asked the model to do for this request.

    Sourced from the backend's own request payload so the audit trail cannot
    claim a model or option set different from the one that ran.
    """

    model: str
    reasoning: str
    options: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class AnnotationRun:
    text: str
    metadata: AnnotationBackendMetadata


@dataclass(frozen=True)
class AnnotationRequest:
    """The constructed model request for one range, plus its provenance.

    Pure value object so request construction is testable without a backend or
    live Ollama: ``messages`` is exactly what reaches the backend seam, and
    ``source_references`` records which events were cited.
    """

    event_range: HistoryEventRange
    messages: tuple[AnnotationMessage, ...]
    source_references: tuple[JournalEventRef, ...]
    source_char_count: int


@dataclass(frozen=True)
class AnnotationGenerationResult:
    target: AnnotationTarget
    outcome: AnnotationGenerationOutcome
    source_references: tuple[JournalEventRef, ...] = ()
    annotation_id: str | None = None
    annotation: str | None = None
    detail: str | None = None
    metadata: AnnotationBackendMetadata | None = None

    @property
    def generated(self) -> bool:
        return self.outcome is AnnotationGenerationOutcome.GENERATED


class AnnotationSourceReader(Protocol):
    """Reads source material through the typed history read API.

    `HistoryCorpusRepository` satisfies this structurally; the generator never
    reaches past it into the raw store, so the material it summarizes is exactly
    what the read API exposes with provenance. ``read_session`` resolves a
    whole-session target's event bounds before the range is read.
    """

    def read_range(self, event_range: HistoryEventRange) -> HistoryEventRangeRead: ...

    def read_session(self, session_id: str) -> HistorySessionRead: ...


class AnnotationChatStream(Protocol):
    """Narrow view of the Ollama chat backend the adapter consumes.

    Exactly the two operations the adapter needs: build the request payload (to
    read the effective model/options) and stream the response. `OllamaBackend`
    satisfies this structurally without this module importing it.
    """

    def build_payload(
        self,
        messages: Sequence[Mapping[str, ChatMessageValue]],
        images_b64: Sequence[str] | None = None,
        reasoning_level: ReasoningLevel = ReasoningLevel.OFF,
    ) -> Mapping[str, JSONValue]: ...

    def iter_chat(
        self,
        messages: Sequence[Mapping[str, ChatMessageValue]],
        images_b64: Sequence[str] | None = None,
        reasoning_level: ReasoningLevel = ReasoningLevel.OFF,
    ) -> AsyncIterator[Mapping[str, JSONValue]]: ...


class AnnotationInferenceBackend(Protocol):
    """Runs one prepared, non-dialog annotation request.

    Implementations must not publish `ResponseToken` or otherwise feed the
    dialog/TTS pipeline; they collect the model's answer content and report the
    model/options they actually used. Reasoning trace (`message.thinking`) is
    never read even when ``reasoning`` is on, per PROJECT.md's reasoning
    isolation rule.
    """

    async def run_annotation(
        self,
        messages: Sequence[AnnotationMessage],
        reasoning: ReasoningLevel = ReasoningLevel.OFF,
    ) -> AnnotationRun: ...


class AnnotationWriter(Protocol):
    def add_annotation(
        self,
        target: AnnotationTarget,
        text: str,
        author: str,
        source: AnnotationSource,
        status: AnnotationStatus = AnnotationStatus.ACTIVE,
        metadata: dict[str, JSONValue] | None = None,
    ) -> AnnotationWriteResult: ...


class AnnotationBackendError(Exception):
    """A backend failure that still carries the prepared request metadata.

    The model and options are known once the request payload is built, before
    the stream can fail. Raising this instead of a bare exception lets the
    service record the model/config a failed, retryable attempt actually used.
    """

    def __init__(
        self,
        message: str,
        *,
        metadata: AnnotationBackendMetadata | None = None,
    ) -> None:
        super().__init__(message)
        self.metadata = metadata


class OllamaAnnotationBackend:
    """Adapter over the streaming `/api/chat` backend for non-dialog use.

    Consumes `iter_chat` and concatenates only `message.content`.
    `message.thinking` is never read - the reasoning trace stays out of the
    stored annotation even when ``reasoning`` is on, per PROJECT.md's
    reasoning-isolation rule. The effective model, reasoning, and options are
    read from the backend's own `build_payload` so the reported metadata is the
    request that actually ran.
    """

    def __init__(self, backend: AnnotationChatStream) -> None:
        self._backend = backend

    async def run_annotation(
        self,
        messages: Sequence[AnnotationMessage],
        reasoning: ReasoningLevel = ReasoningLevel.OFF,
    ) -> AnnotationRun:
        chat_messages: list[dict[str, ChatMessageValue]] = [
            {"role": message.role, "content": message.content} for message in messages
        ]
        payload = self._backend.build_payload(chat_messages, reasoning_level=reasoning)
        metadata = _metadata_from_payload(payload)

        parts: list[str] = []
        try:
            async for chunk in self._backend.iter_chat(
                chat_messages, reasoning_level=reasoning
            ):
                message = chunk.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str) and content:
                        parts.append(content)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise AnnotationBackendError(str(exc), metadata=metadata) from exc
        return AnnotationRun("".join(parts), metadata)


def _metadata_from_payload(
    payload: Mapping[str, JSONValue],
) -> AnnotationBackendMetadata:
    model = payload.get("model")
    return AnnotationBackendMetadata(
        model=str(model) if model is not None else "",
        reasoning=_reasoning_label(payload.get("think")),
        options=_render_options(payload.get("options")),
    )


def _reasoning_label(value: JSONValue) -> str:
    if value is False:
        return "off"
    if value is True:
        return "on"
    return str(value)


def _render_options(value: JSONValue) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict):
        return ()
    return tuple(
        (key, json.dumps(value[key], ensure_ascii=False, sort_keys=True))
        for key in sorted(value)
    )


def _format_options(options: tuple[tuple[str, str], ...]) -> str:
    if not options:
        return "-"
    return ",".join(f"{name}={value}" for name, value in options)


def exceeds_source_bound(
    event_range: HistoryEventRange, max_source_events: int
) -> bool:
    """Whether the requested range is larger than the configured source cap.

    A malformed range (cross-session or reversed, ``requested_count == 0``) is
    not "too large"; the read API reports its specific reason instead.
    """

    count = event_range.requested_count
    return count > max_source_events


def format_source_block(session_id: str, events: Sequence[HistoryCorpusEvent]) -> str:
    """Render the cited events as delimited, provenance-bearing source text."""

    lines: list[str] = []
    for event in events:
        marker = " (transcript)" if event.text_is_transcript else ""
        lines.append(
            f"[#{event.reference.event_position}] "
            f"{event.role} / {event.source}{marker} @ {event.timestamp}"
        )
        lines.append(event.indexed_text)
        lines.append("")
    header = f"Source material (session {session_id}):"
    return "\n".join([header, "", *lines]).rstrip() + "\n"


def build_annotation_messages(
    instruction: str, source_block: str
) -> tuple[AnnotationMessage, ...]:
    return (AnnotationMessage(role="user", content=f"{instruction}\n\n{source_block}"),)


def build_annotation_request(
    event_range: HistoryEventRange,
    events: Sequence[HistoryCorpusEvent],
    *,
    instruction: str,
) -> AnnotationRequest:
    """Assemble the model request. Pure: no I/O, no backend, fully testable."""

    source_block = format_source_block(event_range.start.session_id, events)
    return AnnotationRequest(
        event_range=event_range,
        messages=build_annotation_messages(instruction, source_block),
        source_references=tuple(event.reference for event in events),
        source_char_count=sum(len(event.indexed_text) for event in events),
    )


async def _run_to_completion(task: asyncio.Task[_T]) -> _T:
    """Await ``task`` to its result, absorbing cancellation of the awaiter.

    Used only for the annotation write: once submitted it is a point of no
    return (a worker thread cannot be interrupted), so a cancellation arriving
    mid-write must not surface as `CANCELLED` while the overlay is being
    committed. Cancellation that arrives *before* the write is submitted still
    aborts at an earlier await and never reaches here.
    """

    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                return task.result()


class AnnotationGenerationService:
    def __init__(
        self,
        source: AnnotationSourceReader,
        backend: AnnotationInferenceBackend,
        annotations: AnnotationWriter,
        *,
        instruction: str = DEFAULT_ANNOTATION_INSTRUCTION,
        reasoning: ReasoningLevel = DEFAULT_REASONING,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        max_source_events: int = DEFAULT_MAX_SOURCE_EVENTS,
        max_source_chars: int = DEFAULT_MAX_SOURCE_CHARS,
        max_annotation_chars: int = DEFAULT_MAX_ANNOTATION_CHARS,
        author: str = GENERATOR_AUTHOR,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        if max_source_events < 1:
            raise ValueError("max_source_events must be at least 1")
        if max_source_chars < 1:
            raise ValueError("max_source_chars must be at least 1")
        if not 1 <= max_annotation_chars <= ANNOTATION_MAX_TEXT_LENGTH:
            raise ValueError(
                "max_annotation_chars must be between 1 and "
                f"{ANNOTATION_MAX_TEXT_LENGTH}"
            )
        if not author:
            raise ValueError("author must not be empty")
        self._source = source
        self._backend = backend
        self._annotations = annotations
        self._instruction = instruction
        self._reasoning = reasoning
        self._max_source_events = max_source_events
        self._max_source_chars = max_source_chars
        self._max_annotation_chars = max_annotation_chars
        self._author = author
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._active: dict[
            AnnotationTarget, asyncio.Task[AnnotationGenerationResult]
        ] = {}

    @property
    def reasoning(self) -> ReasoningLevel:
        return self._reasoning

    @property
    def max_source_events(self) -> int:
        return self._max_source_events

    @property
    def max_source_chars(self) -> int:
        return self._max_source_chars

    def active_targets(self) -> tuple[AnnotationTarget, ...]:
        return tuple(self._active)

    def cancel_all(self) -> None:
        for task in tuple(self._active.values()):
            task.cancel()

    def cancel(self, target: AnnotationTarget) -> bool:
        task = self._active.get(target)
        if task is None:
            return False
        task.cancel()
        return True

    async def generate_annotation(
        self, target: AnnotationTarget
    ) -> AnnotationGenerationResult:
        """Generate one annotation for a target and persist the overlay.

        ``target`` is either a whole session (its full event span is read) or an
        inclusive event range. The stored annotation is anchored to that same
        target, so a whole-session summary stays "the session" rather than a
        frozen range.

        A concurrent call for the same target joins the in-flight job; the
        `_active` entry is cleared when the shared job actually finishes, so a
        job that keeps running past an externally cancelled owner (e.g.
        committing its overlay write) stays joinable and cannot be duplicated by
        a fresh request for the same target. This mirrors the transcription
        service's job model.
        """

        task = self._active.get(target)
        if task is not None and task.done():
            task = None
        owner = task is None
        if task is None:
            task = asyncio.ensure_future(self._run(target))
            self._active[target] = task
            self._forget_when_done(target, task)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.cancelled():
                return self._log_result(
                    AnnotationGenerationResult(
                        target, AnnotationGenerationOutcome.CANCELLED
                    )
                )
            if owner:
                task.cancel()
            raise

    def _forget_when_done(
        self,
        target: AnnotationTarget,
        task: asyncio.Task[AnnotationGenerationResult],
    ) -> None:
        def _discard(done: asyncio.Task[AnnotationGenerationResult]) -> None:
            if self._active.get(target) is done:
                del self._active[target]

        task.add_done_callback(_discard)

    async def _run(self, target: AnnotationTarget) -> AnnotationGenerationResult:
        prepared = await self._prepare_source(target)
        if isinstance(prepared, AnnotationGenerationResult):
            return prepared
        request = prepared

        run = await self._invoke_backend(target, request)
        if isinstance(run, AnnotationGenerationResult):
            return run

        return await self._persist(target, request, run)

    async def _resolve_read_range(
        self, target: AnnotationTarget
    ) -> HistoryEventRange | AnnotationGenerationResult:
        """The event range to read: the whole session, or the explicit range."""

        if not target.is_whole_session:
            try:
                return HistoryEventRange(
                    JournalEventRef(target.session_id, target.start_position),
                    JournalEventRef(target.session_id, target.end_position),
                )
            except (ValueError, TypeError):
                return self._log_result(
                    AnnotationGenerationResult(
                        target,
                        AnnotationGenerationOutcome.UNKNOWN_RANGE,
                        detail="invalid_target",
                    )
                )
        session_read = await asyncio.to_thread(
            self._source.read_session, target.session_id
        )
        if (
            session_read.status is not HistorySessionReadStatus.FOUND
            or session_read.session is None
        ):
            return self._log_result(
                AnnotationGenerationResult(
                    target,
                    AnnotationGenerationOutcome.UNKNOWN_RANGE,
                    detail="unknown_session",
                )
            )
        metadata = session_read.session
        return HistoryEventRange(
            JournalEventRef(target.session_id, metadata.first_event_position),
            JournalEventRef(target.session_id, metadata.last_event_position),
        )

    async def _prepare_source(
        self, target: AnnotationTarget
    ) -> AnnotationRequest | AnnotationGenerationResult:
        resolved = await self._resolve_read_range(target)
        if isinstance(resolved, AnnotationGenerationResult):
            return resolved
        read_range = resolved

        if exceeds_source_bound(read_range, self._max_source_events):
            return self._log_result(
                AnnotationGenerationResult(
                    target,
                    AnnotationGenerationOutcome.SOURCE_TOO_LARGE,
                    detail=f"{read_range.requested_count} > {self._max_source_events}",
                )
            )
        read = await asyncio.to_thread(self._source.read_range, read_range)
        if read.status is HistoryEventRangeStatus.TOO_MANY_EVENTS:
            return self._log_result(
                AnnotationGenerationResult(
                    target,
                    AnnotationGenerationOutcome.SOURCE_TOO_LARGE,
                    detail=read.status.value,
                )
            )
        if read.status is not HistoryEventRangeStatus.FOUND:
            return self._log_result(
                AnnotationGenerationResult(
                    target,
                    AnnotationGenerationOutcome.UNKNOWN_RANGE,
                    detail=read.status.value,
                )
            )
        request = build_annotation_request(
            read_range, read.events, instruction=self._instruction
        )
        if request.source_char_count == 0:
            return self._log_result(
                AnnotationGenerationResult(
                    target,
                    AnnotationGenerationOutcome.EMPTY_SOURCE,
                    source_references=request.source_references,
                )
            )
        if request.source_char_count > self._max_source_chars:
            # A bounded event count still allows a few very long events to form
            # an unbounded prompt (raw event text has no upper limit), which
            # would make this non-dialog call compete unpredictably with a live
            # turn. Reject on total source size before reaching the model.
            return self._log_result(
                AnnotationGenerationResult(
                    target,
                    AnnotationGenerationOutcome.SOURCE_TEXT_TOO_LARGE,
                    source_references=request.source_references,
                    detail=f"{request.source_char_count} > {self._max_source_chars}",
                )
            )
        return request

    async def _invoke_backend(
        self, target: AnnotationTarget, request: AnnotationRequest
    ) -> AnnotationRun | AnnotationGenerationResult:
        try:
            async with self._semaphore:
                return await self._backend.run_annotation(
                    request.messages, self._reasoning
                )
        except asyncio.CancelledError:
            raise
        except AnnotationBackendError as exc:
            logger.exception("Annotation backend failed for %s", _target_label(target))
            return self._log_result(
                AnnotationGenerationResult(
                    target,
                    AnnotationGenerationOutcome.BACKEND_FAILED,
                    source_references=request.source_references,
                    detail=str(exc),
                    metadata=exc.metadata,
                )
            )
        except Exception as exc:
            logger.exception("Annotation backend failed for %s", _target_label(target))
            return self._log_result(
                AnnotationGenerationResult(
                    target,
                    AnnotationGenerationOutcome.BACKEND_FAILED,
                    source_references=request.source_references,
                    detail=str(exc),
                )
            )

    async def _persist(
        self,
        target: AnnotationTarget,
        request: AnnotationRequest,
        run: AnnotationRun,
    ) -> AnnotationGenerationResult:
        annotation_text = run.text.strip()
        if not annotation_text:
            return self._log_result(
                AnnotationGenerationResult(
                    target,
                    AnnotationGenerationOutcome.EMPTY_ANNOTATION,
                    source_references=request.source_references,
                    metadata=run.metadata,
                )
            )
        if len(annotation_text) > self._max_annotation_chars:
            return self._log_result(
                AnnotationGenerationResult(
                    target,
                    AnnotationGenerationOutcome.OUTPUT_TOO_LONG,
                    source_references=request.source_references,
                    detail=f"{len(annotation_text)} > {self._max_annotation_chars}",
                    metadata=run.metadata,
                )
            )

        metadata = _annotation_metadata(run.metadata, request)
        write_task: asyncio.Task[AnnotationWriteResult] = asyncio.ensure_future(
            asyncio.to_thread(
                self._annotations.add_annotation,
                target,
                annotation_text,
                self._author,
                AnnotationSource.GENERATED,
                metadata=metadata,
            )
        )
        write = await _run_to_completion(write_task)
        if not write.accepted:
            return self._log_result(
                AnnotationGenerationResult(
                    target,
                    AnnotationGenerationOutcome.ANNOTATION_REJECTED,
                    source_references=request.source_references,
                    detail=write.status.value,
                    metadata=run.metadata,
                )
            )
        return self._log_result(
            AnnotationGenerationResult(
                target,
                AnnotationGenerationOutcome.GENERATED,
                source_references=request.source_references,
                annotation_id=write.annotation_id,
                annotation=annotation_text,
                metadata=run.metadata,
            )
        )

    def _log_result(
        self, result: AnnotationGenerationResult
    ) -> AnnotationGenerationResult:
        metadata = result.metadata
        model = metadata.model if metadata is not None else "-"
        reasoning = metadata.reasoning if metadata is not None else "-"
        options = _format_options(metadata.options) if metadata is not None else "-"
        logger.info(
            "Annotation %s for %s (model=%s, reasoning=%s, options=%s, sources=%d)%s",
            result.outcome.value,
            _target_label(result.target),
            model,
            reasoning,
            options,
            len(result.source_references),
            f": {result.detail}" if result.detail else "",
        )
        return result


def _annotation_metadata(
    backend_metadata: AnnotationBackendMetadata, request: AnnotationRequest
) -> dict[str, JSONValue]:
    """Model/configuration provenance stored on the generated annotation."""

    return {
        "model": backend_metadata.model,
        "reasoning": backend_metadata.reasoning,
        "options": [[name, value] for name, value in backend_metadata.options],
        "source_event_count": len(request.source_references),
    }


def _target_label(target: AnnotationTarget) -> str:
    if target.is_whole_session:
        return f"{target.session_id}#all"
    return f"{target.session_id}#{target.start_position}-{target.end_position}"
