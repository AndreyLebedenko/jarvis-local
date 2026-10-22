"""PersonalProxyService: the router, the worker, and the lifecycle of the
personal-proxy pipeline.

Pure asyncio over ports and injected stage callables; it imports no backend,
engine, HTTP client, application module, or journal. `submit` only enqueues. A
router task reads the inbox: while a confirmation exchange is pending every item
is an answer attempt (a rejected one is dropped, never a request); otherwise the
item joins a bounded FIFO of requests. One worker takes requests one at a time,
so there is never more than one external request, which the locality seam needs.

Not thread-safe: `submit`, `interrupt`, `start` and `close` belong to the event
loop of the service; other threads marshal onto it. The service writes no log
line, and nothing taken from a request appears in an exception or a repr."""

from __future__ import annotations

import asyncio
from contextlib import suppress

from jarvis.core.config import PersonalProxySettings
from jarvis.personal_proxy.answer_presenter import AnswerPresenter
from jarvis.personal_proxy.answer_transcriber import StageAnswerTranscriber
from jarvis.personal_proxy.answer_voice import RESUME_LIMIT_SECONDS, AnswerVoice
from jarvis.personal_proxy.check_result import CheckedTranscript
from jarvis.personal_proxy.confirmation_exchange import ConfirmationExchange
from jarvis.personal_proxy.confirmation_outcome import ExchangeOutcome, ExchangeState
from jarvis.personal_proxy.confirmation_ports import (
    ExchangeSpeaker,
    MicrophoneGate,
    Sleep,
)
from jarvis.personal_proxy.locality import LocalityReporter
from jarvis.personal_proxy.pipeline_stages import PipelineStages
from jarvis.personal_proxy.proxy_inbox import InboxItem, ProxyInbox, TypedText
from jarvis.personal_proxy.request_pipeline import PipelineParts, RequestPipeline
from jarvis.personal_proxy.service_blocks import NoticeBlock, NoticeKind
from jarvis.personal_proxy.service_ports import LanguageProvider, ProxyChatSink
from jarvis.personal_proxy.service_reporter import Reporter

INBOX_CAPACITY = 8
BUSY_POST_LIMIT_SECONDS = 2.0
REQUEST_QUEUE_CAPACITY = 4


def _running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


class ServiceClosedError(Exception):
    def __init__(self) -> None:
        super().__init__("the personal proxy service is closed")


