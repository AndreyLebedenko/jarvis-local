"""Desktop Status Console shell (task-ui-02): a pywebview window over
status_console_ui/index.html.

Framework decision (human, task-ui-02 stop condition): pywebview over a
local HTML/CSS/JS front-end, reusing the visual language already drafted in
.planning/UI/mock-ups/jarvis_status_console_v1.html with no rewrite into a
native widget toolkit. Windows backend is WebView2 (pre-installed on
Windows 11); a future Linux backend would be QtWebEngine via PySide6 - a
pywebview GUI-backend choice, not a UI rewrite (see story-status-console-
ui.md's Open Questions). This module is a same-process bridge only
(pywebview's own evaluate_js), matching "UI consumes engine state through
explicit events/snapshots" (story's Key Decisions) without adding a
networked layer nothing in v1.0 needs yet - a networked WebSocket transport
is deferred to whichever later task needs cross-device delivery (e.g.
task-ui-06's touchstrip surface, if that ends up running on a separate
device).

Pure rendering logic (contract shape -> DOM update) lives in
status_console_ui/app.js; this module's job is only launching the window
and translating ui_contract.py's dataclasses into the JSON payloads that
app.js's functions expect - the *_payload() functions below are the pure,
testable half of that translation.

Nothing here subscribes to bus.py directly - that would require deciding
how pywebview's own GUI loop (webview.start(), typically main-thread) and
this process's asyncio loop share the main thread, which is a separate,
larger concern than either this module or task-ui-03 owns. Instead,
main.py's handlers call system_log.publish_system_event() at the point
something happens (see main.py's _on_mic_sleep_toggled/
_on_thinking_mode_toggled/warm_up) - publishing to the bus is safe with
zero subscribers (bus.py: a no-op) - and whichever future task wires a
live StatusConsoleWindow into main.py's App only needs to subscribe
push_system_event to that same SystemEvent. Visibility mode is still a
reserved placeholder - task-ui-05's job. See story-status-console-ui.md's
task-ui-02/task-ui-03 cards.

task-ui-04 adds the reverse direction: StatusConsoleApi is exposed to the
front-end as pywebview's js_api (JS -> Python), for the Think toggle and
reset controls. Its methods are plain sync callables that schedule work
onto a given asyncio loop via run_coroutine_threadsafe - the exact same
race-avoidance pattern this project's hotkey listeners already use
(thinking_mode.py/audio_in.py's run_hotkey_listener), since pywebview
invokes js_api methods from its own GUI thread, not the asyncio loop's
thread.

Stop Condition (task-ui-04): no module (backend, microphone, TTS, memory,
vision) has a lifecycle/reset API today (see PROJECT.md) - so
reset_module() never claims success. It honestly publishes a WARN
SystemEvent reporting the gap instead of faking a reset; a future task
that adds a real per-module reset API replaces only that method's body,
not the button/wiring around it.

task-ui-05 adds set_visibility_mode(), the same js_api pattern as
toggle_thinking()/reset_context(). Human decision recorded in task-ui-05's
card: in v1, Open/Hidden only changes what the Status Console UI itself
displays - it does not touch audio_in.py/tts.py/Orchestrator, so this
method needs no engine-side consumer beyond VisibilityModeState itself and
a SystemEvent for visibility.

task-ui-06 adds TouchstripWindow, a second StatusConsoleWindow pointed at
status_console_ui/touchstrip.html instead of index.html - same push_*()
surface (task-ui-06's AC: "Same state contract as desktop Status Console
is reused"), same StatusConsoleApi instance shared with the desktop
window (pywebview allows binding the same js_api object to more than one
window), so toggling Think/visibility mode on either surface is one real
engine state, not two independently-tracked copies. Stop Condition
evaluated: pywebview supports creating multiple windows in one process
before webview.start() runs the GUI loop, so this needed no separate
process or architecture change.

story-v1.2.4-task-1 adds request_shutdown(), routed through the exact
same shutdown_event that main.py's shutdown hotkey already sets (Boundary:
"Shutdown must use the same clean path as the existing shutdown hotkey") -
this class never cancels tasks or unsubscribes handlers itself; it only
sets the event that run_until_shutdown() already waits on, so there is
exactly one clean-shutdown implementation, not a second one reachable only
from the UI. shutdown_event is optional at construction and settable later
via set_shutdown_event(), the same chicken-and-egg ordering as set_loop()
(this object is created before main.py's run() creates its real
asyncio.Event()).
"""

