"""pywebview Status Console bridge and payload adapters."""

import asyncio
import concurrent.futures
import logging
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from jarvis.core.bus import EventBus
from jarvis.core.config import (
    DEFAULT_UI_CONFIG_PATH,
    SUPPORTED_TTS_ENGINES,
    SUPPORTED_TTS_LANGUAGES,
    SUPPORTED_UI_LANGUAGES,
    Settings,
    TtsLanguageSettings,
    VadSettings,
    tts_route_field_specs,
    tts_route_values,
    write_ui_config,
)
from jarvis.core.system_log import publish_system_event
from jarvis.dialog.thinking_mode import ThinkingModeState
from jarvis.ui.config_selection import (
    VAD_MAX_CHUNK_RANGE,
    VAD_REQUEST_END_PAUSE_RANGE,
    VAD_RESUME_COOLDOWN_RANGE,
    VAD_THRESHOLD_RANGE,
    UiConfigSelection,
    validate_selection,
)
from jarvis.ui.contract import (
    DataLocality,
    EventLevel,
    ModuleHealth,
    ModuleId,
    RuntimeState,
    SystemEvent,
    VisibilityMode,
)
from jarvis.ui.text import (
    DEFAULT_UI_LANGUAGE,
    module_label,
    runtime_state_text,
    ui_text,
)
from jarvis.ui.visibility import VisibilityModeState

UI_DIR = Path(__file__).resolve().parent / "status_console_ui"
INDEX_HTML = UI_DIR / "index.html"
TOUCHSTRIP_HTML = UI_DIR / "touchstrip.html"


def runtime_state_payload(
    state: RuntimeState,
    substatus: str | None = None,
    language: str = DEFAULT_UI_LANGUAGE,
) -> dict:
    label, default_substatus = runtime_state_text(state, language)
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


def config_values_payload(settings: Settings) -> dict:
    """Snapshot section for configuration iteration 2: current values,
    option lists, and validation ranges - the front-end renders and
    range-checks from this data instead of hardcoding a second copy of
    the contract. TTS routes carry only explicitly configured languages;
    an absent language means the Silero-only default is in effect."""
    routes = {
        language: {"engine": route.engine, **tts_route_values(route)}
        for language, route in sorted(settings.tts.languages.items())
    }
    return {
        "ui_language": settings.ui.language,
        "ui_language_options": list(SUPPORTED_UI_LANGUAGES),
        "vad": {
            "threshold": settings.vad.threshold,
            "max_chunk_seconds": settings.vad.max_chunk_seconds,
            "request_end_pause_seconds": settings.vad.request_end_pause_seconds,
            "resume_cooldown_seconds": settings.vad.resume_cooldown_seconds,
        },
        "vad_ranges": {
            "threshold": list(VAD_THRESHOLD_RANGE),
            "max_chunk_seconds": list(VAD_MAX_CHUNK_RANGE),
            "request_end_pause_seconds": list(VAD_REQUEST_END_PAUSE_RANGE),
            "resume_cooldown_seconds": list(VAD_RESUME_COOLDOWN_RANGE),
        },
        "tts": {
            "languages": sorted(SUPPORTED_TTS_LANGUAGES),
            "engines": sorted(SUPPORTED_TTS_ENGINES),
            "schemas": {
                engine: [asdict(spec) for spec in tts_route_field_specs(engine)]
                for engine in sorted(SUPPORTED_TTS_ENGINES)
            },
            "routes": routes,
        },
    }


class WindowLike(Protocol):
    """Shape of the pywebview window object used by StatusConsoleWindow."""

    def destroy(self) -> None: ...
    def load_url(self, url: str) -> None: ...


WindowFactory = Callable[..., WindowLike]


