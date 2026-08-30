import asyncio
import logging
import types
from pathlib import Path

import pytest

from jarvis.app import (
    APP_LOGGER_NAME,
    _announce_debug_mode_to_panel,
    announce_debug_mode,
    main,
    parse_args,
    run,
)
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    LoggingSettings,
)
from jarvis.core.debug_transcript import configure_debug_transcript, recording
from jarvis.ui.contract import (
    EventLevel,
    SystemEvent,
)
from tests.main_split._support_from_test_main import (
    _collecting_subscriber,
    _fake_app,
    _settings,
)


class _StopBeforeEngine(Exception):
    """Aborts run() after its startup announcements, before build_app()
    would construct real hardware-touching modules."""


def _raise(error: Exception):
    raise error


# --- debug mode gate --------------------------------------------------------
# Debug lifts the content rule both records otherwise keep, so the console
# banner is the consent surface and a headless debug run must not exist.


def test_debug_requires_the_status_console(capsys):
    with pytest.raises(SystemExit) as exit_info:
        parse_args(["--debug"])

    assert exit_info.value.code != 0
    assert "--debug requires --status-console" in capsys.readouterr().err


def test_debug_is_accepted_with_the_status_console():
    args = parse_args(["--status-console", "--debug"])

    assert args.debug is True


def test_debug_is_off_unless_asked_for():
    assert parse_args([]).debug is False
    assert parse_args(["--status-console"]).debug is False


def test_main_carries_the_debug_flag_into_the_console_launch(monkeypatch):
    calls = {}

    def fake_run_with_status_console(**kwargs):
        calls.update(kwargs)

    monkeypatch.setattr(
        "jarvis.app.run_with_status_console", fake_run_with_status_console
    )

    main(["--status-console", "--debug"])

    assert calls["debug"] is True


def test_announcing_debug_mode_warns_that_privacy_is_not_guaranteed(caplog):
    """The warning has to be in the file a problem report carries, or a log
    containing the exchange would not say why it was allowed to. WARNING,
    not INFO: it must stand out in a file that is mostly INFO."""
    with caplog.at_level(logging.WARNING, logger=APP_LOGGER_NAME):
        announce_debug_mode(True, Path("logs/jarvis-debug.jsonl"))

    assert all(record.levelno == logging.WARNING for record in caplog.records)
    announced = " ".join(record.getMessage() for record in caplog.records)
    assert "DEBUG MODE" in announced
    assert "Privacy is not guaranteed" in announced
    assert "jarvis-debug.jsonl" in announced


def test_a_debug_run_that_cannot_record_says_so(caplog):
    """Starting for a recording and silently not getting one is the worst
    of both: the privacy cost is paid and no evidence is collected."""
    with caplog.at_level(logging.WARNING, logger=APP_LOGGER_NAME):
        announce_debug_mode(True, None)

    announced = " ".join(record.getMessage() for record in caplog.records)
    assert "records nothing" in announced


def test_a_normal_run_says_nothing_about_debug(caplog):
    with caplog.at_level(logging.DEBUG, logger=APP_LOGGER_NAME):
        announce_debug_mode(False)

    assert caplog.records == []


