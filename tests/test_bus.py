import ast
import asyncio
import logging
import sys
from pathlib import Path

import pytest

from jarvis.core.bus import EventBus


async def test_publish_delivers_to_all_subscribers():
    bus = EventBus()
    received_a = []
    received_b = []

    async def handler_a(payload):
        received_a.append(payload)

    async def handler_b(payload):
        received_b.append(payload)

    bus.subscribe("evt", handler_a)
    bus.subscribe("evt", handler_b)

    await bus.publish("evt", "payload")

    assert received_a == ["payload"]
    assert received_b == ["payload"]


async def test_unsubscribe_stops_delivery():
    bus = EventBus()
    received = []

    async def handler(payload):
        received.append(payload)

    bus.subscribe("evt", handler)
    bus.unsubscribe("evt", handler)

    await bus.publish("evt", "payload")

    assert received == []


async def test_different_event_types_do_not_cross_deliver():
    bus = EventBus()
    received_a = []
    received_b = []

    async def handler_a(payload):
        received_a.append(payload)

    async def handler_b(payload):
        received_b.append(payload)

    bus.subscribe("type-a", handler_a)
    bus.subscribe("type-b", handler_b)

    await bus.publish("type-a", "payload")

    assert received_a == ["payload"]
    assert received_b == []


async def test_publish_with_no_subscribers_is_noop():
    bus = EventBus()

    await bus.publish("nobody-listening", "payload")


async def test_concurrent_publishes_deliver_each_event_exactly_once():
    bus = EventBus()
    received = []

    async def handler(payload):
        await asyncio.sleep(0)
        received.append(payload)

    bus.subscribe("evt", handler)

    await asyncio.gather(*(bus.publish("evt", i) for i in range(20)))

    assert sorted(received) == list(range(20))


async def test_subscriber_exception_does_not_break_bus_or_starve_others(caplog):
    bus = EventBus()
    received = []

    async def failing(payload):
        raise ValueError("boom")

    async def ok(payload):
        received.append(payload)

    bus.subscribe("evt", failing)
    bus.subscribe("evt", ok)

    with caplog.at_level(logging.ERROR):
        await bus.publish("evt", "payload")

    assert received == ["payload"]

    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert error_records, (
        "expected the subscriber exception to be logged, not swallowed"
    )
    assert any(
        r.exc_info and isinstance(r.exc_info[1], ValueError) for r in error_records
    )


async def test_cancelled_subscriber_is_not_logged_as_failure_and_propagates(caplog):
    bus = EventBus()
    received = []

    async def cancelled_handler(payload):
        raise asyncio.CancelledError()

    async def ok(payload):
        received.append(payload)

    bus.subscribe("evt", cancelled_handler)
    bus.subscribe("evt", ok)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(asyncio.CancelledError):
            await bus.publish("evt", "payload")

    assert received == ["payload"]
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)


async def test_publish_does_not_raise_when_a_subscriber_raises():
    bus = EventBus()

    async def failing(payload):
        raise ValueError("boom")

    bus.subscribe("evt", failing)

    await bus.publish("evt", "payload")


def test_bus_has_no_project_import_dependencies():
    source = (
        Path(__file__)
        .resolve()
        .parent.parent.joinpath("src/jarvis/core/bus.py")
        .read_text(encoding="utf-8")
    )
    tree = ast.parse(source)
    imported_top_level_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_top_level_names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                imported_top_level_names.add(node.module.split(".")[0])

    non_stdlib = imported_top_level_names - set(sys.stdlib_module_names)
    assert not non_stdlib, f"jarvis.core.bus imports non-stdlib modules: {non_stdlib}"
