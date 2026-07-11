import asyncio
import logging
import sys
import types

import pytest

from bus import EventBus
from config import Settings
import manual.manual_check_status_console as manual_check
from manual.manual_check_status_console import (
    DemoContext,
    _run_demo_cycle_async,
)
from status_console import StatusConsoleApi
from ui_contract import EventLevel, RuntimeState, SystemEvent
from visibility_mode import VisibilityModeState
from thinking_mode import ThinkingModeState
from main import ConversationHistory


class _FakeTransport:
    def __init__(self) -> None:
        self.runtime_states: list[RuntimeState] = []

    def set_runtime_state(self, state: RuntimeState, substatus: str | None = None) -> None:
        del substatus
        self.runtime_states.append(state)


class _FakeWindow:
    def destroy(self) -> None:
        pass

    def load_url(self, url: str) -> None:
        self.url = url


@pytest.mark.asyncio
async def test_demo_cycle_uses_transport_and_publishes_real_system_events():
    bus = EventBus()
    events: list[SystemEvent] = []

    async def on_system_event(event: SystemEvent) -> None:
        events.append(event)

    bus.subscribe(SystemEvent, on_system_event)
    shutdown_event = asyncio.Event()
    api = StatusConsoleApi(
        thinking_mode=ThinkingModeState(bus),
        history=ConversationHistory(),
        bus=bus,
        logger=logging.getLogger(__name__),
        visibility_mode=VisibilityModeState(bus),
    )
    transport = _FakeTransport()
    context = DemoContext(
        api=api,
        bus=bus,
        transport=transport,
        shutdown_event=shutdown_event,
    )

    task = asyncio.create_task(_run_demo_cycle_async(context))
    await asyncio.sleep(0.05)
    shutdown_event.set()
    await task

    assert transport.runtime_states
    assert transport.runtime_states[0] is RuntimeState.IDLE
    assert events
    assert events[0].level is EventLevel.INFO


def test_manual_main_creates_windows_before_starting_pywebview(monkeypatch):
    created_windows: list[dict[str, object]] = []

    def create_window(**kwargs):
        created_windows.append(kwargs)
        return _FakeWindow()

    def start(callback) -> None:
        del callback
        assert len(created_windows) == 2

    monkeypatch.setattr(manual_check, "load_settings", lambda: Settings())
    monkeypatch.setitem(
        sys.modules,
        "webview",
        types.SimpleNamespace(create_window=create_window, start=start),
    )

    manual_check.main()
