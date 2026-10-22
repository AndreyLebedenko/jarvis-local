import logging

import pytest

from jarvis.core.bus import EventBus
from jarvis.core.config import Settings, UiSettings
from jarvis.core.lifecycle import WarmupCompleted, WarmupStarted
from jarvis.personal_proxy.launch import launch_personal_proxy
from jarvis.personal_proxy.proxy_assembly import ProxyHost
from jarvis.personal_proxy.startup_failure import (
    ProxyStartupError,
    StartupFailureKind,
)
from jarvis.ui.contract import (
    EventLevel,
    HealthStatus,
    ModuleId,
    RuntimeState,
    SystemEvent,
)
from jarvis.ui.module_health import ModuleHealthChanged
from jarvis.ui.runtime_state import RuntimeStateChanged
from jarvis.ui.text import ui_text

LOGGER = logging.getLogger("test.launch")


async def _dropped():
    return None


def _host(bus, language="en"):
    return ProxyHost(
        settings=Settings(ui=UiSettings(language=language)),
        bus=bus,
        audio_input=None,
        player=None,
        transport=None,
        report_dropped=_dropped,
    )


def _record(bus):
    seen = []

    async def on_started(event):
        seen.append("warmup started")

    async def on_completed(event):
        seen.append(f"warmup completed {event.succeeded}")

    async def on_system(event):
        seen.append((event.source, event.level, event.message))

    async def on_state(event):
        seen.append(("state", event.state, event.substatus_key))

    async def on_health(event):
        seen.append(("health", event.module, event.status, event.detail_key))

    bus.subscribe(WarmupStarted, on_started)
    bus.subscribe(WarmupCompleted, on_completed)
    bus.subscribe(SystemEvent, on_system)
    bus.subscribe(RuntimeStateChanged, on_state)
    bus.subscribe(ModuleHealthChanged, on_health)
    return seen


async def test_a_successful_launch_returns_the_runtime_and_says_what_is_ready():
    bus = EventBus()
    seen = _record(bus)
    runtime = object()

    async def prepare(host):
        seen.append("prepared")
        return runtime

    result = await launch_personal_proxy(_host(bus), LOGGER, prepare)

    assert result.runtime is runtime
    assert result.failure is None
    assert seen == [
        "warmup started",
        "prepared",
        ("PERSONAL_PROXY", EventLevel.INFO, ui_text("personal_proxy_ready", "en")),
        ("state", RuntimeState.LISTENING, "ready_to_listen"),
        (
            "health",
            ModuleId.BACKEND,
            HealthStatus.OK,
            "backend_detail_proxy_ready",
        ),
    ]


async def test_a_successful_launch_does_not_claim_the_main_model_is_warm():
    bus = EventBus()
    seen = _record(bus)

    async def prepare(host):
        return object()

    await launch_personal_proxy(_host(bus), LOGGER, prepare)

    assert "warmup completed True" not in seen
    assert ("WARMUP", EventLevel.INFO, ui_text("warmup_succeeded", "en")) not in seen


@pytest.mark.parametrize("language", ["en", "ru"])
@pytest.mark.parametrize("kind", list(StartupFailureKind))
async def test_a_failed_launch_reports_an_error_with_the_kind_and_returns_none(
    kind, language
):
    bus = EventBus()
    seen = _record(bus)

    async def prepare(host):
        raise ProxyStartupError(kind)

    result = await launch_personal_proxy(_host(bus, language), LOGGER, prepare)

    assert result.runtime is None
    assert result.failure is kind
    assert seen == [
        "warmup started",
        ("PERSONAL_PROXY", EventLevel.ERROR, ui_text(kind.ui_text_key, language)),
    ]


async def test_an_unexpected_error_is_reported_as_internal_without_its_text(caplog):
    bus = EventBus()
    seen = _record(bus)
    secret = "private file name"

    async def prepare(host):
        raise RuntimeError(secret)

    with caplog.at_level(logging.DEBUG):
        result = await launch_personal_proxy(_host(bus), LOGGER, prepare)

    assert result.runtime is None
    assert result.failure is StartupFailureKind.INTERNAL
    assert seen[-1][2] == ui_text("personal_proxy_not_started_internal", "en")
    assert secret not in caplog.text
    assert secret not in repr(seen)


async def test_the_failure_log_line_holds_the_kind_alone(caplog):
    bus = EventBus()

    async def prepare(host):
        raise ProxyStartupError(StartupFailureKind.TOPICS_FILE)

    with caplog.at_level(logging.DEBUG):
        await launch_personal_proxy(_host(bus), LOGGER, prepare)

    assert [record.getMessage() for record in caplog.records] == [
        "[PERSONAL_PROXY] Personal proxy not started: topics_file"
    ]
