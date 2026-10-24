"""Fakes and a rig for the PersonalProxyService tests: every stage is a fake
that records what it was given, and all of them share one call log."""

from __future__ import annotations

import asyncio
import io

import numpy as np
import soundfile as sf
from _confirmation_fakes import (
    FakeMicrophone,
    FakeSpeaker,
    FakeTranscriber,
    ManualSleep,
)

from jarvis.core.config import PersonalProxySettings
from jarvis.personal_proxy.check.check_result import (
    CheckedTranscript,
    CheckSource,
    Doubt,
    DoubtKind,
)
from jarvis.personal_proxy.gate.gate import check_outbound_payload
from jarvis.personal_proxy.reporting.service_blocks import PersistenceBlock
from jarvis.personal_proxy.request.pipeline_stages import PipelineStages
from jarvis.personal_proxy.restoration.restoration import restore_answer
from jarvis.personal_proxy.sanitize.sanitize_result import (
    SanitizeResult,
    SanitizeVerdict,
)
from jarvis.personal_proxy.service.proxy_service import PersonalProxyService
from jarvis.personal_proxy.stt.stt_result import Transcription
from jarvis.ui.contract import DataLocality

HEARD = "Передай Марине Крыловой, что документы готовы"
SANITIZED = "Передай <PERSON_1>, что документы готовы"
MAPPING = {"<PERSON_1>": "Марине Крыловой"}
ANSWER_DELTAS = ("Хорошо, передаю ", "<PERSON_1>. ", "Это займёт минуту.")
TRANSCRIPTION = Transcription(HEARD, (), ())
CHECKED = CheckedTranscript(HEARD, (), CheckSource.CHECKED, False)
CHECKED_WITH_DOUBT = CheckedTranscript(
    HEARD,
    (Doubt(DoubtKind.FRAGMENT, "Марине Крыловой"),),
    CheckSource.CHECKED,
    True,
)
SEND = SanitizeResult(SanitizeVerdict.SEND, "", SANITIZED, MAPPING)
TOPICS = "здоровье ребёнка"


