import asyncio
import logging
import threading
import time
import types

import numpy as np
from _support_from_test_main import (
    _fake_app,
    _FakeBackend,
    _FakeCaptureInput,
    _FakeTtsOutput,
    _settings,
)

from jarvis.app import (
    build_app,
    run_clipboard_hotkey_listener,
    run_interrupt_hotkey_listener,
    run_mic_sleep_hotkey_listener,
    run_thinking_hotkey_listener,
    run_until_shutdown,
    wire,
)
from jarvis.audio.input import (
    AudioInput,
    UtteranceChunk,
)
from jarvis.core.bus import EventBus
from jarvis.ui.contract import (
    EventLevel,
    SystemEvent,
)

# --- shutdown --------------------------------------------------------------


async def test_run_until_shutdown_with_a_real_microphone_loop_exits_cleanly(caplog):
    """The reported failure shape at the pure level: a real AudioInput
    parked in a blocked executor read enters the standard shutdown
    sequence. stop() must see the loop (and its read worker) actually
    finish, and the shutdown gather must log no task failure."""

    class _NoSpeechChunker:
        settings = types.SimpleNamespace(request_end_pause_seconds=2.0)

        def chunk(self, samples):
            return []

    class _BlockedDrainingStream:
        def __init__(self) -> None:
            self._stopped = threading.Event()
            self._waiting = threading.Event()

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def read(self, block_samples):
            self._waiting.set()
            self._stopped.wait()
            time.sleep(0.05)  # slow drain after the stream stop
            return np.zeros((block_samples, 1), dtype=np.float32), False

        def stop(self) -> None:
            self._stopped.set()

        def start(self) -> None:
            raise AssertionError("shutdown must not restart the stream")

    stream = _BlockedDrainingStream()
    audio_input = AudioInput(
        bus=EventBus(), chunker=_NoSpeechChunker(), stream_factory=lambda bs: stream
    )
    app = build_app(
        _settings(),
        backend=_FakeBackend(),
        audio_input=audio_input,
        tts_output=_FakeTtsOutput(),
        capture_input=_FakeCaptureInput(),
    )
    subscriptions = wire(app)
    shutdown_event = asyncio.Event()
    mic_task = asyncio.create_task(audio_input.run_microphone_loop())
    await asyncio.to_thread(stream._waiting.wait, 2.0)

    shutdown_event.set()
    with caplog.at_level(logging.ERROR):
        await asyncio.wait_for(
            run_until_shutdown(app, subscriptions, shutdown_event, [mic_task]),
            timeout=5,
        )

    assert mic_task.done()
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


async def test_run_until_shutdown_cancels_tasks_and_unsubscribes():
    app = _fake_app()
    subscriptions = wire(app)
    shutdown_event = asyncio.Event()
    background_tasks = [asyncio.create_task(asyncio.Event().wait()) for _ in range(2)]

    shutdown_event.set()
    await asyncio.wait_for(
        run_until_shutdown(app, subscriptions, shutdown_event, background_tasks),
        timeout=2,
    )

    assert all(task.cancelled() for task in background_tasks)

    # confirm unsubscribed: publishing no longer reaches the orchestrator
    await app.bus.publish(
        UtteranceChunk, UtteranceChunk(wav_bytes=b"x", start_seconds=0, end_seconds=1)
    )
    assert app.backend.calls == []


async def test_run_until_shutdown_disables_mcp_host_when_present():
    """run()'s startup calls app.mcp_host.enable() when MCP is configured
    on; this is the matching teardown half - a live MCP connection must
    not outlive clean shutdown."""
    app = _fake_app()
    disable_calls = []

    class _FakeMcpHost:
        async def disable(self) -> None:
            disable_calls.append(1)

    app.mcp_host = _FakeMcpHost()
    subscriptions = wire(app)
    shutdown_event = asyncio.Event()

    shutdown_event.set()
    await asyncio.wait_for(
        run_until_shutdown(app, subscriptions, shutdown_event, []), timeout=2
    )

    assert disable_calls == [1]


async def test_run_until_shutdown_disables_mcp_before_unwiring_subscriptions():
    """Review finding 4: disable() publishes a SystemEvent the Status
    Console's own subscription relays to the UI - unwiring that
    subscription first would mean the UI silently never learns MCP went
    offline. A subscription that is still active when disable() runs must
    actually receive the event."""
    app = _fake_app()
    received: list = []

    async def on_system_event(event) -> None:
        received.append(event)

    class _FakeMcpHost:
        async def disable(self) -> None:
            await app.bus.publish(
                SystemEvent, SystemEvent(0.0, "MCP", EventLevel.INFO, "off")
            )

    app.mcp_host = _FakeMcpHost()
    subscriptions = [*wire(app), (SystemEvent, on_system_event)]
    app.bus.subscribe(SystemEvent, on_system_event)
    shutdown_event = asyncio.Event()

    shutdown_event.set()
    await asyncio.wait_for(
        run_until_shutdown(app, subscriptions, shutdown_event, []), timeout=2
    )

    assert len(received) == 1


class _FakeKeyboardModuleForShutdownTest:
    def __init__(self) -> None:
        self.removed_handles: list[object] = []

    def register(self, binding, callback) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        self.removed_handles.append(object())


async def test_run_until_shutdown_cancels_real_hotkey_listeners():
    """Same shape as test_run_until_shutdown_cancels_tasks_and_unsubscribes,
    but with the real listener coroutines (task-10's clipboard/mic-sleep,
    task-13's thinking-mode, task-v1.7.0-2's interrupt) instead of
    arbitrary fake tasks - confirms run()'s pattern of handing these to
    run_until_shutdown actually cancels them and stops each provider
    during cleanup."""
    app = _fake_app()
    subscriptions = wire(app)
    shutdown_event = asyncio.Event()

    fake_kb_clipboard = _FakeKeyboardModuleForShutdownTest()
    fake_kb_mic_sleep = _FakeKeyboardModuleForShutdownTest()
    fake_kb_thinking = _FakeKeyboardModuleForShutdownTest()
    fake_kb_interrupt = _FakeKeyboardModuleForShutdownTest()
    mic_sleep_audio_input = AudioInput(bus=app.bus, chunker=None)

    background_tasks = [
        asyncio.create_task(
            run_clipboard_hotkey_listener(
                app.bus,
                app.settings.hotkeys,
                app.settings.clipboard,
                provider=fake_kb_clipboard,
            )
        ),
        asyncio.create_task(
            run_mic_sleep_hotkey_listener(
                mic_sleep_audio_input, app.settings.hotkeys, provider=fake_kb_mic_sleep
            )
        ),
        asyncio.create_task(
            run_thinking_hotkey_listener(
                app.thinking_mode, app.settings.hotkeys, provider=fake_kb_thinking
            )
        ),
        asyncio.create_task(
            run_interrupt_hotkey_listener(
                app.bus, app.settings.hotkeys, provider=fake_kb_interrupt
            )
        ),
    ]
    await asyncio.sleep(0)  # let all listeners register their hotkeys

    shutdown_event.set()
    await asyncio.wait_for(
        run_until_shutdown(app, subscriptions, shutdown_event, background_tasks),
        timeout=2,
    )

    assert all(task.cancelled() for task in background_tasks)
    assert len(fake_kb_clipboard.removed_handles) == 1
    assert len(fake_kb_mic_sleep.removed_handles) == 1
    assert len(fake_kb_interrupt.removed_handles) == 1
    assert len(fake_kb_thinking.removed_handles) == 1
