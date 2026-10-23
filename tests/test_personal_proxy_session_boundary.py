"""A new session may start only when nothing of the old request can still
reach the Journal: not while an interrupt notice is still being posted, and not
when a request arrives while the old answer is being flushed."""

import asyncio
import types

from _service_fakes import RecordingSink, Rig, until

from jarvis.core.bus import EventBus
from jarvis.core.lifecycle import NewContextReason
from jarvis.personal_proxy.journal_writer import ProxyJournalWriter
from jarvis.personal_proxy.proxy_inbox import TypedText
from jarvis.personal_proxy.proxy_runtime import PersonalProxyRuntime
from jarvis.personal_proxy.proxy_submissions import ProxySubmissions
from jarvis.personal_proxy.restoration_result import RestorationMethod
from jarvis.personal_proxy.service_blocks import AnswerBlock, NoticeBlock, NoticeKind


class SessionRecorder:
    def __init__(self):
        self.session = 1
        self.calls = []

    async def record_proxy_heard(self, *args, **kwargs):
        self.calls.append(("heard", self.session))

    async def record_proxy_sent(self, *args, **kwargs):
        self.calls.append(("sent", self.session))

    async def record_proxy_answer(self, text, **kwargs):
        self.calls.append(("answer", self.session))

    async def record_proxy_notice(self, kind, detail):
        self.calls.append((f"notice {kind}", self.session))

    def end_session(self):
        self.session += 1
        self.calls.append(("session ended", self.session))


async def _noop():
    return None


def _runtime(rig, writer):
    async def dropped():
        return None

    return PersonalProxyRuntime(
        service=rig.service,
        submissions=ProxySubmissions(
            rig.service, text_max_chars=100, report_dropped=dropped
        ),
        bus=EventBus(),
        client=types.SimpleNamespace(aclose=_noop),
        on_new_session=writer.start_new_session,
    )


async def test_the_service_is_not_idle_while_the_interrupt_notice_is_still_posted():
    gate = asyncio.Event()

    class BlockingSink(RecordingSink):
        async def post(self, block):
            if isinstance(block, NoticeBlock) and block.kind is NoticeKind.INTERRUPTED:
                await gate.wait()
            await super().post(block)

    rig = Rig(sink=None)
    rig.sink = BlockingSink(rig.log)
    recorder = SessionRecorder()
    writer = ProxyJournalWriter(rig.sink, recorder, dry_run=False)
    rig.service._sink = writer
    rig.service._reporter._sink = writer
    rig.stages.stream_gate = asyncio.Event()
    runtime = _runtime(rig, writer)
    rig.service.start()
    rig.service.submit(TypedText("one"))
    await until(lambda: rig.stages.streams)
    rig.service.interrupt()
    await until(lambda: rig.service._current is None or rig.service._current.done())
    await asyncio.sleep(0.02)

    idle_during_notice = rig.service.idle
    result = await runtime.start_new_session()
    gate.set()
    await asyncio.sleep(0.05)
    await rig.service.close()

    assert idle_during_notice is False
    assert result.reason is NewContextReason.BUSY
    assert ("session ended", 2) not in recorder.calls
    assert all(session == 1 for _, session in recorder.calls)


async def test_a_request_arriving_during_the_flush_blocks_the_new_session():
    class YieldingRecorder(SessionRecorder):
        flushing = None

        async def record_proxy_answer(self, text, **kwargs):
            await self.flushing()
            await super().record_proxy_answer(text, **kwargs)

    rig = Rig()
    recorder = YieldingRecorder()
    writer = ProxyJournalWriter(RecordingSink([]), recorder, dry_run=False)
    runtime = _runtime(rig, writer)
    rig.service.start()

    async def submit_while_flushing():
        rig.service.submit(TypedText("late"))
        await asyncio.sleep(0)

    recorder.flushing = submit_while_flushing
    await writer.post(AnswerBlock("Held.", RestorationMethod.PASSTHROUGH, False))

    result = await runtime.start_new_session()
    await rig.service.close()

    assert result.reason is NewContextReason.BUSY
    assert ("session ended", 2) not in recorder.calls
