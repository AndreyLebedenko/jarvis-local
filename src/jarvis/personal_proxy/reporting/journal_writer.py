"""Keeps the exchange of the personal proxy in the Journal.

A tee over the chat sink: every block goes to the real sink first, then the
ones that belong in the Journal are written through the recorder. The service
stays journal-free and never sees a persistence failure. The dry-run block, and
with it the mapping, is never written, and neither is the external answer
before its placeholders were restored. Nothing taken from a request appears in
a log line."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from jarvis.journal.events import JSONValue
from jarvis.personal_proxy.common.response_mode import TEXT_MODE
from jarvis.personal_proxy.confirmation.confirmation_blocks import HeardBlock, SentBlock
from jarvis.personal_proxy.reporting.notice_class import notice_class
from jarvis.personal_proxy.reporting.service_blocks import (
    AnswerBlock,
    AnswerCompleteBlock,
    NoticeBlock,
    NoticeKind,
    RequestSourceBlock,
    ServiceBlock,
)
from jarvis.personal_proxy.reporting.service_ports import ProxyChatSink
from jarvis.personal_proxy.restoration.restoration_result import RestorationMethod

_ANSWER_ENDED_EARLY = frozenset({NoticeKind.INTERRUPTED, NoticeKind.ANSWER_INCOMPLETE})
_NO_SOURCE = RequestSourceBlock(None, None)


class ProxyExchangeRecorder(Protocol):
    async def record_proxy_heard(
        self,
        text: str,
        *,
        decision: str,
        doubt_kinds: tuple[str, ...],
        wav_bytes: bytes | None = None,
        raw_transcript: str | None = None,
    ) -> None: ...

    async def record_proxy_sent(
        self, text: str, *, message_count: int, forced: bool = False
    ) -> None: ...

    async def record_proxy_answer(
        self,
        text: str,
        *,
        methods: tuple[str, ...],
        unresolved_placeholders: bool,
        incomplete: bool,
        response_mode: str,
        spoken_derivative: str | None = None,
    ) -> None: ...

    async def record_proxy_notice(self, kind: str, detail: JSONValue) -> None: ...

    def end_session(self) -> None: ...


@dataclass
class _AnswerBuffer:
    sentences: list[str] = field(default_factory=list, repr=False)
    methods: list[RestorationMethod] = field(default_factory=list)
    unresolved: bool = False


class ProxyJournalWriter:
    def __init__(
        self,
        inner: ProxyChatSink,
        recorder: ProxyExchangeRecorder,
        *,
        dry_run: bool,
        logger: logging.Logger | None = None,
    ) -> None:
        self._inner = inner
        self._recorder = recorder
        self._dry_run = dry_run
        self._logger = logger or logging.getLogger(__name__)
        self._source = _NO_SOURCE
        self._answer: _AnswerBuffer | None = None
        self._response_mode = TEXT_MODE

    def __repr__(self) -> str:
        return f"ProxyJournalWriter(dry_run={self._dry_run})"

    async def post(self, block: ServiceBlock) -> None:
        await self._inner.post(block)
        if self._dry_run:
            return
        await self._guarded(self._persist(block))

    async def close(self) -> None:
        """Writes the answer that was still being shown, as incomplete."""
        await self._guarded(self._flush_answer(incomplete=True))

    async def start_new_session(
        self, still_allowed: Callable[[], bool] = lambda: True
    ) -> bool:
        """What is still held belongs to the session that ends here; the next
        request opens the new one. The flush may yield, so `still_allowed` is
        asked again after it and the session is kept when it says no."""
        await self._guarded(self._flush_answer(incomplete=True))
        if not still_allowed():
            return False
        self._source = _NO_SOURCE
        self._response_mode = TEXT_MODE
        self._recorder.end_session()
        return True

    async def _guarded(self, work: Awaitable[None]) -> None:
        try:
            await work
        except Exception as error:
            self._logger.warning("Journal write failed: %s", type(error).__name__)

    async def _persist(self, block: ServiceBlock) -> None:
        if isinstance(block, RequestSourceBlock):
            await self._flush_answer(incomplete=True)
            self._source = block
            self._response_mode = block.response_mode
        elif isinstance(block, HeardBlock):
            await self._record_heard(block)
        elif isinstance(block, SentBlock):
            await self._recorder.record_proxy_sent(
                block.text, message_count=len(block.messages), forced=block.forced
            )
        elif isinstance(block, AnswerBlock):
            self._buffer(block)
        elif isinstance(block, AnswerCompleteBlock):
            await self._flush_answer(
                incomplete=False, spoken_derivative=block.spoken_derivative
            )
        elif isinstance(block, NoticeBlock):
            await self._record_notice(block)

    async def _record_heard(self, block: HeardBlock) -> None:
        source, self._source = self._source, _NO_SOURCE
        await self._recorder.record_proxy_heard(
            block.heard_text,
            decision=block.decision.value,
            doubt_kinds=tuple(doubt.kind.value for doubt in block.doubts),
            wav_bytes=source.voice_wav,
            raw_transcript=source.raw_transcript,
        )

    async def _record_notice(self, block: NoticeBlock) -> None:
        if block.kind in _ANSWER_ENDED_EARLY:
            await self._flush_answer(incomplete=True)
        classified = notice_class(block)
        await self._recorder.record_proxy_notice(
            str(classified["kind"]), classified["detail"]
        )

    def _buffer(self, block: AnswerBlock) -> None:
        if self._answer is None:
            self._answer = _AnswerBuffer()
        self._answer.sentences.append(block.text)
        self._answer.methods.append(block.method)
        self._answer.unresolved = (
            self._answer.unresolved or block.unresolved_placeholders
        )

    async def _flush_answer(
        self, *, incomplete: bool, spoken_derivative: str | None = None
    ) -> None:
        answer, self._answer = self._answer, None
        if answer is None:
            return
        await self._recorder.record_proxy_answer(
            " ".join(answer.sentences),
            methods=tuple(method.value for method in answer.methods),
            unresolved_placeholders=answer.unresolved,
            incomplete=incomplete,
            response_mode=self._response_mode,
            spoken_derivative=spoken_derivative,
        )
