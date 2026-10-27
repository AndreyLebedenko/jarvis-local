"""Posts notices to the chat and speaks the fixed sentence that goes with them.
Nothing here takes text from a request except the refusal reason, which goes
into the block and nowhere else."""

from __future__ import annotations

from contextlib import suppress

from jarvis.personal_proxy.answer.answer_voice import AnswerVoice, SpeechSession
from jarvis.personal_proxy.reporting.service_blocks import (
    NoticeBlock,
    NoticeDetail,
    NoticeKind,
    ServiceBlock,
)
from jarvis.personal_proxy.reporting.service_ports import (
    LanguageProvider,
    ProxyChatSink,
)
from jarvis.personal_proxy.reporting.service_texts import spoken_notice


class Reporter:
    def __init__(
        self, sink: ProxyChatSink, voice: AnswerVoice, language: LanguageProvider
    ) -> None:
        self._sink = sink
        self._voice = voice
        self._language = language

    async def post(self, block: ServiceBlock) -> None:
        await self._sink.post(block)

    async def notice(
        self,
        kind: NoticeKind,
        detail: NoticeDetail = None,
        reason: str = "",
        *,
        forceable: bool = False,
    ) -> None:
        block = NoticeBlock(kind, detail, reason, forceable)
        await self._sink.post(block)
        await self.speak_notice(block)

    async def speak_notice(self, block: NoticeBlock) -> None:
        sentence = spoken_notice(block, self._language())
        if sentence is not None:
            await self.speak(sentence)

    async def quiet_notice(self, kind: NoticeKind, detail: NoticeDetail = None) -> None:
        """For the failure paths: a notice that cannot be delivered is dropped."""
        with suppress(Exception):
            await self.notice(kind, detail)

    async def speak(self, sentence: str) -> None:
        async with self._voice.session() as session:
            await session.say(sentence)
        await self.report_problems(session)

    async def report_problems(self, session: SpeechSession) -> None:
        for kind in session.take_problems():
            await self._sink.post(NoticeBlock(kind))
