"""Shows each restored sentence in the chat as soon as it arrives and speaks it
(as received unless a speech preparation is given), one at a time and in
order. The answer is read by a task of its own, so speaking never holds up
showing it, and the answer is closed as soon as its
last sentence arrived. When the answer fails, the incomplete notice is shown at
that moment and spoken after the sentences already shown. The microphone stays
paused for the whole answer.

`present_rendered` (Text+Voice) shows the sentences the same way but speaks
nothing until the answer is complete: the whole answer goes to a render
callable, and its text is spoken instead. When the render fails, times out or
yields nothing, the shown sentences are spoken as in `present`. The answer is
closed after the render and carries the spoken text for the Journal; an
interrupt during the render still closes it, without one."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress

from jarvis.personal_proxy.answer.answer_reporter import Reporter
from jarvis.personal_proxy.answer.answer_voice import AnswerVoice
from jarvis.personal_proxy.answer.speech_preparation import (
    SpeechPreparation,
    as_received,
    cleaned_for_voice,
)
from jarvis.personal_proxy.common.visible_text import has_visible_text
from jarvis.personal_proxy.external.external_error import error_kind_of
from jarvis.personal_proxy.reporting.service_blocks import (
    AnswerCompleteBlock,
    NoticeBlock,
    NoticeKind,
    answer_block_of,
)
from jarvis.personal_proxy.restoration.restoration_result import RestoredSentence
from jarvis.personal_proxy.restoration.restoration_sentences import (
    BoundedSentenceBuffer,
)

Arrival = RestoredSentence | NoticeBlock | None
SpokenRender = Callable[[str], Awaitable[str]]


class AnswerPresenter:
    def __init__(self, reporter: Reporter, voice: AnswerVoice) -> None:
        self._reporter = reporter
        self._voice = voice

    async def present(
        self,
        sentences: AsyncIterator[RestoredSentence],
        prepare_speech: SpeechPreparation = as_received,
    ) -> None:
        arrivals: asyncio.Queue[Arrival] = asyncio.Queue()
        reader = asyncio.ensure_future(self._show_arriving(sentences, arrivals))
        try:
            async with self._voice.session() as session:
                while isinstance(arrival := await arrivals.get(), RestoredSentence):
                    await session.say(prepare_speech(arrival.text))
                    await self._reporter.report_problems(session)
            await self._reporter.report_problems(session)
            if arrival is not None:
                with suppress(Exception):
                    await self._reporter.speak_notice(arrival)
        except Exception:
            if not _failure_was_reported(reader):
                raise
        finally:
            await _stop(reader)
            await _close(sentences)

    async def present_rendered(
        self,
        sentences: AsyncIterator[RestoredSentence],
        render: SpokenRender | None,
        prepare_speech: SpeechPreparation = cleaned_for_voice,
    ) -> None:
        arrivals: asyncio.Queue[Arrival] = asyncio.Queue()
        reader = asyncio.ensure_future(
            self._show_arriving(sentences, arrivals, announce_complete=False)
        )
        shown: list[str] = []
        ended_complete = False
        closed = False
        try:
            async with self._voice.session() as session:
                while isinstance(arrival := await arrivals.get(), RestoredSentence):
                    shown.append(arrival.text)
                lines = [prepare_speech(text) for text in shown]
                ended_complete = arrival is None
                if ended_complete and shown:
                    await session.hold_microphone()
                    spoken = await _rendered(render, shown)
                    await self._close_answer(spoken)
                    closed = True
                    if spoken is not None:
                        lines = _spoken_lines(spoken)
                for line in lines:
                    await session.say(line)
                    await self._reporter.report_problems(session)
            await self._reporter.report_problems(session)
            if arrival is not None:
                with suppress(Exception):
                    await self._reporter.speak_notice(arrival)
        except Exception:
            if not _failure_was_reported(reader):
                raise
        finally:
            if ended_complete and not closed:
                await self._close_answer(None)
            await _stop(reader)
            await _close(sentences)

    async def _close_answer(self, spoken: str | None) -> None:
        with suppress(Exception):
            await self._reporter.post(AnswerCompleteBlock(spoken))

    async def _show_arriving(
        self,
        sentences: AsyncIterator[RestoredSentence],
        arrivals: asyncio.Queue[Arrival],
        *,
        announce_complete: bool = True,
    ) -> NoticeBlock | None:
        try:
            async for sentence in sentences:
                await self._reporter.post(answer_block_of(sentence))
                arrivals.put_nowait(sentence)
        except Exception as error:
            notice = NoticeBlock(NoticeKind.ANSWER_INCOMPLETE, error_kind_of(error))
            with suppress(Exception):
                await self._reporter.post(notice)
            arrivals.put_nowait(notice)
            return notice
        if announce_complete:
            with suppress(Exception):
                await self._reporter.post(AnswerCompleteBlock())
        arrivals.put_nowait(None)
        return None


async def _rendered(render: SpokenRender | None, shown: list[str]) -> str | None:
    if render is None:
        return None
    try:
        reply = await render(" ".join(shown))
    except Exception:
        return None
    spoken = cleaned_for_voice(reply)
    return spoken if has_visible_text(spoken) else None


def _spoken_lines(spoken: str) -> list[str]:
    buffer = BoundedSentenceBuffer()
    lines = buffer.feed(spoken)
    tail = buffer.flush()
    return lines if tail is None else [*lines, tail]


def _failure_was_reported(reader: asyncio.Future[NoticeBlock | None]) -> bool:
    return reader.done() and not reader.cancelled() and reader.result() is not None


async def _stop(reader: asyncio.Future[NoticeBlock | None]) -> None:
    reader.cancel()
    await asyncio.wait({reader})


async def _close(sentences: AsyncIterator[RestoredSentence]) -> None:
    close = getattr(sentences, "aclose", None)
    if close is not None:
        await close()
