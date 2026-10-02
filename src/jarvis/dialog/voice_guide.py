"""The voice guide: turns an accepted `speak` request into speech and one
journal event.

A bounded FIFO queue with one worker. For each request the worker produces the
text to speak (a guide pass over the canvas, the canvas itself, or the caller's
own spoken text), plays it through the app's ReplayPlayer, and journals the
outcome. It runs outside the Orchestrator turn lifecycle: the guide pass uses
the bus-free OllamaBackend.iter_chat(), never chat(), whose ResponseToken events
would be taken for a user turn, and it never has tools.

Control is explicit data, not task cancellation. Each request records what
happened to it (its guide pass, the ReplayRun it started, an interrupt request)
and one function maps those facts to the journal status. The service is
started with start() and ended with close(), which journals every request it
ever accepted.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from jarvis.audio.language_segments import text_language
from jarvis.audio.replay import PlayItem, ReplayOutcome, ReplayRun, TextReply
from jarvis.audio.speech_language import (
    TtsLanguageMode,
    resolve_speech_language,
    speech_language_contract,
)
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    VOICE_GUIDE_PROFILE,
    GenerationOptions,
    GenerationSettings,
    ResponseSettings,
)
from jarvis.core.lifecycle import SpeechLanguage
from jarvis.dialog.backend import LENGTH_CAP_DONE_REASON
from jarvis.dialog.canvas_speech import compose_canvas_speech_messages
from jarvis.dialog.thinking_mode import ReasoningLevel
from jarvis.journal.external_canvas import (
    ExternalCanvasCaller,
    SpeechOrigin,
    SpeechStatus,
)

logger = logging.getLogger(__name__)


class VoiceGuideRejection(Enum):
    QUEUE_FULL = "queue_full"
    CLOSED = "closed"


@dataclass(frozen=True)
class VoiceGuideRequest:
    canvas: str
    spoken_text: str | None = None
    guidance: str | None = None
    caller: ExternalCanvasCaller | None = None


@dataclass(frozen=True)
class VoiceGuideAccepted:
    """`position` is 1-based among the requests not yet finished, the one in
    flight included: 1 means nothing is ahead of it. `speech_origin` is what
    the request will be spoken from."""

    position: int
    speech_origin: SpeechOrigin


@dataclass(frozen=True)
class VoiceGuideRejected:
    reason: VoiceGuideRejection


EnqueueResult = VoiceGuideAccepted | VoiceGuideRejected


@dataclass(frozen=True)
class VoiceGuideQueueChanged:
    """Published on every queue change. `length` counts unfinished requests;
    `in_flight` says one of them is being generated or spoken right now."""

    length: int
    in_flight: bool


class GuideBackend(Protocol):
    def iter_chat(
        self,
        messages: Sequence[dict[str, Any]],
        images_b64: Sequence[str] | None = None,
        reasoning_level: ReasoningLevel = ReasoningLevel.OFF,
        tools: Sequence[dict[str, object]] | None = None,
        *,
        options: GenerationOptions,
    ) -> AsyncIterator[dict[str, Any]]: ...


class GuidePlayer(Protocol):
    def start_run(self, items: list[PlayItem]) -> ReplayRun | ReplayOutcome: ...

    async def wait_for_pending(self) -> None: ...


class GuideRecorder(Protocol):
    async def record_external_canvas(
        self,
        canvas: str,
        *,
        speech_origin: SpeechOrigin,
        speech_status: SpeechStatus,
        caller: ExternalCanvasCaller | None = None,
        guidance: str | None = None,
        spoken_derivative: str | None = None,
        spoken_derivative_truncated: bool = False,
    ) -> None: ...


def _new_signal() -> asyncio.Future[None]:
    return asyncio.get_running_loop().create_future()


@dataclass
class _Item:
    """One request on its way through the service, with what happened to it.
    The journal status is derived from these facts alone (see _status_of)."""

    request: VoiceGuideRequest
    origin: SpeechOrigin
    interrupt_signal: asyncio.Future[None] = field(default_factory=_new_signal)
    guide_parts: list[str] = field(default_factory=list)
    guide_truncated: bool = False
    guide_task: asyncio.Task[str] | None = None
    guide_stopped: bool = False
    playback: ReplayRun | ReplayOutcome | None = None
    failure: Exception | None = None

    @property
    def interrupted(self) -> bool:
        return self.interrupt_signal.done()

    @property
    def derivative(self) -> str | None:
        if self.origin is SpeechOrigin.CALLER:
            text = self.request.spoken_text
        elif self.origin is SpeechOrigin.DERIVATIVE:
            text = "".join(self.guide_parts)
        else:
            return None
        return text if text and text.strip() else None

    @property
    def derivative_truncated(self) -> bool:
        return self.guide_truncated and self.derivative is not None


def _status_of(item: _Item) -> SpeechStatus:
    """The journal status of a settled item (its guide pass and its run have
    ended), from what happened to it, never from who noticed an interrupt.

    A run that finished before an interrupt reached it is spoken or failed by
    its own result; only a run that ended by cancellation is interrupted. With
    no run at all, only a stop can explain an item that neither failed nor was
    muted."""
    playback = item.playback
    if playback is ReplayOutcome.DISABLED:
        return SpeechStatus.MUTED
    if playback is ReplayOutcome.EMPTY:
        return SpeechStatus.FAILED
    if isinstance(playback, ReplayRun):
        if playback.cancelled:
            return SpeechStatus.INTERRUPTED
        return SpeechStatus.SPOKEN if item.failure is None else SpeechStatus.FAILED
    if item.failure is not None:
        return SpeechStatus.FAILED
    return SpeechStatus.INTERRUPTED


def _consume_outcome(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()


def _log_failure(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.error("Voice guide background task failed", exc_info=task.exception())


class VoiceGuideService:
    """`capacity` bounds the unfinished requests, the one in flight included,
    so acceptance does not depend on how far the worker has got.

    Call start() once inside the running loop and close() to end. close() is
    the orderly shutdown: it stops the item in flight, lets the worker journal
    it, journals every other accepted request `skipped`, and only then
    returns, so no accepted request goes unjournaled."""

    def __init__(
        self,
        *,
        backend: GuideBackend,
        player: GuidePlayer,
        recorder: GuideRecorder,
        bus: EventBus,
        generation_settings: GenerationSettings,
        response_settings: ResponseSettings,
        language_mode: Callable[[], TtsLanguageMode],
        canvas_only_origin: SpeechOrigin,
        on_error: Callable[[], Awaitable[None]],
        capacity: int,
    ) -> None:
        if canvas_only_origin is SpeechOrigin.CALLER:
            raise ValueError("canvas_only_origin must be derivative or verbatim")
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self._backend = backend
        self._player = player
        self._recorder = recorder
        self._bus = bus
        self._generation = generation_settings
        self._response_settings = response_settings
        self._language_mode = language_mode
        self._canvas_only_origin = canvas_only_origin
        self._on_error = on_error
        self._capacity = capacity
        self._pending: deque[_Item] = deque()
        self._dropped: deque[_Item] = deque()
        self._closed = False
        self._current: _Item | None = None
        self._worker: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._wakeup = asyncio.Event()
        self._background: set[asyncio.Task[None]] = set()

    @property
    def queue_length(self) -> int:
        return len(self._pending) + (1 if self._current is not None else 0)

    def start(self) -> None:
        if self._worker is not None:
            raise RuntimeError("the voice guide service is already started")
        if self._closed:
            raise RuntimeError("the voice guide service is closed")
        self._worker = asyncio.get_running_loop().create_task(self._serve_forever())
        self._worker.add_done_callback(self._on_worker_done)

    def enqueue(self, request: VoiceGuideRequest) -> EnqueueResult:
        if self._closed:
            return VoiceGuideRejected(VoiceGuideRejection.CLOSED)
        if self.queue_length >= self._capacity:
            return VoiceGuideRejected(VoiceGuideRejection.QUEUE_FULL)
        origin = self._origin_of(request)
        self._pending.append(_Item(request, origin))
        self._queue_changed()
        return VoiceGuideAccepted(self.queue_length, origin)

    def interrupt(self) -> None:
        """Stops the item in flight and drops every queued one. The journal
        writes happen on the worker, in order."""
        if self._closed:
            return
        self._stop_everything()

    async def close(self) -> None:
        if self._close_task is None:
            self._closed = True
            self._stop_everything()
            self._close_task = asyncio.get_running_loop().create_task(self._shutdown())
        await asyncio.shield(self._close_task)

    def _stop_everything(self) -> None:
        if self._current is not None:
            self._request_interrupt(self._current)
        self._dropped.extend(self._pending)
        self._pending.clear()
        self._queue_changed()

    def _request_interrupt(self, item: _Item) -> None:
        if item.interrupted:
            return
        item.interrupt_signal.set_result(None)
        guide = item.guide_task
        if guide is not None and not guide.done():
            item.guide_stopped = True
            guide.cancel()
        if isinstance(item.playback, ReplayRun):
            item.playback.cancel()

    async def _shutdown(self) -> None:
        if self._worker is not None:
            await asyncio.wait({self._worker})
        while self._dropped:
            await self._journal(self._dropped.popleft(), SpeechStatus.SKIPPED)
        self._current = None
        self._queue_changed()
        if self._background:
            await asyncio.wait(set(self._background))

    def _on_worker_done(self, worker: asyncio.Task[None]) -> None:
        self._closed = True
        if not worker.cancelled() and worker.exception() is not None:
            logger.error("Voice guide worker crashed", exc_info=worker.exception())

    async def _serve_forever(self) -> None:
        while True:
            if self._dropped:
                await self._journal(self._dropped.popleft(), SpeechStatus.SKIPPED)
            elif self._pending:
                await self._serve(self._pending.popleft())
            elif self._closed:
                return
            else:
                self._wakeup.clear()
                await self._wakeup.wait()

    def _origin_of(self, request: VoiceGuideRequest) -> SpeechOrigin:
        if request.spoken_text is not None:
            return SpeechOrigin.CALLER
        return self._canvas_only_origin

    async def _serve(self, item: _Item) -> None:
        self._current = item
        self._queue_changed()
        try:
            await self._speak(item)
        except Exception as failure:
            self._record_failure(item, failure)
        status = _status_of(item)
        await self._journal(item, status)
        self._current = None
        self._queue_changed()
        if status is SpeechStatus.FAILED:
            await self._cue_error()

    def _record_failure(self, item: _Item, failure: Exception) -> None:
        if item.failure is None:
            item.failure = failure
            logger.error("Voice guide request failed", exc_info=failure)

    async def _speak(self, item: _Item) -> None:
        request = item.request
        speech_language = resolve_speech_language(
            self._language_mode(), text_language(request.canvas)
        )
        text = await self._text_to_speak(item, speech_language)
        if text is not None:
            await self._play(item, TextReply(text, speech_language))

    async def _text_to_speak(
        self, item: _Item, speech_language: SpeechLanguage
    ) -> str | None:
        if item.origin is SpeechOrigin.CALLER:
            assert item.request.spoken_text is not None
            return item.request.spoken_text
        if item.origin is SpeechOrigin.VERBATIM:
            return item.request.canvas
        if item.interrupted:
            return None
        item.guide_task = asyncio.get_running_loop().create_task(
            self._guide_pass(item, speech_language)
        )
        await asyncio.wait({item.guide_task})
        return self._finished_guide_text(item)

    def _finished_guide_text(self, item: _Item) -> str | None:
        task = item.guide_task
        assert task is not None and task.done()
        if task.cancelled():
            return None
        failure = task.exception()
        if failure is None:
            return task.result()
        if not item.guide_stopped:
            self._record_failure(item, failure)
        return None

    async def _guide_pass(self, item: _Item, speech_language: SpeechLanguage) -> str:
        profile = self._generation.profile(VOICE_GUIDE_PROFILE)
        messages = compose_canvas_speech_messages(
            profile.prompt,
            speech_language_contract(speech_language, self._response_settings),
            item.request.canvas,
            item.request.guidance,
        )
        chunks = self._backend.iter_chat(
            messages,
            reasoning_level=ReasoningLevel(profile.reasoning),
            tools=None,
            options=self._generation.options_for(VOICE_GUIDE_PROFILE),
        )
        async with contextlib.aclosing(chunks):
            async for chunk in chunks:
                message = chunk.get("message")
                content = message.get("content") if isinstance(message, dict) else None
                if isinstance(content, str) and content:
                    item.guide_parts.append(content)
                if chunk.get("done"):
                    item.guide_truncated = (
                        chunk.get("done_reason") == LENGTH_CAP_DONE_REASON
                    )
                    break
        return "".join(item.guide_parts)

    async def _play(self, item: _Item, reply: TextReply) -> None:
        while True:
            if item.interrupted:
                return
            started = self._player.start_run([reply])
            if started is not ReplayOutcome.BUSY:
                break
            await self._wait_for_other_run(item)
        item.playback = started
        if started is ReplayOutcome.EMPTY:
            logger.warning("Voice guide text has nothing speakable")
        if isinstance(started, ReplayRun):
            await started.wait()

    async def _wait_for_other_run(self, item: _Item) -> None:
        other_run_ended = asyncio.get_running_loop().create_task(
            self._other_run_ended()
        )
        try:
            await asyncio.wait(
                {other_run_ended, item.interrupt_signal},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            other_run_ended.cancel()

    async def _other_run_ended(self) -> None:
        # Unshielded, abandoning this wait would cancel a replay we do not own;
        # shield() then drops the inner failure, hence _consume_outcome.
        pending = asyncio.get_running_loop().create_task(
            self._player.wait_for_pending()
        )
        pending.add_done_callback(_consume_outcome)
        with contextlib.suppress(Exception):
            await asyncio.shield(pending)

    async def _journal(self, item: _Item, status: SpeechStatus) -> None:
        request = item.request
        try:
            await self._recorder.record_external_canvas(
                request.canvas,
                speech_origin=item.origin,
                speech_status=status,
                caller=request.caller,
                guidance=request.guidance,
                spoken_derivative=item.derivative,
                spoken_derivative_truncated=item.derivative_truncated,
            )
        except Exception:
            logger.exception("Voice guide request could not be journaled")

    async def _cue_error(self) -> None:
        try:
            await self._on_error()
        except Exception:
            logger.exception("Voice guide error cue failed")

    def _queue_changed(self) -> None:
        self._wakeup.set()
        event = VoiceGuideQueueChanged(
            length=self.queue_length, in_flight=self._current is not None
        )
        self._run_in_background(self._bus.publish(VoiceGuideQueueChanged, event))

    def _run_in_background(self, work: Coroutine[Any, Any, None]) -> None:
        task = asyncio.get_running_loop().create_task(work)
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        task.add_done_callback(_log_failure)
