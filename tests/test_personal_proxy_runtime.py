import httpx
import pytest

from jarvis.audio.input import UtteranceChunk
from jarvis.core.bus import EventBus
from jarvis.personal_proxy.proxy_inbox import Utterance
from jarvis.personal_proxy.proxy_runtime import PersonalProxyRuntime
from jarvis.personal_proxy.proxy_submissions import ProxySubmissions
from jarvis.ui.contract import VisibilityMode
from jarvis.ui.visibility import VisibilityModeChanged


class _Service:
    def __init__(self, log):
        self.log = log
        self.items = []

    def start(self):
        self.log.append("service started")

    def submit(self, item):
        self.items.append(item)

    def interrupt(self):
        self.log.append("service interrupted")

    def cancel_pending_question(self):
        self.log.append("question cancelled")

    async def close(self):
        self.log.append("service closed")


class _Client(httpx.AsyncClient):
    def __init__(self, log):
        super().__init__()
        self.log = log

    async def aclose(self):
        self.log.append("client closed")
        await super().aclose()


async def _dropped():
    return None


def _runtime(log):
    bus = EventBus()
    service = _Service(log)
    submissions = ProxySubmissions(service, text_max_chars=100, report_dropped=_dropped)
    runtime = PersonalProxyRuntime(
        service=service, submissions=submissions, bus=bus, client=_Client(log)
    )
    return runtime, bus, service


def _chunk():
    return UtteranceChunk(wav_bytes=b"wav", start_seconds=0, end_seconds=1)


async def test_nothing_reaches_the_service_before_start():
    log = []
    runtime, bus, service = _runtime(log)

    await bus.publish(UtteranceChunk, _chunk())

    assert service.items == []
    await runtime.stop()


async def test_after_start_an_utterance_on_the_bus_reaches_the_service():
    log = []
    runtime, bus, service = _runtime(log)

    runtime.start()
    await bus.publish(UtteranceChunk, _chunk())

    assert service.items == [Utterance(b"wav")]
    await runtime.stop()


async def test_start_twice_starts_the_service_and_subscribes_once():
    log = []
    runtime, bus, service = _runtime(log)

    runtime.start()
    runtime.start()
    await bus.publish(UtteranceChunk, _chunk())

    assert log == ["service started"]
    assert len(service.items) == 1
    await runtime.stop()


async def test_stop_unsubscribes_then_interrupts_closes_the_service_then_the_client():
    log = []
    runtime, bus, service = _runtime(log)
    runtime.start()
    log.clear()

    await runtime.stop()
    await bus.publish(UtteranceChunk, _chunk())

    assert log == ["service interrupted", "service closed", "client closed"]
    assert service.items == []


async def test_stop_is_idempotent():
    log = []
    runtime, _, _ = _runtime(log)
    runtime.start()
    await runtime.stop()
    log.clear()

    await runtime.stop()

    assert log == []


async def test_stop_closes_the_client_even_when_the_service_fails_to_close():
    log = []
    runtime, _, service = _runtime(log)

    async def failing_close():
        raise RuntimeError("close failed")

    service.close = failing_close

    with pytest.raises(RuntimeError):
        await runtime.stop()

    assert "client closed" in log


async def test_a_stopped_runtime_does_not_start_again():
    log = []
    runtime, _, _ = _runtime(log)
    await runtime.stop()

    runtime.start()

    assert "service started" not in log


async def test_text_goes_to_the_same_submissions():
    log = []
    runtime, _, service = _runtime(log)

    result = await runtime.submit_text("hello")

    assert result.accepted
    assert len(service.items) == 1
    await runtime.stop()


def test_the_repr_shows_no_state_beyond_whether_it_is_stopped():
    runtime, _, _ = _runtime([])

    assert repr(runtime) == "PersonalProxyRuntime(stopped=False)"


async def test_hiding_the_window_cancels_a_pending_question():
    log = []
    runtime, bus, service = _runtime(log)
    runtime.start()

    await bus.publish(
        VisibilityModeChanged, VisibilityModeChanged(mode=VisibilityMode.HIDDEN)
    )

    assert log.count("question cancelled") == 1
    assert "service interrupted" not in log
    await runtime.stop()


async def test_opening_the_window_cancels_nothing():
    log = []
    runtime, bus, service = _runtime(log)
    runtime.start()

    await bus.publish(
        VisibilityModeChanged, VisibilityModeChanged(mode=VisibilityMode.OPEN)
    )

    assert "question cancelled" not in log
    await runtime.stop()


async def test_hiding_the_window_before_start_or_after_stop_cancels_nothing():
    log = []
    runtime, bus, service = _runtime(log)
    hidden = VisibilityModeChanged(mode=VisibilityMode.HIDDEN)

    await bus.publish(VisibilityModeChanged, hidden)
    runtime.start()
    await runtime.stop()
    await bus.publish(VisibilityModeChanged, hidden)

    assert "question cancelled" not in log