class StatusConsoleWindow:
    """Owns one pywebview window shell for a transport-served UI surface."""

    def __init__(
        self,
        window_factory: WindowFactory | None = None,
        title: str = "Jarvis - Status Console",
        url: str | Path = INDEX_HTML,
        width: int = 960,
        height: int = 900,
        min_size: tuple[int, int] = (480, 420),
        resizable: bool = True,
    ) -> None:
        self._window_factory = window_factory or self._default_window_factory
        self._window: WindowLike | None = None
        self._closed = False
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

    def create(
        self,
        on_closed: Callable[[], None] | None = None,
        url: str | Path | None = None,
    ) -> WindowLike:
        self._window = self._window_factory(
            title=self._title,
            url=str(self._url if url is None else url),
            width=self._width,
            height=self._height,
            min_size=self._min_size,
            resizable=self._resizable,
        )
        self._hook_native_closed(on_closed)
        return self._window

    def _hook_native_closed(self, on_closed: Callable[[], None] | None) -> None:
        """Marks this surface closed when the user closes the real window
        (title-bar X), so the shell can notify the engine and optionally
        forwards the close to a callback (main.py routes the desktop
        console's close into the engine's clean shutdown path). Fake
        windows in tests have no `.events`, so this is getattr-guarded."""
        closed_event = getattr(getattr(self._window, "events", None), "closed", None)
        if closed_event is None:
            return

        def handle_closed(*_args: object) -> None:
            self._closed = True
            self._window = None
            if on_closed is not None:
                on_closed()

        closed_event += handle_closed

    def close(self) -> None:
        window, self._window = self._window, None
        self._closed = True
        if window is None:
            return
        window.destroy()

    def load_url(self, url: str) -> None:
        if self._closed:
            return
        if self._window is None:
            raise RuntimeError("create() must be called before load_url()")
        self._window.load_url(url)


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

ModelOptionsSource = Callable[[], Awaitable[list[str]]]
MicrophoneOptionsSource = Callable[[], Awaitable[list[str]]]


