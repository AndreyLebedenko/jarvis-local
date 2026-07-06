import asyncio

import pytest

from bus import EventBus
from manual_check_status_console import DemoContext, _run_demo_cycle_async
from thinking_mode import ThinkingModeState, ThinkingModeToggled
from ui_contract import VisibilityMode
from visibility_mode import VisibilityModeChanged, VisibilityModeState


class _FakeApi:
    def set_loop(self, loop) -> None:
        pass


class _FakeConsole:
    """Records every push_*() call - lets a test catch a missing bus
    subscription in _run_demo_cycle_async without a real pywebview window,
    the exact bug class code review caught here: VisibilityModeChanged was
    published but nothing subscribed push_visibility_mode() to it, so a
    real click never reflected back into the UI even though the state
    change and SystemEvent were both real."""

    def __init__(self) -> None:
        self.visibility_calls: list[VisibilityMode] = []
        self.thinking_calls: list[bool] = []

    def push_visibility_mode(self, mode: VisibilityMode) -> None:
        self.visibility_calls.append(mode)

    def push_thinking_mode(self, is_enabled: bool) -> None:
        self.thinking_calls.append(is_enabled)

    def push_system_event(self, event) -> None:
        pass

    def push_model_label(self, label: str) -> None:
        pass

    def push_module_health(self, health) -> None:
        pass

    def push_data_locality(self, locality) -> None:
        pass

    def push_runtime_state(self, state, substatus=None) -> None:
        pass


async def test_visibility_mode_change_is_pushed_back_to_both_windows():
    bus = EventBus()
    console = _FakeConsole()
    touchstrip = _FakeConsole()
    ctx = DemoContext(
        console=console,
        touchstrip=touchstrip,
        api=_FakeApi(),
        bus=bus,
        thinking_mode=ThinkingModeState(bus=bus),
        visibility_mode=VisibilityModeState(bus=bus),
    )

    task = asyncio.create_task(_run_demo_cycle_async(ctx))
    try:
        await asyncio.sleep(0.05)  # let it subscribe and do its startup pushes
        console.visibility_calls.clear()  # ignore the initial push_visibility_mode(OPEN)
        touchstrip.visibility_calls.clear()

        await bus.publish(VisibilityModeChanged, VisibilityModeChanged(mode=VisibilityMode.HIDDEN))
        await asyncio.sleep(0.05)

        assert console.visibility_calls == [VisibilityMode.HIDDEN]
        assert touchstrip.visibility_calls == [VisibilityMode.HIDDEN]
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_thinking_mode_toggle_is_pushed_back_to_both_windows():
    """Same wiring check as above, for the sibling subscription that was
    already correct - regression coverage for both, not just the one the
    review found missing. Also covers task-ui-06: both windows share one
    StatusConsoleApi/ThinkingModeState, so a toggle from either surface
    must reach both."""
    bus = EventBus()
    console = _FakeConsole()
    touchstrip = _FakeConsole()
    thinking_mode = ThinkingModeState(bus=bus)
    ctx = DemoContext(
        console=console,
        touchstrip=touchstrip,
        api=_FakeApi(),
        bus=bus,
        thinking_mode=thinking_mode,
        visibility_mode=VisibilityModeState(bus=bus),
    )

    task = asyncio.create_task(_run_demo_cycle_async(ctx))
    try:
        await asyncio.sleep(0.05)
        console.thinking_calls.clear()  # ignore the initial push_thinking_mode(False)
        touchstrip.thinking_calls.clear()

        await bus.publish(ThinkingModeToggled, ThinkingModeToggled(is_enabled=True))
        await asyncio.sleep(0.05)

        assert console.thinking_calls == [True]
        assert touchstrip.thinking_calls == [True]
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