class PersonalProxyService:
    def __init__(
        self,
        *,
        stages: PipelineStages,
        sink: ProxyChatSink,
        speaker: ExchangeSpeaker,
        microphone: MicrophoneGate,
        locality: LocalityReporter,
        language: LanguageProvider,
        settings: PersonalProxySettings,
        topics_text: str,
        sleep: Sleep = asyncio.sleep,
        queue_capacity: int = REQUEST_QUEUE_CAPACITY,
        inbox_capacity: int = INBOX_CAPACITY,
        resume_limit_seconds: float = RESUME_LIMIT_SECONDS,
    ) -> None:
        self._stages = stages
        self._sink = sink
        self._speaker = speaker
        self._microphone = microphone
        self._language = language
        self._settings = settings
        self._sleep = sleep
        self._voice = AnswerVoice(
            speaker=speaker,
            microphone=microphone,
            language=language,
            resume_limit_seconds=resume_limit_seconds,
        )
        self._reporter = Reporter(sink, self._voice, language)
        self._pipeline = RequestPipeline(
            PipelineParts(
                stages=stages,
                reporter=self._reporter,
                presenter=AnswerPresenter(self._reporter, self._voice),
                confirm=self._confirm,
                locality=locality,
                topics_text=topics_text,
                dry_run=settings.dry_run,
            )
        )
        self._inbox = ProxyInbox(inbox_capacity)
        self._requests: asyncio.Queue[InboxItem] = asyncio.Queue(queue_capacity)
        self._unrouted = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._router: asyncio.Task[None] | None = None
        self._worker: asyncio.Task[None] | None = None
        self._current: asyncio.Task[None] | None = None
        self._exchange: ConfirmationExchange | None = None
        self._interrupted = False
        self._closed = False
        self._close_task: asyncio.Future[None] | None = None
        self._warm_lock = asyncio.Lock()
        self._warm = False

    def __repr__(self) -> str:
        return f"PersonalProxyService(closed={self._closed})"

    @property
    def idle(self) -> bool:
        """No item waits in the inbox or the queue and no request is running."""
        return self._unrouted == 0 and self._requests.empty() and self._current is None

    def start(self) -> None:
        if self._closed:
            raise ServiceClosedError
        if self._router is None:
            self._loop = asyncio.get_running_loop()
            self._router = asyncio.create_task(self._route())
            self._worker = asyncio.create_task(self._work())

    def submit(self, item: InboxItem) -> None:
        """Enqueues and returns at once. A full inbox raises `InboxFullError`
        and drops the item."""
        if self._closed:
            raise ServiceClosedError
        self._inbox.submit(item)
        self._unrouted += 1

    async def warm_up(self) -> None:
        async with self._warm_lock:
            if not self._warm:
                await self._stages.warm_up()
                self._warm = True

    def interrupt(self) -> None:
        """A pending question is answered "no" (it ends as CANCELLED); otherwise
        the request in flight is cancelled. Safe to call from any thread: a call
        from outside the service's loop is marshalled onto it. Before `start`
        there is nothing to interrupt."""
        loop = self._loop
        if loop is None:
            return
        if _running_loop() is loop:
            self._interrupt_on_loop()
        else:
            with suppress(RuntimeError):
                loop.call_soon_threadsafe(self._interrupt_on_loop)

    def _interrupt_on_loop(self) -> None:
        exchange = self._pending_exchange()
        if exchange is not None:
            exchange.cancel()
        elif self._current is not None and not self._current.done():
            self._interrupted = True
            self._current.cancel()

    async def close(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.ensure_future(self._shutdown())
        await asyncio.shield(self._close_task)

    async def _shutdown(self) -> None:
        self._closed = True
        tasks = [task for task in (self._router, self._worker) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._voice.stop()

    def _pending_exchange(self) -> ConfirmationExchange | None:
        exchange = self._exchange
        if exchange is not None and exchange.state is not ExchangeState.DONE:
            return exchange
        return None

    async def _confirm(self, checked: CheckedTranscript) -> ExchangeOutcome:
        exchange = ConfirmationExchange(
            sink=self._sink,
            speaker=self._speaker,
            microphone=self._microphone,
            transcriber=StageAnswerTranscriber(self._stages.transcribe),
            language=self._language(),
            timeout_seconds=self._settings.confirmation_timeout_seconds,
            sleep=self._sleep,
        )
        self._exchange = exchange
        try:
            return await exchange.run(checked)
        finally:
            self._exchange = None

    async def _route(self) -> None:
        while True:
            item = await self._inbox.next_item()
            try:
                await self._dispatch(item)
            except Exception:
                pass
            finally:
                self._unrouted -= 1

    async def _dispatch(self, item: InboxItem) -> None:
        exchange = self._pending_exchange()
        if exchange is None:
            await self._enqueue(item)
        elif isinstance(item, TypedText):
            exchange.submit_typed(item.text)
        else:
            exchange.submit_spoken(item.wav)

    async def _enqueue(self, item: InboxItem) -> None:
        try:
            self._requests.put_nowait(item)
        except asyncio.QueueFull:
            await self._announce_busy()

    async def _announce_busy(self) -> None:
        """Straight to the sink and bounded, so that a sink that hangs cannot
        stop the router from delivering the answer to a pending question."""
        notice = NoticeBlock(NoticeKind.BUSY)
        with suppress(Exception):
            await asyncio.wait_for(self._sink.post(notice), BUSY_POST_LIMIT_SECONDS)

    async def _work(self) -> None:
        while True:
            item = await self._requests.get()
            await self._run_one(item)

    async def _run_one(self, item: InboxItem) -> None:
        task = asyncio.ensure_future(self._handle(item))
        self._current = task
        try:
            await asyncio.wait({task})
        finally:
            if not task.done():
                task.cancel()
                await asyncio.wait({task})
            self._current = None
        await self._after(task)

    async def _after(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()
            return
        interrupted, self._interrupted = self._interrupted, False
        if interrupted:
            await self._reporter.quiet_notice(NoticeKind.INTERRUPTED)

    async def _handle(self, item: InboxItem) -> None:
        try:
            await self.warm_up()
            await self._pipeline.run(item)
        except Exception:
            await self._reporter.quiet_notice(NoticeKind.INTERNAL_ERROR)