import asyncio
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from bus import EventBus
from system_log import publish_system_event
from thinking_mode import ThinkingModeState
from ui_contract import (
    DataLocality,
    EventLevel,
    ModuleHealth,
    ModuleId,
    RuntimeState,
    SystemEvent,
    VisibilityMode,
)
from visibility_mode import VisibilityModeState

UI_DIR = Path(__file__).resolve().parent / "status_console_ui"
INDEX_HTML = UI_DIR / "index.html"
TOUCHSTRIP_HTML = UI_DIR / "touchstrip.html"

# Labels/default substatus text for each RuntimeState. Kept here (not in
# app.js) so a later task can localize or reuse them without touching the
# front-end, and so this mapping is covered by a pure Python test.
_RUNTIME_STATE_TEXT: dict[RuntimeState, tuple[str, str]] = {
    RuntimeState.IDLE: ("Ожидание", "Скажите «Джарвис», чтобы начать."),
    RuntimeState.WARMING: ("Прогрев (локально)", "Модель загружается в память GPU..."),
    RuntimeState.LISTENING: ("Слушаю", "Жду голосовую команду..."),
    RuntimeState.THINKING: ("Думаю", "Собираю контекст и формирую ответ..."),
    RuntimeState.SPEAKING: ("Отвечаю", "Произношу ответ вслух..."),
    RuntimeState.ERROR: ("Ошибка", ""),
}


def runtime_state_payload(state: RuntimeState, substatus: str | None = None) -> dict:
    label, default_substatus = _RUNTIME_STATE_TEXT[state]
    return {
        "state": state.value,
        "label": label,
        "substatus": default_substatus if substatus is None else substatus,
    }


def module_health_payload(health: ModuleHealth) -> dict:
    return {
        "module": health.module.value,
        "status": health.status.value,
        "detail": health.detail,
    }


def data_locality_payload(locality: DataLocality) -> dict:
    return {"locality": locality.value}


def system_event_payload(event: SystemEvent) -> dict:
    return {
        "timestamp": event.timestamp,
        "source": event.source,
        "level": event.level.value,
        "message": event.message,
        "correlation_id": event.correlation_id,
    }


def thinking_mode_payload(is_enabled: bool) -> dict:
    return {"is_enabled": is_enabled}


def visibility_mode_payload(mode: VisibilityMode) -> dict:
    return {"mode": mode.value}


class WindowLike(Protocol):
    """Shape of the pywebview window object this class relies on - lets
    tests inject a fake, mirroring audio_in.py's InputStreamLike pattern."""

    def evaluate_js(self, script: str) -> object: ...


WindowFactory = Callable[..., WindowLike]


