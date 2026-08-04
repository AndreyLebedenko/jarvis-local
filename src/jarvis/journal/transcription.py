"""Historical transcription service (task-v1.8.0-19).

Explicit, non-dialog local Ollama transcription for already-recorded voice
audio. It never runs on its own initiative: a user or UI command asks for one
event reference, the service reads that event's stored audio, sends it to the
local backend through the verified `images` media transport, and writes the
result to the transcript overlay store keyed to the source event.

This is deliberately not part of the live dialog path:

- It does not publish `ResponseToken`, so a transcription never reaches TTS or
  the conversation record. It collects the model's answer text directly.
- Model calls pass through a bounded semaphore so historical transcription
  competes predictably with a live turn instead of fanning out unboundedly and
  fighting the live generation for VRAM.
- It writes only to the derived transcript overlay (task-v1.8.0-18); the raw
  journal event and its `transcript` field are never rewritten.

Auditing: the model and generation options recorded on a result and in the log
are the ones the backend actually built for the request (`TranscriptionRun`
carries them back from the backend seam), never an independently supplied
string that could drift from the real call.

Out of scope for this card (see the story card): a background scheduler,
automatic audio deletion, annotation generation, retrieval projection
integration, and UI. This module is a pure in-process service with injected
seams so request construction and job state are testable without live Ollama.

Media-format note: the only historical audio today is voice-turn `.wav` media,
which `JournalRecorder` already writes as 16 kHz mono WAV within the model's
30 s clip limit (PROJECT.md verified facts). The service therefore passes those
bytes straight through to `images`; decoding/resampling arbitrary uploaded
audio formats is a separate concern and is not done here.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Protocol, TypeVar

from jarvis.journal.events import JournalEvent, JournalEventRef, JSONValue
from jarvis.journal.store import JournalStore
from jarvis.journal.transcript import TranscriptSource, TranscriptUpsertResult

logger = logging.getLogger(__name__)

AUDIO_MEDIA_EXTENSIONS = frozenset({".wav"})
DEFAULT_MAX_CONCURRENCY = 1

# Runtime data sent to the model, not documentation or UI text: Russian
# typography is canonical here, same exception as the dialog system prompt
# (CLAUDE.md rule 9). Historical voice audio is predominantly Russian speech.
DEFAULT_TRANSCRIPTION_INSTRUCTION = (
    "Расшифруй дословно речь в этой аудиозаписи. Выведи только произнесённый "
    "текст, без комментариев, пояснений и кавычек. Если речь на другом языке, "
    "расшифруй на языке оригинала."
)

_T = TypeVar("_T")

# One chat message as this service builds it: role plus text content, and
# optionally the base64 media list the `images` transport carries.
ChatMessageValue = str | Sequence[str]


class TranscriptionOutcome(Enum):
    TRANSCRIBED = "transcribed"
    UNKNOWN_EVENT = "unknown_event"
    NO_AUDIO_MEDIA = "no_audio_media"
    MEDIA_UNREADABLE = "media_unreadable"
    EMPTY_TRANSCRIPT = "empty_transcript"
    TRANSCRIPT_REJECTED = "transcript_rejected"
    BACKEND_FAILED = "backend_failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class TranscriptionMessage:
    role: str
    content: str


@dataclass(frozen=True)
class TranscriptionBackendMetadata:
    """What the backend actually asked the model to do for this request.

    Sourced from the backend's own request payload so the audit trail cannot
    claim a model or option set different from the one that ran. `options` is
    the payload's generation options rendered as sorted (name, json-value)
    pairs so it stays a typed, comparable, loggable value.
    """

    model: str
    reasoning: str
    options: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class TranscriptionRun:
    text: str
    metadata: TranscriptionBackendMetadata


@dataclass(frozen=True)
class TranscriptionRequest:
    """The constructed model request for one event, plus its provenance.

    Pure value object so request construction is testable without a backend or
    live Ollama: `messages`/`images_b64` are exactly what reaches the backend
    seam, `source_media` records which of the event's media files were read.
    The model and options are not fixed here - the backend owns them and
    reports the effective values back through `TranscriptionRun.metadata`.
    """

    reference: JournalEventRef
    messages: tuple[TranscriptionMessage, ...]
    images_b64: tuple[str, ...]
    source_media: tuple[str, ...]


@dataclass(frozen=True)
class TranscriptionResult:
    reference: JournalEventRef
    outcome: TranscriptionOutcome
    source_media: tuple[str, ...] = ()
    transcript: str | None = None
    detail: str | None = None
    metadata: TranscriptionBackendMetadata | None = None

    @property
    def transcribed(self) -> bool:
        return self.outcome is TranscriptionOutcome.TRANSCRIBED


class TranscriptionEventSource(Protocol):
    """Reads the authoritative source event and its media bytes.

    Validation is against the raw journal, never a derived projection, so a
    not-yet-rebuilt corpus can never make a real event look missing.
    """

    def read_event(self, reference: JournalEventRef) -> JournalEvent | None: ...

    def read_media(self, session_id: str, name: str) -> bytes: ...


class TranscriptionChatStream(Protocol):
    """Narrow view of the Ollama chat backend the adapter consumes.

    Exactly the two operations the adapter needs: build the request payload
    (to read the effective model/options) and stream the response. `OllamaBackend`
    satisfies this structurally without this module importing it.
    """

    def build_payload(
        self,
        messages: Sequence[Mapping[str, ChatMessageValue]],
        images_b64: Sequence[str] | None = None,
    ) -> Mapping[str, JSONValue]: ...

    def iter_chat(
        self,
        messages: Sequence[Mapping[str, ChatMessageValue]],
        images_b64: Sequence[str] | None = None,
    ) -> AsyncIterator[Mapping[str, JSONValue]]: ...


class TranscriptionInferenceBackend(Protocol):
    """Runs one prepared, non-dialog transcription request.

    Implementations must not publish `ResponseToken` or otherwise feed the
    dialog/TTS pipeline; they collect the model's answer content and report the
    model/options they actually used.
    """

    async def run_transcription(
        self,
        messages: Sequence[TranscriptionMessage],
        images_b64: Sequence[str],
    ) -> TranscriptionRun: ...


class TranscriptWriter(Protocol):
    def upsert_transcript(
        self,
        reference: JournalEventRef,
        text: str,
        source: TranscriptSource,
    ) -> TranscriptUpsertResult: ...


class TranscriptionBackendError(Exception):
    """A backend failure that still carries the prepared request metadata.

    The model and options are known once the request payload is built, before
    the stream can fail. Raising this instead of a bare exception lets the
    service record the model/config a failed, retryable attempt actually used,
    rather than dropping that audit information on any stream error.
    """

    def __init__(
        self,
        message: str,
        *,
        metadata: TranscriptionBackendMetadata | None = None,
    ) -> None:
        super().__init__(message)
        self.metadata = metadata


class JournalStoreTranscriptionSource:
    """`TranscriptionEventSource` backed by the append-only journal store."""

    def __init__(self, store: JournalStore) -> None:
        self._store = store

    def read_event(self, reference: JournalEventRef) -> JournalEvent | None:
        records = self._store.read_session(reference.session_id).records
        if reference.event_position >= len(records):
            return None
        record = records[reference.event_position]
        if record.reference != reference:
            return None
        return record.event

    def read_media(self, session_id: str, name: str) -> bytes:
        return (self._store.root / session_id / name).read_bytes()


class OllamaTranscriptionBackend:
    """Adapter over the streaming `/api/chat` backend for non-dialog use.

    Consumes `iter_chat` (the verified `images` media path) and concatenates
    only `message.content`. `message.thinking` is never read - transcription
    runs with reasoning off, and content must stay clean either way per
    PROJECT.md's reasoning-isolation rule. The effective model and options are
    read from the backend's own `build_payload` so the reported metadata is the
    request that actually ran.
    """

    def __init__(self, backend: TranscriptionChatStream) -> None:
        self._backend = backend

    async def run_transcription(
        self,
        messages: Sequence[TranscriptionMessage],
        images_b64: Sequence[str],
    ) -> TranscriptionRun:
        chat_messages: list[dict[str, ChatMessageValue]] = [
            {"role": message.role, "content": message.content} for message in messages
        ]
        images = list(images_b64)
        payload = self._backend.build_payload(chat_messages, images)
        metadata = _metadata_from_payload(payload)

        parts: list[str] = []
        try:
            async for chunk in self._backend.iter_chat(chat_messages, images):
                message = chunk.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str) and content:
                        parts.append(content)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Metadata is already known from the built payload; attach it so a
            # retryable stream failure is still audited against the real model.
            raise TranscriptionBackendError(str(exc), metadata=metadata) from exc
        return TranscriptionRun("".join(parts), metadata)


def _metadata_from_payload(
    payload: Mapping[str, JSONValue],
) -> TranscriptionBackendMetadata:
    model = payload.get("model")
    options = payload.get("options")
    return TranscriptionBackendMetadata(
        model=str(model) if model is not None else "",
        reasoning=_reasoning_label(payload.get("think")),
        options=_render_options(options),
    )


def _reasoning_label(value: JSONValue) -> str:
    if value is False:
        return "off"
    if value is True:
        return "on"
    return str(value)


def _format_options(options: tuple[tuple[str, str], ...]) -> str:
    if not options:
        return "-"
    return ",".join(f"{name}={value}" for name, value in options)


def _render_options(value: JSONValue) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict):
        return ()
    return tuple(
        (key, json.dumps(value[key], ensure_ascii=False, sort_keys=True))
        for key in sorted(value)
    )


def select_audio_media(event: JournalEvent) -> tuple[str, ...]:
    """The event's media files that this service can transcribe, in order.

    Non-audio media (screenshots attached to a voice turn) and events with no
    audio at all resolve to an empty tuple, which the caller reports as a clear
    refusal rather than a silent skip.
    """

    return tuple(
        name
        for name in event.media
        if PurePosixPath(name).suffix.lower() in AUDIO_MEDIA_EXTENSIONS
    )


def build_transcription_messages(instruction: str) -> tuple[TranscriptionMessage, ...]:
    return (TranscriptionMessage(role="user", content=instruction),)


def build_transcription_request(
    reference: JournalEventRef,
    *,
    instruction: str,
    audio_media: Sequence[str],
    media_bytes: Sequence[bytes],
) -> TranscriptionRequest:
    """Assemble the model request. Pure: no I/O, no backend, fully testable."""

    images_b64 = tuple(base64.b64encode(data).decode("ascii") for data in media_bytes)
    return TranscriptionRequest(
        reference=reference,
        messages=build_transcription_messages(instruction),
        images_b64=images_b64,
        source_media=tuple(audio_media),
    )


async def _run_to_completion(task: asyncio.Task[_T]) -> _T:
    """Await ``task`` to its result, absorbing cancellation of the awaiter.

    Used only for the transcript write: once the write has been submitted it is
    a point of no return (a worker thread cannot be interrupted), so a
    cancellation arriving mid-write must not surface as `CANCELLED` while the
    overlay is being committed. The write completes and its real outcome is
    reported. Cancellation that arrives *before* the write is submitted still
    aborts at an earlier await and never reaches here.
    """

    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                return task.result()


class TranscriptionService:
    def __init__(
        self,
        source: TranscriptionEventSource,
        backend: TranscriptionInferenceBackend,
        transcripts: TranscriptWriter,
        *,
        instruction: str = DEFAULT_TRANSCRIPTION_INSTRUCTION,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._source = source
        self._backend = backend
        self._transcripts = transcripts
        self._instruction = instruction
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._active: dict[JournalEventRef, asyncio.Task[TranscriptionResult]] = {}

    def active_references(self) -> tuple[JournalEventRef, ...]:
        return tuple(self._active)

    def cancel_all(self) -> None:
        for task in tuple(self._active.values()):
            task.cancel()

    def cancel(self, reference: JournalEventRef) -> bool:
        task = self._active.get(reference)
        if task is None:
            return False
        task.cancel()
        return True

    async def transcribe_event(self, reference: JournalEventRef) -> TranscriptionResult:
        """Transcribe one event and persist the overlay.

        The underlying job is tracked so it can be cancelled by reference or via
        `cancel_all()`. Explicit cancellation of the job (or the owning caller's
        own cancellation) resolves to a `CANCELLED` result with no overlay
        write. A concurrent call for the same reference joins the in-flight job;
        if that joined caller is itself cancelled, it gets its own cancellation
        and the shared job continues undisturbed for the owner.

        The `_active` entry is cleared when the shared job actually finishes,
        not when a waiter returns, so a job that keeps running past an
        externally cancelled owner (e.g. committing its overlay write) stays
        joinable and cannot be duplicated by a fresh request for the same
        reference.
        """

        task = self._active.get(reference)
        if task is not None and task.done():
            task = None
        owner = task is None
        if task is None:
            task = asyncio.ensure_future(self._run(reference))
            self._active[reference] = task
            self._forget_when_done(reference, task)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.cancelled():
                return self._log_result(
                    TranscriptionResult(reference, TranscriptionOutcome.CANCELLED)
                )
            # Our own await was cancelled while the shielded job kept running.
            # Only the owner propagates that into the shared job; a joined
            # waiter must not cancel work the owner still wants.
            if owner:
                task.cancel()
            raise

    def _forget_when_done(
        self, reference: JournalEventRef, task: asyncio.Task[TranscriptionResult]
    ) -> None:
        def _discard(done: asyncio.Task[TranscriptionResult]) -> None:
            if self._active.get(reference) is done:
                del self._active[reference]

        task.add_done_callback(_discard)

    async def _run(self, reference: JournalEventRef) -> TranscriptionResult:
        event = await asyncio.to_thread(self._source.read_event, reference)
        if event is None:
            return self._log_result(
                TranscriptionResult(reference, TranscriptionOutcome.UNKNOWN_EVENT)
            )

        audio_media = select_audio_media(event)
        if not audio_media:
            return self._log_result(
                TranscriptionResult(reference, TranscriptionOutcome.NO_AUDIO_MEDIA)
            )

        try:
            media_bytes = [
                await asyncio.to_thread(
                    self._source.read_media, reference.session_id, name
                )
                for name in audio_media
            ]
        except OSError as exc:
            return self._log_result(
                TranscriptionResult(
                    reference,
                    TranscriptionOutcome.MEDIA_UNREADABLE,
                    source_media=audio_media,
                    detail=str(exc),
                )
            )

        request = build_transcription_request(
            reference,
            instruction=self._instruction,
            audio_media=audio_media,
            media_bytes=media_bytes,
        )

        try:
            async with self._semaphore:
                run = await self._backend.run_transcription(
                    request.messages, request.images_b64
                )
        except asyncio.CancelledError:
            raise
        except TranscriptionBackendError as exc:
            logger.exception(
                "Transcription backend failed for %s:%s",
                reference.session_id,
                reference.event_position,
            )
            return self._log_result(
                TranscriptionResult(
                    reference,
                    TranscriptionOutcome.BACKEND_FAILED,
                    source_media=audio_media,
                    detail=str(exc),
                    metadata=exc.metadata,
                )
            )
        except Exception as exc:
            logger.exception(
                "Transcription backend failed for %s:%s",
                reference.session_id,
                reference.event_position,
            )
            return self._log_result(
                TranscriptionResult(
                    reference,
                    TranscriptionOutcome.BACKEND_FAILED,
                    source_media=audio_media,
                    detail=str(exc),
                )
            )

        transcript = run.text.strip()
        if not transcript:
            return self._log_result(
                TranscriptionResult(
                    reference,
                    TranscriptionOutcome.EMPTY_TRANSCRIPT,
                    source_media=audio_media,
                    metadata=run.metadata,
                )
            )

        # Point of no return: from here the overlay write must complete and be
        # reported truthfully. _run_to_completion keeps a late cancellation from
        # producing a CANCELLED result while the write is committing.
        write_task: asyncio.Task[TranscriptUpsertResult] = asyncio.ensure_future(
            asyncio.to_thread(
                self._transcripts.upsert_transcript,
                reference,
                transcript,
                TranscriptSource.GENERATED,
            )
        )
        upsert = await _run_to_completion(write_task)
        if not upsert.accepted:
            return self._log_result(
                TranscriptionResult(
                    reference,
                    TranscriptionOutcome.TRANSCRIPT_REJECTED,
                    source_media=audio_media,
                    detail=upsert.status.value,
                    metadata=run.metadata,
                )
            )

        return self._log_result(
            TranscriptionResult(
                reference,
                TranscriptionOutcome.TRANSCRIBED,
                source_media=audio_media,
                transcript=transcript,
                metadata=run.metadata,
            )
        )

    def _log_result(self, result: TranscriptionResult) -> TranscriptionResult:
        metadata = result.metadata
        model = metadata.model if metadata is not None else "-"
        reasoning = metadata.reasoning if metadata is not None else "-"
        options = _format_options(metadata.options) if metadata is not None else "-"
        logger.info(
            "Transcription %s for %s:%s "
            "(model=%s, reasoning=%s, options=%s, media=%s)%s",
            result.outcome.value,
            result.reference.session_id,
            result.reference.event_position,
            model,
            reasoning,
            options,
            ",".join(result.source_media) or "-",
            f": {result.detail}" if result.detail else "",
        )
        return result
