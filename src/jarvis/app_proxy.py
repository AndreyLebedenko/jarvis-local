from __future__ import annotations

from typing import TYPE_CHECKING

from jarvis.app_logger import logger
from jarvis.core.config import Settings
from jarvis.core.lifecycle import (
    NewContextReason,
    NewContextResult,
    TextSubmissionReason,
    TextSubmissionResult,
)
from jarvis.core.run_mode import RunMode
from jarvis.core.system_log import publish_system_event
from jarvis.personal_proxy.startup.launch import ProxyPreparer, launch_personal_proxy
from jarvis.personal_proxy.startup.proxy_assembly import ProxyHost
from jarvis.ui.contract import EventLevel, HealthStatus, ModuleHealth, ModuleId
from jarvis.ui.text import ui_text
from jarvis.ui.transport import NewContextHandler, TextInputSubmitter

if TYPE_CHECKING:
    from jarvis.app import App, LiveStatusConsole

PROXY_EVENT_SOURCE = "PERSONAL_PROXY"
LISTENING_CUE = "listening"
STARTING_TEXT_KEY = "personal_proxy_starting"
INBOX_FULL_LOG_MESSAGE = "Personal proxy input queue is full; an utterance was dropped"
RUNNING_MESSAGE = "Jarvis is running. Press the shutdown hotkey or Ctrl+C to stop."
DEBUG_REFUSED_MESSAGE = (
    "debug mode cannot be combined with the personal proxy: it would "
    "record the transcript, the mapping and the answer"
)
CONSOLE_REQUIRED_MESSAGE = (
    "the personal proxy requires the Status Console: it is the surface "
    "that shows the blocks of a request"
)
TRANSPORT_REQUIRED_MESSAGE = "the personal proxy requires the Status Console transport"
PLAYER_REQUIRED_MESSAGE = "the personal proxy requires the shared speech player"


def require_console_for_personal_proxy(
    run_mode: RunMode, live_console: LiveStatusConsole | None, debug: bool = False
) -> None:
    if run_mode is RunMode.PERSONAL_PROXY and debug:
        raise ValueError(DEBUG_REFUSED_MESSAGE)
    if run_mode is RunMode.PERSONAL_PROXY and live_console is None:
        raise ValueError(CONSOLE_REQUIRED_MESSAGE)


async def launch_proxy_instead_of_warm_up(
    app: App,
    settings: Settings,
    live_console: LiveStatusConsole | None,
    prepare_personal_proxy: ProxyPreparer,
) -> None:
    host = proxy_host(app, settings, live_console)
    launch = await launch_personal_proxy(host, logger, prepare_personal_proxy)
    app.personal_proxy = launch.runtime
    app.personal_proxy_failure = launch.failure
    if app.personal_proxy is None:
        host.transport.set_module_health(proxy_microphone_off(settings))


def proxy_microphone_off(settings: Settings) -> ModuleHealth:
    return ModuleHealth(
        module=ModuleId.MICROPHONE,
        status=HealthStatus.UNAVAILABLE,
        detail=ui_text("mic_detail_off_proxy_not_started", settings.ui.language),
    )


def model_label_for(settings: Settings, run_mode: RunMode) -> str:
    if run_mode is RunMode.PERSONAL_PROXY:
        return settings.personal_proxy.model
    return settings.backend.model


async def announce_running(app: App) -> None:
    proxy_down = app.run_mode is RunMode.PERSONAL_PROXY and app.personal_proxy is None
    if not proxy_down:
        await app.sound_cues.play(LISTENING_CUE)
    print(RUNNING_MESSAGE)


def start_personal_proxy(app: App) -> None:
    if app.personal_proxy is not None:
        app.personal_proxy.start()


def proxy_host(
    app: App, settings: Settings, live_console: LiveStatusConsole | None
) -> ProxyHost:
    if live_console is None or live_console.transport is None:
        raise RuntimeError(TRANSPORT_REQUIRED_MESSAGE)
    if app.replay_player is None:
        raise RuntimeError(PLAYER_REQUIRED_MESSAGE)
    return ProxyHost(
        settings=settings,
        bus=app.bus,
        audio_input=app.audio_input,
        player=app.replay_player,
        transport=live_console.transport,
        report_dropped=lambda: report_dropped_proxy_input(app),
        journal=app.journal_recorder,
        response_mode=lambda: app.response_mode.mode.value,
    )


async def report_dropped_proxy_input(app: App) -> None:
    await publish_system_event(
        app.bus,
        logger,
        source=PROXY_EVENT_SOURCE,
        level=EventLevel.WARN,
        log_message=INBOX_FULL_LOG_MESSAGE,
        ui_message=ui_text("personal_proxy_inbox_full", app.settings.ui.language),
    )


def proxy_unavailable_text(app: App) -> str:
    failure = app.personal_proxy_failure
    key = STARTING_TEXT_KEY if failure is None else failure.ui_text_key
    return ui_text(key, app.settings.ui.language)


def text_submitter_for(app: App, run_mode: RunMode) -> TextInputSubmitter:
    if run_mode is not RunMode.PERSONAL_PROXY:
        return app.orchestrator.submit_text_input

    async def submit(text: str) -> TextSubmissionResult:
        runtime = app.personal_proxy
        if runtime is None:
            return TextSubmissionResult(
                TextSubmissionReason.UNAVAILABLE,
                app.settings.clipboard.max_chars,
                proxy_unavailable_text(app),
            )
        return await runtime.submit_text(text)

    return submit


def new_context_handler_for(app: App, run_mode: RunMode) -> NewContextHandler:
    if run_mode is not RunMode.PERSONAL_PROXY:
        return app.orchestrator.start_new_context

    async def start() -> NewContextResult:
        runtime = app.personal_proxy
        if runtime is None:
            return NewContextResult(NewContextReason.UNAVAILABLE)
        return await runtime.start_new_session()

    return start