class StatusConsoleWindow:
    """Owns a pywebview window and translates ui_contract.py values into
    evaluate_js calls against the matching front-end file (status_console_ui/
    app.js for the desktop shell, touchstrip.js for TouchstripWindow below -
    both expose the same apply*() function names, task-ui-06's "same state
    contract" AC). window_factory is injectable so tests never need a real
    pywebview/WebView2 install - see manual_check_status_console.py for the
    real, hardware-dependent run.

    title/url/width/height/min_size/resizable default to the desktop shell's
    original values; TouchstripWindow below overrides them for a fixed-size,
    non-resizable ~900x230 window matching a real touch-strip device."""

    def __init__(
        self,
        window_factory: WindowFactory | None = None,
        title: str = "Jarvis - Status Console",
        url: Path = INDEX_HTML,
        width: int = 960,
        height: int = 640,
        min_size: tuple[int, int] = (480, 420),
        resizable: bool = True,
    ) -> None:
        self._window_factory = window_factory or self._default_window_factory
        self._window: WindowLike | None = None
        self._title = title
        self._url = url
        self._width = width
        self._height = height
        self._min_size = min_size
        self._resizable = resizable

    @staticmethod
    def _default_window_factory(**kwargs) -> WindowLike:
        import webview

        return webview.create_window(**kwargs)

    def create(self, js_api: object | None = None) -> WindowLike:
        self._window = self._window_factory(
            title=self._title,
            url=str(self._url),
            width=self._width,
            height=self._height,
            min_size=self._min_size,
            resizable=self._resizable,
            js_api=js_api,
        )
        return self._window

    def push_runtime_state(self, state: RuntimeState, substatus: str | None = None) -> None:
        self._evaluate("applyRuntimeState", runtime_state_payload(state, substatus))

    def push_module_health(self, health: ModuleHealth) -> None:
        self._evaluate("applyModuleHealth", module_health_payload(health))

    def push_data_locality(self, locality: DataLocality) -> None:
        self._evaluate("applyDataLocality", data_locality_payload(locality))

    def push_model_label(self, label: str) -> None:
        self._evaluate("applyModelLabel", {"label": label})

    def push_system_event(self, event: SystemEvent) -> None:
        self._evaluate("appendSystemEvent", system_event_payload(event))

    def push_thinking_mode(self, is_enabled: bool) -> None:
        self._evaluate("applyThinkingMode", thinking_mode_payload(is_enabled))

    def push_visibility_mode(self, mode: VisibilityMode) -> None:
        self._evaluate("applyVisibilityMode", visibility_mode_payload(mode))

    def _evaluate(self, js_function: str, payload: dict) -> None:
        if self._window is None:
            raise RuntimeError("create() must be called before pushing state")
        self._window.evaluate_js(f"{js_function}({json.dumps(payload)})")


class TouchstripWindow(StatusConsoleWindow):
    """The touchstrip glance surface (task-ui-06): status_console_ui/
    touchstrip.html instead of index.html, sized to a real touch-strip
    device (~900x230, non-resizable - a physical device does not resize).
    Every push_*() method except push_system_event() is inherited
    unchanged, because touchstrip.js exposes the same apply*() function
    names as app.js (task-ui-06's "same state contract" AC) - only the
    rendering differs. push_system_event() is overridden to fail loudly:
    Scope explicitly excludes a dense event log from this surface, and
    touchstrip.js has no appendSystemEvent() to call."""

    def __init__(self, window_factory: WindowFactory | None = None) -> None:
        super().__init__(
            window_factory=window_factory,
            title="Jarvis - Touchstrip",
            url=TOUCHSTRIP_HTML,
            width=900,
            height=230,
            min_size=(900, 230),
            resizable=False,
        )

    def push_system_event(self, event: SystemEvent) -> None:
        raise NotImplementedError(
            "TouchstripWindow has no system events panel by design (Scope: "
            "'No dense event log on touchstrip') - push_system_event() is "
            "only valid on the desktop StatusConsoleWindow."
        )


class ClearableHistory(Protocol):
    """Shape StatusConsoleApi.reset_context() relies on - deliberately not
    main.py's concrete ConversationHistory, so this module never depends on
    the top-level wiring module (main.py may need to depend on this one
    later, when a live window is finally wired in - see this module's
    docstring)."""

    def clear(self) -> None: ...


_MODULE_RESET_SOURCE: dict[ModuleId, str] = {
    ModuleId.BACKEND: "LLM",
    ModuleId.MICROPHONE: "STT",
    ModuleId.TTS: "TTS",
    ModuleId.MEMORY: "ENGINE",
    ModuleId.VISION: "CAPTURE",
}

_MODULE_LABELS_RU: dict[ModuleId, str] = {
    ModuleId.BACKEND: "модели/backend",
    ModuleId.MICROPHONE: "микрофона",
    ModuleId.TTS: "TTS",
    ModuleId.MEMORY: "памяти",
    ModuleId.VISION: "vision/экрана",
}