def _stop_run_before_the_engine(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.app.configure_logging", lambda settings: None)
    monkeypatch.setattr("jarvis.app.ensure_generated", lambda settings: None)
    monkeypatch.setattr(
        "jarvis.app.build_app", lambda settings: _raise(_StopBeforeEngine())
    )


def test_run_announces_debug_mode_at_startup(monkeypatch):
    """The announcement is wired into run() itself, not left to callers -
    every launch path that can set the flag goes through here."""
    announced = []
    monkeypatch.setattr(
        "jarvis.app.announce_debug_mode",
        lambda enabled, path=None: announced.append(enabled),
    )
    monkeypatch.setattr("jarvis.app.configure_debug_transcript", lambda settings: None)
    _stop_run_before_the_engine(monkeypatch)

    for debug, console in ((True, object()), (False, None)):
        with pytest.raises(_StopBeforeEngine):
            asyncio.run(run(settings=_settings(), live_console=console, debug=debug))

    assert announced == [True, False]


def test_a_run_without_debug_turns_any_previous_recording_off(monkeypatch, tmp_path):
    """Review finding (P2, 2026-07-26): the transcript logger is module
    state, so a second run in the same process inherited the first one's
    sink and kept writing request content with nothing announcing it.
    Off has to be an action, not the absence of the enable call."""
    configure_debug_transcript(LoggingSettings(directory=str(tmp_path)))
    assert recording() is True
    _stop_run_before_the_engine(monkeypatch)

    with pytest.raises(_StopBeforeEngine):
        asyncio.run(run(settings=_settings(), live_console=None))

    assert recording() is False


async def test_run_publishes_the_debug_panel_notice_when_debug_is_on(monkeypatch):
    """The panel/log half of slice 4: announce_debug_mode() guarantees the
    file log even without a bus, but the events panel needs one, so this
    fires once app.bus exists - through publish_system_event(), the same
    call every other user-facing fact in this file goes through."""
    bus = EventBus()
    received: list[SystemEvent] = []
    bus.subscribe(SystemEvent, _collecting_subscriber(received))
    app = _fake_app(bus=bus)
    fake_console = types.SimpleNamespace(
        api=types.SimpleNamespace(set_shutdown_event=lambda event: None)
    )
    monkeypatch.setattr(
        "jarvis.app.wire_status_console",
        lambda *args, **kwargs: _raise(_StopBeforeEngine()),
    )

    with pytest.raises(_StopBeforeEngine):
        await run(settings=_settings(), app=app, live_console=fake_console, debug=True)

    assert len(received) == 1
    assert received[0].source == "ENGINE"
    assert received[0].level is EventLevel.WARN
    assert "Debug mode is active" in received[0].message


async def test_run_does_not_publish_the_debug_panel_notice_when_debug_is_off(
    monkeypatch,
):
    bus = EventBus()
    received: list[SystemEvent] = []
    bus.subscribe(SystemEvent, _collecting_subscriber(received))
    app = _fake_app(bus=bus)
    monkeypatch.setattr(
        "jarvis.app.warm_up", lambda *args, **kwargs: _raise(_StopBeforeEngine())
    )

    with pytest.raises(_StopBeforeEngine):
        await run(settings=_settings(), app=app, live_console=None, debug=False)

    assert received == []


async def test_debug_panel_notice_is_localized():
    """Direct test of the helper, independent of run()'s wiring - the
    events panel is a Russian-language, end-user surface (per
    system_log.py's own docstring), so ui_message must actually localize."""
    bus = EventBus()
    received: list[SystemEvent] = []
    bus.subscribe(SystemEvent, _collecting_subscriber(received))
    app = _fake_app(bus=bus)

    await _announce_debug_mode_to_panel(app, "ru")

    assert "Режим отладки активен" in received[0].message


def test_run_refuses_a_headless_debug_launch(monkeypatch):
    """Review finding (P1, 2026-07-25): the CLI gate is not the invariant.
    run() is its own entry point, and a transcript recorded with nothing on
    screen saying so is exactly what the console requirement exists to
    prevent - so the refusal has to live where the flag is used."""
    announced = []
    monkeypatch.setattr("jarvis.app.announce_debug_mode", announced.append)
    _stop_run_before_the_engine(monkeypatch)

    with pytest.raises(ValueError, match="requires the Status Console"):
        asyncio.run(run(settings=_settings(), live_console=None, debug=True))

    assert announced == []


def test_run_without_a_console_is_fine_when_debug_is_off(monkeypatch):
    """The refusal is about debug, not about running headless: a normal
    `python -m jarvis` has no console and must keep working."""
    _stop_run_before_the_engine(monkeypatch)

    with pytest.raises(_StopBeforeEngine):
        asyncio.run(run(settings=_settings(), live_console=None))
