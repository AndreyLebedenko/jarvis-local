"""The proxy's part of the application's start: prepare it where the main
model's warm-up would run, and say so on the bus. The main model is not warmed
in this mode, so `WarmupCompleted` is never published: it would mark the
backend as responding. A failed start is reported with its kind alone; the
window stays open and nothing is started."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from jarvis.core.bus import EventBus
from jarvis.core.lifecycle import WarmupStarted
from jarvis.core.system_log import publish_system_event
from jarvis.personal_proxy.service.proxy_runtime import PersonalProxyRuntime
from jarvis.personal_proxy.startup.proxy_assembly import (
    ProxyHost,
    prepare_personal_proxy_runtime,
)
from jarvis.personal_proxy.startup.startup_failure import (
    ProxyStartupError,
    StartupFailureKind,
)
from jarvis.ui.contract import EventLevel, HealthStatus, ModuleId, RuntimeState
from jarvis.ui.module_health import ModuleHealthChanged
from jarvis.ui.runtime_state import RuntimeStateChanged
from jarvis.ui.text import ui_text

SOURCE = "PERSONAL_PROXY"

ProxyPreparer = Callable[[ProxyHost], Awaitable[PersonalProxyRuntime]]


@dataclass(frozen=True)
class ProxyLaunch:
    """The prepared, not yet started, runtime; or the kind of the failure."""

    runtime: PersonalProxyRuntime | None
    failure: StartupFailureKind | None = None


async def launch_personal_proxy(
    host: ProxyHost,
    logger: logging.Logger,
    prepare: ProxyPreparer = prepare_personal_proxy_runtime,
) -> ProxyLaunch:
    language = host.settings.ui.language
    await host.bus.publish(WarmupStarted, WarmupStarted())
    try:
        runtime = await prepare(host)
    except ProxyStartupError as error:
        await _report_failure(host.bus, logger, language, error.kind)
        return ProxyLaunch(None, error.kind)
    except Exception:
        kind = StartupFailureKind.INTERNAL
        await _report_failure(host.bus, logger, language, kind)
        return ProxyLaunch(None, kind)
    await _report_ready(host.bus, logger, language)
    return ProxyLaunch(runtime)


async def _report_ready(bus: EventBus, logger: logging.Logger, language: str) -> None:
    await publish_system_event(
        bus,
        logger,
        source=SOURCE,
        level=EventLevel.INFO,
        log_message="Personal proxy stages are ready",
        ui_message=ui_text("personal_proxy_ready", language),
    )
    await bus.publish(
        RuntimeStateChanged,
        RuntimeStateChanged(RuntimeState.LISTENING, substatus_key="ready_to_listen"),
    )
    await bus.publish(
        ModuleHealthChanged,
        ModuleHealthChanged(
            ModuleId.BACKEND, HealthStatus.OK, "backend_detail_proxy_ready"
        ),
    )


async def _report_failure(
    bus: EventBus, logger: logging.Logger, language: str, kind: StartupFailureKind
) -> None:
    await publish_system_event(
        bus,
        logger,
        source=SOURCE,
        level=EventLevel.ERROR,
        log_message=f"Personal proxy not started: {kind.value}",
        ui_message=ui_text(kind.ui_text_key, language),
    )
