"""Shows each restored sentence in the chat and speaks it verbatim, one at a
time and in order. The microphone stays paused for the whole answer."""

from __future__ import annotations

from collections.abc import AsyncIterator

from jarvis.personal_proxy.answer_voice import AnswerVoice
from jarvis.personal_proxy.restoration_result import RestoredSentence
from jarvis.personal_proxy.service_blocks import answer_block_of
from jarvis.personal_proxy.service_reporter import Reporter


class AnswerPresenter:
    def __init__(self, reporter: Reporter, voice: AnswerVoice) -> None:
        self._reporter = reporter
        self._voice = voice

    async def present(self, sentences: AsyncIterator[RestoredSentence]) -> None:
        async with self._voice.session() as session:
            try:
                async for sentence in sentences:
                    await self._reporter.post(answer_block_of(sentence))
                    await session.say(sentence.text)
                    await self._reporter.report_problems(session)
            finally:
                await _close(sentences)
        await self._reporter.report_problems(session)


async def _close(sentences: AsyncIterator[RestoredSentence]) -> None:
    close = getattr(sentences, "aclose", None)
    if close is not None:
        await close()
