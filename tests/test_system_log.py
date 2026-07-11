import logging
import time

from jarvis.core.bus import EventBus
from jarvis.core.system_log import publish_system_event
from ui_contract import EventLevel, SystemEvent

logger = logging.getLogger("test_system_log")


async def test_publish_system_event_publishes_a_system_event_to_the_bus():
    bus = EventBus()
    received: list[SystemEvent] = []

    async def on_event(event: SystemEvent) -> None:
        received.append(event)

    bus.subscribe(SystemEvent, on_event)

    before = time.time()
    await publish_system_event(
        bus,
        logger,
        source="WARMUP",
        level=EventLevel.INFO,
        log_message="Warm-up request succeeded",
        ui_message="Прогрев завершён",
    )
    after = time.time()

    assert len(received) == 1
    event = received[0]
    assert event.source == "WARMUP"
    assert event.level is EventLevel.INFO
    assert event.message == "Прогрев завершён"
    assert event.correlation_id is None
    assert before <= event.timestamp <= after


async def test_publish_system_event_logs_the_english_log_message_not_the_ui_message(caplog):
    bus = EventBus()

    with caplog.at_level(logging.INFO, logger="test_system_log"):
        await publish_system_event(
            bus,
            logger,
            source="HOTKEY",
            level=EventLevel.INFO,
            log_message="Thinking mode enabled",
            ui_message="Режим мышления включён",
        )

    assert any("Thinking mode enabled" in record.message for record in caplog.records)
    assert not any("включён" in record.message for record in caplog.records)


async def test_publish_system_event_maps_warn_level_to_python_warning(caplog):
    bus = EventBus()

    with caplog.at_level(logging.INFO, logger="test_system_log"):
        await publish_system_event(
            bus,
            logger,
            source="WARMUP",
            level=EventLevel.WARN,
            log_message="Warm-up request failed",
            ui_message="Прогрев не удался",
        )

    assert any(record.levelno == logging.WARNING for record in caplog.records)


async def test_publish_system_event_returns_the_published_event():
    bus = EventBus()

    event = await publish_system_event(
        bus,
        logger,
        source="ENGINE",
        level=EventLevel.ERROR,
        log_message="boom",
        ui_message="Ошибка",
        correlation_id="turn-1",
    )

    assert event.correlation_id == "turn-1"


async def test_publish_system_event_is_a_no_op_safe_publish_with_no_subscribers():
    bus = EventBus()

    # Should not raise even though nothing is subscribed - matches bus.py's
    # own "publish with no subscribers is a no-op" contract, relevant since
    # main.py publishes these before any Status Console window subscribes.
    await publish_system_event(
        bus,
        logger,
        source="ENGINE",
        level=EventLevel.INFO,
        log_message="noop",
        ui_message="noop",
    )
