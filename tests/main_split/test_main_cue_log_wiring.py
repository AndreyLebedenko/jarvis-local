import logging
from pathlib import Path

import pytest
from _support_from_test_main import (
    _collecting_subscriber,
    _FakeSoundCues,
    _settings,
)

from jarvis.app import (
    APP_LOGGER_NAME,
    App,
    _on_reasoning_level_changed,
    _on_response_mode_changed,
)
from jarvis.core.bus import EventBus
from jarvis.dialog.response_mode import (
    ResponseMode,
    ResponseModeChanged,
)
from jarvis.dialog.thinking_mode import (
    ReasoningLevel,
    ReasoningLevelChanged,
)
from jarvis.ui.contract import (
    EventLevel,
    SystemEvent,
)

# --- graded reasoning-level cue/log wiring (story-v1.3.1 task 3) ------------


def _app_with_sound_cues(sound_cues, *, ui_config_path: Path | None = None) -> App:
    kwargs = {}
    if ui_config_path is not None:
        kwargs["ui_config_path"] = ui_config_path
    return App(
        bus=EventBus(),
        backend=None,
        audio_input=None,
        tts_output=None,
        capture_input=None,
        orchestrator=None,
        sound_cues=sound_cues,
        thinking_mode=None,
        response_mode=None,
        settings=_settings(),
        **kwargs,
    )


@pytest.mark.parametrize(
    "level,expected_plays",
    [
        (ReasoningLevel.OFF, ["thinking_off"]),
        (ReasoningLevel.LOW, ["thinking_on"]),
        (ReasoningLevel.MEDIUM, ["thinking_on", "thinking_on"]),
        (ReasoningLevel.HIGH, ["thinking_on", "thinking_on", "thinking_on"]),
    ],
)
async def test_reasoning_level_changed_plays_the_graded_cue_sequence(
    level, expected_plays
):
    sound_cues = _FakeSoundCues()
    app = _app_with_sound_cues(sound_cues)

    await _on_reasoning_level_changed(
        app, ReasoningLevelChanged(level=level, source="HOTKEY")
    )

    assert sound_cues.played == expected_plays


@pytest.mark.parametrize(
    "level",
    [
        ReasoningLevel.OFF,
        ReasoningLevel.LOW,
        ReasoningLevel.MEDIUM,
        ReasoningLevel.HIGH,
    ],
)
async def test_reasoning_level_changed_logs_the_exact_level_name(level, caplog):
    app = _app_with_sound_cues(_FakeSoundCues())

    with caplog.at_level(logging.INFO, logger=APP_LOGGER_NAME):
        await _on_reasoning_level_changed(
            app, ReasoningLevelChanged(level=level, source="HOTKEY")
        )

    assert any(level.value in record.message for record in caplog.records)


@pytest.mark.parametrize("source", ["HOTKEY", "UI"])
async def test_reasoning_level_changed_publishes_a_system_event_for_the_ui(source):
    """task-ui-03: the Status Console's events panel gets this through the
    bus, not by scraping the log line above.

    Regression (live human check, 2026-07-13): a Control Center click and a
    hotkey press both used to be logged as "HOTKEY", because the source was
    hardcoded here instead of read from the event - the SystemEvent's
    source must match whichever channel actually changed the level."""
    bus = EventBus()
    received: list[SystemEvent] = []
    bus.subscribe(SystemEvent, _collecting_subscriber(received))
    app = App(
        bus=bus,
        backend=None,
        audio_input=None,
        tts_output=None,
        capture_input=None,
        orchestrator=None,
        sound_cues=_FakeSoundCues(),
        thinking_mode=None,
        response_mode=None,
        settings=_settings(),
    )

    await _on_reasoning_level_changed(
        app, ReasoningLevelChanged(level=ReasoningLevel.MEDIUM, source=source)
    )

    assert len(received) == 1
    assert received[0].source == source
    assert received[0].level is EventLevel.INFO
    assert "medium" in received[0].message.lower()


# --- response mode cue/log wiring (story-v1.9.0 task 2) ---------------------


@pytest.mark.parametrize(
    "mode", [ResponseMode.TEXT, ResponseMode.VOICE, ResponseMode.TEXT_VOICE]
)
async def test_response_mode_changed_plays_no_sound_cue(mode, tmp_path):
    """Unlike the graded reasoning levels, the three response modes are
    named options with no natural beep-count mapping - _on_response_mode_
    changed()'s own design decision, verified here as a regression guard."""
    sound_cues = _FakeSoundCues()
    app = _app_with_sound_cues(sound_cues, ui_config_path=tmp_path / "config.ui.toml")

    await _on_response_mode_changed(
        app, ResponseModeChanged(mode=mode, source="HOTKEY")
    )

    assert sound_cues.played == []


@pytest.mark.parametrize(
    "mode", [ResponseMode.TEXT, ResponseMode.VOICE, ResponseMode.TEXT_VOICE]
)
async def test_response_mode_changed_logs_the_exact_mode_name(mode, caplog, tmp_path):
    app = _app_with_sound_cues(
        _FakeSoundCues(), ui_config_path=tmp_path / "config.ui.toml"
    )

    with caplog.at_level(logging.INFO, logger=APP_LOGGER_NAME):
        await _on_response_mode_changed(
            app, ResponseModeChanged(mode=mode, source="HOTKEY")
        )

    assert any(mode.value in record.message for record in caplog.records)


@pytest.mark.parametrize("source", ["HOTKEY", "UI", "VOICE"])
async def test_response_mode_changed_publishes_a_system_event_for_the_ui(
    source, tmp_path
):
    bus = EventBus()
    received: list[SystemEvent] = []
    bus.subscribe(SystemEvent, _collecting_subscriber(received))
    app = App(
        bus=bus,
        backend=None,
        audio_input=None,
        tts_output=None,
        capture_input=None,
        orchestrator=None,
        sound_cues=_FakeSoundCues(),
        thinking_mode=None,
        response_mode=None,
        settings=_settings(),
        ui_config_path=tmp_path / "config.ui.toml",
    )

    await _on_response_mode_changed(
        app, ResponseModeChanged(mode=ResponseMode.VOICE, source=source)
    )

    assert len(received) == 1
    assert received[0].source == source
    assert received[0].level is EventLevel.INFO
    assert "voice" in received[0].message.lower()


async def test_response_mode_changed_never_persists_for_any_source(tmp_path):
    """Task 3b: the live toggle (Status-tab buttons, Ctrl+Alt+O, and task
    4's voice path) session-overrides only - no source of
    ResponseModeChanged writes config.ui.toml anymore. The persisted
    default changes exclusively through a Settings-tab Apply (write_ui_config
    via save_config_selection), so a hotkey cycle must survive a restart
    untouched."""
    ui_config_path = tmp_path / "config.ui.toml"
    app = _app_with_sound_cues(_FakeSoundCues(), ui_config_path=ui_config_path)

    for source in ("HOTKEY", "UI", "VOICE"):
        await _on_response_mode_changed(
            app, ResponseModeChanged(mode=ResponseMode.VOICE, source=source)
        )

    assert not ui_config_path.exists()