def make_wav(seconds=0.1):
    buffer = io.BytesIO()
    samples = np.zeros(int(16000 * seconds), dtype=np.float32)
    sf.write(buffer, samples, 16000, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


class RecordingSink:
    def __init__(self, log, *, fail_on=None):
        self.log = log
        self.blocks = []
        self.persistence_blocks = []
        self.fail_on = fail_on

    async def post(self, block):
        if isinstance(block, PersistenceBlock):
            self.persistence_blocks.append(block)
            return
        self.log.append(f"post:{type(block).__name__}")
        self.blocks.append(block)
        if self.fail_on is not None and isinstance(block, self.fail_on):
            raise RuntimeError("sink broke")

    def of(self, block_type):
        return [block for block in self.blocks if isinstance(block, block_type)]

    def notices(self):
        from jarvis.personal_proxy.reporting.service_blocks import NoticeBlock

        return [block.kind for block in self.of(NoticeBlock)]


class FakeLocality:
    def __init__(self, log):
        self.log = log
        self.current = DataLocality.LOCAL
        self.history = []

    def set_data_locality(self, locality):
        self.current = locality
        self.history.append(locality)
        self.log.append(f"locality:{locality.value}")


class FakeStream:
    def __init__(self, log, locality, deltas, *, error=None, gate=None):
        self.log = log
        self.locality = locality
        self.deltas = list(deltas)
        self.error = error
        self.gate = gate
        self.closed = False
        self.seen_locality = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        self.log.append("pull")
        self.seen_locality.append(self.locality.current)
        if self.gate is not None:
            await self.gate.wait()
        if self.deltas:
            return self.deltas.pop(0)
        if self.error is not None:
            raise self.error
        raise StopAsyncIteration

    async def aclose(self):
        self.log.append("stream_closed")
        self.closed = True


class FailingBackend:
    async def complete(self, request):
        raise RuntimeError("no model in this test")


class FakeStages:
    """Each stage has a result and an optional error or hold; calls are kept."""

    def __init__(self, log, locality, settings):
        self.log = log
        self.locality = locality
        self.settings = settings
        self.transcription = TRANSCRIPTION
        self.checked = CHECKED
        self.sanitized = SEND
        self.deltas = ANSWER_DELTAS
        self.stream_error = None
        self.stream_gate = None
        self.open_error = None
        self.errors = {}
        self.holds = {}
        self.calls = {name: [] for name in STAGE_NAMES}
        self.streams = []
        self.gate_results = []
        self.restore_override = None

    async def _enter(self, name, *args):
        self.log.append(name)
        self.calls[name].append(args)
        if name in self.holds:
            await self.holds[name].wait()
        if name in self.errors:
            raise self.errors[name]

    async def transcribe(self, clip):
        await self._enter("transcribe", clip)
        return self.transcription

    async def check(self, transcription, clip):
        await self._enter("check", transcription, clip)
        return self.checked

    async def sanitize(self, checked):
        await self._enter("sanitize", checked)
        return self.sanitized

    def gate(self, payload, context):
        self.log.append("gate")
        self.calls["gate"].append((payload, context))
        result = check_outbound_payload(payload, context)
        self.gate_results.append(result)
        return result

    def open_stream(self, payload):
        self.log.append("open_stream")
        self.calls["open_stream"].append((payload,))
        if self.open_error is not None:
            raise self.open_error
        stream = FakeStream(
            self.log,
            self.locality,
            self.deltas,
            error=self.stream_error,
            gate=self.stream_gate,
        )
        self.streams.append(stream)
        return stream

    def restore(self, deltas, mapping):
        self.log.append("restore")
        if self.restore_override is not None:
            return self.restore_override(deltas, mapping)
        return restore_answer(deltas, mapping, FailingBackend(), self.settings)

    async def warm_up(self):
        await self._enter("warm_up")

    def as_stages(self):
        return PipelineStages(
            transcribe=self.transcribe,
            check=self.check,
            sanitize=self.sanitize,
            gate=self.gate,
            open_stream=self.open_stream,
            restore=self.restore,
            warm_up=self.warm_up,
        )


STAGE_NAMES = (
    "transcribe",
    "check",
    "sanitize",
    "gate",
    "open_stream",
    "restore",
    "warm_up",
)


class Rig:
    def __init__(
        self,
        *,
        dry_run=False,
        language="en",
        speaker=None,
        microphone=None,
        sink=None,
        queue_capacity=4,
        inbox_capacity=8,
        timeout=20.0,
        **settings_overrides,
    ):
        self.log = []
        self.settings = PersonalProxySettings(
            dry_run=dry_run,
            confirmation_timeout_seconds=timeout,
            **settings_overrides,
        )
        self.language = language
        self.sink = sink or RecordingSink(self.log)
        self.speaker = speaker or FakeSpeaker(self.log)
        self.microphone = microphone or FakeMicrophone(self.log)
        self.locality = FakeLocality(self.log)
        self.stages = FakeStages(self.log, self.locality, self.settings)
        self.sleep = ManualSleep()
        self.service = PersonalProxyService(
            stages=self.stages.as_stages(),
            sink=self.sink,
            speaker=self.speaker,
            microphone=self.microphone,
            locality=self.locality,
            language=lambda: self.language,
            settings=self.settings,
            topics_text=TOPICS,
            sleep=self.sleep,
            queue_capacity=queue_capacity,
            inbox_capacity=inbox_capacity,
            resume_limit_seconds=0.05,
        )

    @property
    def payloads_sent(self):
        return [args[0] for args in self.stages.calls["open_stream"]]

    @property
    def spoken_texts(self):
        return [text for text, _ in self.speaker.spoken]


async def until(condition, seconds=2.0):
    async with asyncio.timeout(seconds):
        while not condition():
            await asyncio.sleep(0)


async def within(awaitable, seconds=5.0):
    """A hang becomes a failure: nothing in these tests may wait forever."""
    return await asyncio.wait_for(awaitable, seconds)


async def closed(service):
    await within(service.close())


async def settled(rig):
    await until(lambda: rig.service.idle)


__all__ = [
    "ANSWER_DELTAS",
    "CHECKED",
    "CHECKED_WITH_DOUBT",
    "HEARD",
    "MAPPING",
    "SANITIZED",
    "SEND",
    "TOPICS",
    "TRANSCRIPTION",
    "FakeTranscriber",
    "Rig",
    "closed",
    "make_wav",
    "settled",
    "until",
    "within",
]
