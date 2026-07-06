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
push_system_event to that same SystemEvent. Think/reset controls and
visibility mode are still reserved placeholders - task-ui-04/task-ui-05's
job. See story-status-console-ui.md's task-ui-02/task-ui-03 cards.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from ui_contract import DataLocality, ModuleHealth, RuntimeState, SystemEvent

UI_DIR = Path(__file__).resolve().parent / "status_console_ui"
INDEX_HTML = UI_DIR / "index.html"

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


class WindowLike(Protocol):
    """Shape of the pywebview window object this class relies on - lets
    tests inject a fake, mirroring audio_in.py's InputStreamLike pattern."""

    def evaluate_js(self, script: str) -> object: ...


WindowFactory = Callable[..., WindowLike]


class StatusConsoleWindow:
    """Owns the pywebview window and translates ui_contract.py values into
    evaluate_js calls against status_console_ui/app.js. window_factory is
    injectable so tests never need a real pywebview/WebView2 install - see
    manual_check_status_console.py for the real, hardware-dependent run."""

    def __init__(self, window_factory: WindowFactory | None = None) -> None:
        self._window_factory = window_factory or self._default_window_factory
        self._window: WindowLike | None = None

    @staticmethod
    def _default_window_factory(**kwargs) -> WindowLike:
        import webview

        return webview.create_window(**kwargs)

    def create(self) -> WindowLike:
        self._window = self._window_factory(
            title="Jarvis - Status Console",
            url=str(INDEX_HTML),
            width=960,
            height=640,
            min_size=(480, 420),
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

    def _evaluate(self, js_function: str, payload: dict) -> None:
        if self._window is None:
            raise RuntimeError("create() must be called before pushing state")
        self._window.evaluate_js(f"{js_function}({json.dumps(payload)})")
