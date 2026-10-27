"""Shows each restored sentence in the chat as soon as it arrives and speaks it
verbatim, one at a time and in order. The answer is read by a task of its own,
so speaking never holds up showing it, and the answer is closed as soon as its
last sentence arrived. When the answer fails, the incomplete notice is shown at
that moment and spoken after the sentences already shown. The microphone stays
paused for the whole answer."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress

from jarvis.personal_proxy.answer.answer_reporter import Reporter
from jarvis.personal_proxy.answer.answer_voice import AnswerVoice
from jarvis.personal_proxy.external.external_error import error_kind_of
from jarvis.personal_proxy.reporting.service_blocks import (
    AnswerCompleteBlock,
    NoticeBlock,
    NoticeKind,
    answer_block_of,
)
from jarvis.personal_proxy.restoration.restoration_result import RestoredSentence

Arrival = RestoredSentence | NoticeBlock | None


class AnswerPresenter:
    def __init__(self, reporter: Reporter, voice: AnswerVoice) -> None:
        self._reporter = reporter
        self._voice = voice

    async def present(self, sentences: AsyncIterator[RestoredSentence]) -> None:
        arrivals: asyncio.Queue[Arrival] = asyncio.Queue()
        reader = asyncio.ensure_future(self._show_arriving(sentences, arrivals))
        try:
            async with self._voice.session() as session:
                while isinstance(arrival := await arrivals.get(), RestoredSentence):
                    await session.say(arrival.text)
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

    async def _show_arriving(
        self,
        sentences: AsyncIterator[RestoredSentence],
        arrivals: asyncio.Queue[Arrival],
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
        with suppress(Exception):
            await self._reporter.post(AnswerCompleteBlock())
        arrivals.put_nowait(None)
        return None


def _failure_was_reported(reader: asyncio.Future[NoticeBlock | None]) -> bool:
    return reader.done() and not reader.cancelled() and reader.result() is not None


async def _stop(reader: asyncio.Future[NoticeBlock | None]) -> None:
    reader.cancel()
    await asyncio.wait({reader})


async def _close(sentences: AsyncIterator[RestoredSentence]) -> None:
    close = getattr(sentences, "aclose", None)
    if close is not None:
        await close()
