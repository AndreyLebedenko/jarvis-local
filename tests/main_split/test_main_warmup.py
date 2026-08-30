import logging

from jarvis.app import (
    APP_LOGGER_NAME,
    warm_up,
)
from jarvis.core.bus import EventBus
from jarvis.ui.contract import (
    EventLevel,
    SystemEvent,
)
from tests.main_split._support_from_test_main import (
    _collecting_subscriber,
    _FakeBackend,
)

# --- warm-up SystemEvent (task-ui-03) ---------------------------------------


async def test_warm_up_publishes_info_system_event_on_success():
    bus = EventBus()
    received: list[SystemEvent] = []
    bus.subscribe(SystemEvent, _collecting_subscriber(received))

    await warm_up(_FakeBackend(), bus)

    assert len(received) == 1
    assert received[0].source == "WARMUP"
    assert received[0].level is EventLevel.INFO


async def test_warm_up_publishes_warn_system_event_and_still_logs_exception_on_failure(
    caplog,
):
    bus = EventBus()
    received: list[SystemEvent] = []
    bus.subscribe(SystemEvent, _collecting_subscriber(received))

    async def failing_chat() -> None:
        raise RuntimeError("Ollama unreachable")

    backend = _FakeBackend(chat_impl=failing_chat)

    with caplog.at_level(logging.ERROR, logger=APP_LOGGER_NAME):
        await warm_up(backend, bus)

    assert any(
        record.levelno == logging.ERROR for record in caplog.records
    )  # logger.exception
    assert len(received) == 1
    assert received[0].source == "WARMUP"
    assert received[0].level is EventLevel.WARN