async def _default_model_options_source(endpoint: str) -> list[str]:
    """Reads model options from the configured local Ollama endpoint.

    httpx is imported here, not at module level: this module is the UI
    bridge, and only the two default option sources touch the network/
    audio stacks - importing this module (e.g. from a pure test) must not
    pull them in."""
    import httpx

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
    """Reads local input device names without blocking the asyncio loop.
    sounddevice is imported here, not at module level - see
    _default_model_options_source()."""
    import sounddevice as sd

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
        self._pending_shutdown = False
        self._settings = settings or Settings()
        self._language = self._settings.ui.language
        self._ui_config_path = Path(ui_config_path)
        self._model_options_source = model_options_source or (
            lambda: _default_model_options_source(self._settings.backend.endpoint)
        )
        self._microphone_options_source = (
            microphone_options_source or _default_microphone_options_source
        )

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._dispatch_pending_shutdown()

    def set_shutdown_event(self, shutdown_event: asyncio.Event) -> None:
        self._shutdown_event = shutdown_event
        self._dispatch_pending_shutdown()

    def _schedule(self, coroutine: Coroutine) -> bool:
        """Single scheduling path for every JS API method: pywebview calls
        them from its own GUI thread, so real work always hops onto the
        engine loop via run_coroutine_threadsafe().

        Guards in one place what used to be eight copies of the same
        pattern: no loop yet (window clickable before the engine loop
        exists), loop already closed (verified live: a control clicked
        after shutdown crashed pywebview's JS dispatch thread), the
        check-then-schedule race where the loop closes in between
        (run_coroutine_threadsafe() then raises RuntimeError
        synchronously), and scheduled coroutines whose exceptions would
        otherwise be silently dropped with the discarded future."""
        if self._loop is None or self._loop.is_closed():
            coroutine.close()
            return False
        try:
            future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        except RuntimeError:
            coroutine.close()
            return False
        future.add_done_callback(self._log_scheduled_failure)
        return True

    def _log_scheduled_failure(self, future: concurrent.futures.Future) -> None:
        if future.cancelled():
            return
        exception = future.exception()
        if exception is not None:
            self._logger.error(
                "Status Console action failed on the engine loop", exc_info=exception
            )

    def toggle_thinking(self) -> None:
        self._schedule(self._thinking_mode.toggle())

    def reset_context(self) -> None:
        self._schedule(self._reset_context_async())

    async def _reset_context_async(self) -> None:
        self._history.clear()
        await publish_system_event(
            self._bus,
            self._logger,
            source="ENGINE",
            level=EventLevel.INFO,
            log_message="Conversation context reset by user",
            ui_message=ui_text("context_reset", self._language),
        )

    def reset_module(self, module_id: str) -> None:
        try:
            module = ModuleId(module_id)
        except ValueError:
            # Raising here would crash pywebview's JS dispatch thread, the
            # same failure shape as the verified closed-loop crash.
            self._logger.warning("Ignoring reset for unknown module %r", module_id)
            return
        self._schedule(self._reset_module_async(module))

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
            ui_message=ui_text(
                "module_reset_unsupported",
                self._language,
                module=module_label(module, self._language),
            ),
        )

    def set_visibility_mode(self, mode_value: str) -> None:
        try:
            mode = VisibilityMode(mode_value)
        except ValueError:
            self._logger.warning("Ignoring unknown visibility mode %r", mode_value)
            return
        self._schedule(self._set_visibility_mode_async(mode))

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
            ui_message=ui_text(
                "hidden_mode_enabled"
                if mode is VisibilityMode.HIDDEN
                else "open_mode_restored",
                self._language,
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
        clean-shutdown implementation regardless of which trigger fired it.

        The intent is remembered, not dropped, if the engine loop or the
        shutdown event is not wired up yet (the window is clickable before
        run() reaches set_loop()/set_shutdown_event(), and the desktop
        front-end disables its Shutdown button on the first click - a
        silently dropped request would make UI shutdown permanently
        unreachable): the setter that completes the wiring dispatches it."""
        self._pending_shutdown = True
        self._dispatch_pending_shutdown()

    def _dispatch_pending_shutdown(self) -> None:
        if not self._pending_shutdown or self._shutdown_event is None:
            return
        if self._schedule(self._request_shutdown_async()):
            self._pending_shutdown = False

    async def _request_shutdown_async(self) -> None:
        await publish_system_event(
            self._bus,
            self._logger,
            source="ENGINE",
            level=EventLevel.INFO,
            log_message="Shutdown requested via Status Console",
            ui_message=ui_text("shutdown_requested", self._language),
        )
        self._shutdown_event.set()

    def request_model_options(self) -> None:
        self._schedule(self._request_model_options_async())

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
                log_message=(
                    "Failed to enumerate Ollama models; degrading to current value"
                ),
                ui_message=ui_text("model_options_failed", self._language),
            )
            options = []
        if current not in options:
            options = [current, *options]
        await self._bus.publish(
            ModelOptionsAvailable,
            ModelOptionsAvailable(options=options, current=current),
        )

    def request_microphone_options(self) -> None:
        self._schedule(self._request_microphone_options_async())

    async def _request_microphone_options_async(self) -> None:
        current = self._settings.microphone.device
        try:
            options = await self._microphone_options_source()
        except Exception:
            self._logger.warning(
                "Failed to enumerate microphone devices", exc_info=True
            )
            await publish_system_event(
                self._bus,
                self._logger,
                source="STT",
                level=EventLevel.WARN,
                log_message=(
                    "Failed to enumerate microphone devices; degrading to current value"
                ),
                ui_message=ui_text("microphone_options_failed", self._language),
            )
            options = []
        if current not in options:
            options = [current, *options]
        await self._bus.publish(
            MicrophoneOptionsAvailable,
            MicrophoneOptionsAvailable(options=options, current=current),
        )

    def save_config_selection(
        self,
        model: str,
        microphone_device: str,
        *,
        ui_language: str | None = None,
        vad: VadSettings | None = None,
        tts_routes: dict[str, TtsLanguageSettings] | None = None,
    ) -> None:
        selection = UiConfigSelection(
            model=model,
            microphone_device=microphone_device,
            ui_language=ui_language,
            vad=vad,
            tts_routes=tts_routes,
        )
        self._schedule(self._save_config_selection_async(selection))

    async def _save_config_selection_async(self, selection: UiConfigSelection) -> None:
        """Writes restart-to-apply UI config after validating selections.

        The front-end mirrors the same checks (defense on both sides);
        validate_selection() is the authority for what gets written."""
        problems = validate_selection(selection)
        if problems:
            self._logger.warning("Ignoring config menu save: %s", "; ".join(problems))
            rejected_key = (
                "config_save_rejected_no_model"
                if problems == ["model must not be empty"]
                else "config_save_rejected_invalid"
            )
            await publish_system_event(
                self._bus,
                self._logger,
                source="ENGINE",
                level=EventLevel.WARN,
                log_message=f"Config menu save rejected: {'; '.join(problems)}",
                ui_message=ui_text(rejected_key, self._language),
            )
            return
        write_ui_config(
            self._ui_config_path,
            model=selection.model,
            microphone_device=selection.microphone_device,
            ui_language=selection.ui_language,
            vad=selection.vad,
            tts_routes=selection.tts_routes,
        )
        await publish_system_event(
            self._bus,
            self._logger,
            source="ENGINE",
            level=EventLevel.INFO,
            log_message=(
                "Config menu saved "
                f"(model={selection.model!r}, "
                f"microphone={selection.microphone_device!r}, "
                f"ui_language={selection.ui_language!r}, "
                f"vad={'set' if selection.vad else 'default'}, "
                f"tts_routes={'set' if selection.tts_routes else 'default'}); "
                "restart to apply"
            ),
            ui_message=ui_text("config_saved_restart_to_apply", self._language),
        )
        await self._bus.publish(UiConfigSaved, UiConfigSaved())
