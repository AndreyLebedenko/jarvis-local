"""pywebview Status Console bridge and payload adapters."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx
import sounddevice as sd

from bus import EventBus
from config import DEFAULT_UI_CONFIG_PATH, Settings, write_ui_config
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


@dataclass(frozen=True)
class ModelOptionsAvailable:
    """Published by StatusConsoleApi after request_model_options() resolves
    - options always includes current (see _request_model_options_async()),
    so the desktop dropdown never renders a selected value that is not
    actually one of its own options."""

    options: list[str]
    current: str


@dataclass(frozen=True)
class MicrophoneOptionsAvailable:
    options: list[str]
    current: str


@dataclass(frozen=True)
class UiConfigSaved:
    """Published after save_config_selection() writes config.ui.toml -
    main.py's wire_status_console() reacts by showing the desktop's
    pending-restart indicator. No payload: the indicator only needs to
    know a save happened, not what changed."""


def options_payload(options: list[str], current: str) -> dict:
    """Shared shape for both the model and microphone selectors - a
    generic "selectable list + current value" contract, not two
    independently-maintained copies of the same dict literal."""
    return {"options": options, "current": current}


class WindowLike(Protocol):
    """Shape of the pywebview window object used by StatusConsoleWindow."""

    def evaluate_js(self, script: str) -> object: ...
    def destroy(self) -> None: ...


WindowFactory = Callable[..., WindowLike]


class StatusConsoleWindow:
    """Owns one pywebview window and pushes typed UI payloads into it."""

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

    def push_model_options(self, options: list[str], current: str) -> None:
        self._evaluate("applyModelOptions", options_payload(options, current))

    def push_microphone_options(self, options: list[str], current: str) -> None:
        self._evaluate("applyMicrophoneOptions", options_payload(options, current))

    def push_pending_restart(self, pending: bool) -> None:
        self._evaluate("applyPendingRestart", {"pending": pending})

    def close(self) -> None:
        if self._window is None:
            return
        self._window.destroy()
        self._window = None

    def _evaluate(self, js_function: str, payload: dict) -> None:
        if self._window is None:
            raise RuntimeError("create() must be called before pushing state")
        self._window.evaluate_js(f"{js_function}({json.dumps(payload)})")


class TouchstripWindow(StatusConsoleWindow):
    """Compact Status Console surface for touchstrip-sized displays."""

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

    def push_model_options(self, options: list[str], current: str) -> None:
        raise NotImplementedError(
            "TouchstripWindow has no configuration menu by design - "
            "push_model_options() is only valid on the desktop StatusConsoleWindow."
        )

    def push_microphone_options(self, options: list[str], current: str) -> None:
        raise NotImplementedError(
            "TouchstripWindow has no configuration menu by design - "
            "push_microphone_options() is only valid on the desktop StatusConsoleWindow."
        )

    def push_pending_restart(self, pending: bool) -> None:
        raise NotImplementedError(
            "TouchstripWindow has no configuration menu by design - "
            "push_pending_restart() is only valid on the desktop StatusConsoleWindow."
        )


class ClearableHistory(Protocol):
    """Shape StatusConsoleApi.reset_context() relies on."""

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

ModelOptionsSource = Callable[[], Awaitable[list[str]]]
MicrophoneOptionsSource = Callable[[], Awaitable[list[str]]]


async def _default_model_options_source(endpoint: str) -> list[str]:
    """Reads model options from the configured local Ollama endpoint."""
    async with httpx.AsyncClient(timeout=3.0) as client:
        response = await client.get(f"{endpoint}/api/tags")
        response.raise_for_status()
        data = response.json()
    return [
        name
        for entry in data.get("models", [])
        if (name := entry.get("model") or entry.get("name"))
    ]


async def _default_microphone_options_source() -> list[str]:
    """Reads local input device names without blocking the asyncio loop."""
    devices = await asyncio.to_thread(sd.query_devices)
    return [
        device["name"] for device in devices if device.get("max_input_channels", 0) > 0
    ]


class StatusConsoleApi:
    """Synchronous JS API facade that schedules work on the engine loop."""

    def __init__(
        self,
        thinking_mode: ThinkingModeState,
        history: ClearableHistory,
        bus: EventBus,
        logger: logging.Logger,
        visibility_mode: VisibilityModeState | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
        shutdown_event: asyncio.Event | None = None,
        settings: Settings | None = None,
        ui_config_path: str | Path = DEFAULT_UI_CONFIG_PATH,
        model_options_source: ModelOptionsSource | None = None,
        microphone_options_source: MicrophoneOptionsSource | None = None,
    ) -> None:
        self._loop = loop
        self._thinking_mode = thinking_mode
        self._history = history
        self._bus = bus
        self._logger = logger
        self._visibility_mode = visibility_mode or VisibilityModeState(bus)
        self._shutdown_event = shutdown_event
        self._settings = settings or Settings()
        self._ui_config_path = Path(ui_config_path)
        self._model_options_source = model_options_source or (
            lambda: _default_model_options_source(self._settings.backend.endpoint)
        )
        self._microphone_options_source = (
            microphone_options_source or _default_microphone_options_source
        )

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def set_shutdown_event(self, shutdown_event: asyncio.Event) -> None:
        self._shutdown_event = shutdown_event

    def _loop_is_usable(self) -> bool:
        """True only while JS API calls can still schedule engine work."""
        return self._loop is not None and not self._loop.is_closed()

    def toggle_thinking(self) -> None:
        if not self._loop_is_usable():
            return
        asyncio.run_coroutine_threadsafe(self._thinking_mode.toggle(), self._loop)

    def reset_context(self) -> None:
        if not self._loop_is_usable():
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
        if not self._loop_is_usable():
            return
        module = ModuleId(module_id)
        asyncio.run_coroutine_threadsafe(self._reset_module_async(module), self._loop)

    async def _reset_module_async(self, module: ModuleId) -> None:
        """Reports that per-module reset is not implemented yet."""
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
        if not self._loop_is_usable():
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
        if not self._loop_is_usable() or self._shutdown_event is None:
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

    def request_model_options(self) -> None:
        if not self._loop_is_usable():
            return
        asyncio.run_coroutine_threadsafe(self._request_model_options_async(), self._loop)

    async def _request_model_options_async(self) -> None:
        current = self._settings.backend.model
        try:
            options = await self._model_options_source()
        except Exception:
            self._logger.warning("Failed to enumerate Ollama models", exc_info=True)
            await publish_system_event(
                self._bus,
                self._logger,
                source="ENGINE",
                level=EventLevel.WARN,
                log_message="Failed to enumerate Ollama models; degrading to current value",
                ui_message="Не удалось получить список моделей Ollama - показано текущее значение",
            )
            options = []
        if current not in options:
            options = [current, *options]
        await self._bus.publish(
            ModelOptionsAvailable, ModelOptionsAvailable(options=options, current=current)
        )

    def request_microphone_options(self) -> None:
        if not self._loop_is_usable():
            return
        asyncio.run_coroutine_threadsafe(
            self._request_microphone_options_async(), self._loop
        )

    async def _request_microphone_options_async(self) -> None:
        current = self._settings.microphone.device
        try:
            options = await self._microphone_options_source()
        except Exception:
            self._logger.warning("Failed to enumerate microphone devices", exc_info=True)
            await publish_system_event(
                self._bus,
                self._logger,
                source="STT",
                level=EventLevel.WARN,
                log_message=(
                    "Failed to enumerate microphone devices; degrading to current value"
                ),
                ui_message=(
                    "Не удалось получить список микрофонов - показано текущее значение"
                ),
            )
            options = []
        if current not in options:
            options = [current, *options]
        await self._bus.publish(
            MicrophoneOptionsAvailable,
            MicrophoneOptionsAvailable(options=options, current=current),
        )

    def save_config_selection(self, model: str, microphone_device: str) -> None:
        if not self._loop_is_usable():
            return
        asyncio.run_coroutine_threadsafe(
            self._save_config_selection_async(model, microphone_device), self._loop
        )

    async def _save_config_selection_async(self, model: str, microphone_device: str) -> None:
        """Writes restart-to-apply UI config after validating selections."""
        if not model.strip():
            self._logger.warning("Ignoring config menu save with an empty model")
            await publish_system_event(
                self._bus,
                self._logger,
                source="ENGINE",
                level=EventLevel.WARN,
                log_message="Config menu save rejected: model was empty",
                ui_message="Сохранение отменено: модель не выбрана",
            )
            return
        write_ui_config(self._ui_config_path, model=model, microphone_device=microphone_device)
        await publish_system_event(
            self._bus,
            self._logger,
            source="ENGINE",
            level=EventLevel.INFO,
            log_message=(
                f"Config menu saved (model={model!r}, microphone={microphone_device!r}); "
                "restart to apply"
            ),
            ui_message="Настройки сохранены - перезапустите Jarvis, чтобы применить",
        )
        await self._bus.publish(UiConfigSaved, UiConfigSaved())