class StatusConsoleApi:
    """Exposed to the front-end as window.pywebview.api (pywebview's own
    JS -> Python bridge) - see this module's docstring for the threading
    rationale. Every public method here is a plain sync callable, never
    awaited directly by pywebview; each schedules its real async work onto
    the given loop instead.

    loop is optional at construction time and settable later via
    set_loop(): pywebview.create_window(js_api=...) must receive this
    object before webview.start() runs the GUI loop, but the real asyncio
    loop this object needs to schedule onto typically does not exist until
    the code running inside webview.start()'s own callback creates one
    (see manual_check_status_console.py) - a real chicken-and-egg ordering
    constraint, not an oversight. Every public method is a no-op until
    set_loop() has been called (a user cannot click a control before the
    window has actually opened, by which point the loop already exists in
    every real run)."""

    def __init__(
        self,
        thinking_mode: ThinkingModeState,
        history: ClearableHistory,
        bus: EventBus,
        logger: logging.Logger,
        visibility_mode: VisibilityModeState | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
        shutdown_event: asyncio.Event | None = None,
    ) -> None:
        self._loop = loop
        self._thinking_mode = thinking_mode
        self._history = history
        self._bus = bus
        self._logger = logger
        self._visibility_mode = visibility_mode or VisibilityModeState(bus)
        self._shutdown_event = shutdown_event

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def set_shutdown_event(self, shutdown_event: asyncio.Event) -> None:
        self._shutdown_event = shutdown_event

    def toggle_thinking(self) -> None:
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._thinking_mode.toggle(), self._loop)

    def reset_context(self) -> None:
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._reset_context_async(), self._loop)

    async def _reset_context_async(self) -> None:
        self._history.clear()
        await publish_system_event(
            self._bus,
            self._logger,
            source="ENGINE",
            level=EventLevel.INFO,
            log_message="Conversation context reset by user",
            ui_message="Контекст диалога сброшен",
        )

    def reset_module(self, module_id: str) -> None:
        if self._loop is None:
            return
        module = ModuleId(module_id)
        asyncio.run_coroutine_threadsafe(self._reset_module_async(module), self._loop)

    async def _reset_module_async(self, module: ModuleId) -> None:
        """Stop Condition (task-ui-04): never claims success - see this
        module's docstring. A future task adding a real per-module reset
        API replaces only this body."""
        await publish_system_event(
            self._bus,
            self._logger,
            source=_MODULE_RESET_SOURCE[module],
            level=EventLevel.WARN,
            log_message=(
                f"Reset requested for module {module.value}, but no engine "
                "reset API exists yet"
            ),
            ui_message=(
                f"Сброс {_MODULE_LABELS_RU[module]} запрошен, но пока не "
                "поддерживается движком"
            ),
        )

    def set_visibility_mode(self, mode_value: str) -> None:
        mode = VisibilityMode(mode_value)
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._set_visibility_mode_async(mode), self._loop)

    async def _set_visibility_mode_async(self, mode: VisibilityMode) -> None:
        previous_mode = self._visibility_mode.mode
        await self._visibility_mode.set_mode(mode)
        if mode == previous_mode:
            # VisibilityModeState.set_mode() already no-ops on a redundant
            # call (no VisibilityModeChanged) - matching that here too, so
            # clicking the already-active mode does not also produce a
            # misleading "changed" SystemEvent.
            return
        await publish_system_event(
            self._bus,
            self._logger,
            source="ENGINE",
            level=EventLevel.INFO,
            log_message=f"Visibility mode set to {mode.value}",
            ui_message=(
                "Режим Hidden активирован: превью экрана скрыто"
                if mode is VisibilityMode.HIDDEN
                else "Режим Open восстановлен"
            ),
        )

    def request_shutdown(self) -> None:
        """Guarded by the front-end's own confirm-before-destructive-action
        step (showShutdownConfirm()/confirmShutdown() in app.js, hold-to-
        confirm in touchstrip.js) - by the time this fires, the user has
        already deliberately confirmed. Sets the same shutdown_event
        main.py's shutdown hotkey sets (loop.call_soon_threadsafe(
        shutdown_event.set) in run()) - this class does no teardown itself,
        it only requests it, so run_until_shutdown() remains the single
        clean-shutdown implementation regardless of which trigger fired it."""
        if self._loop is None or self._shutdown_event is None:
            return
        asyncio.run_coroutine_threadsafe(self._request_shutdown_async(), self._loop)

    async def _request_shutdown_async(self) -> None:
        await publish_system_event(
            self._bus,
            self._logger,
            source="ENGINE",
            level=EventLevel.INFO,
            log_message="Shutdown requested via Status Console",
            ui_message="Запрошено завершение работы Jarvis",
        )
        self._shutdown_event.set()
