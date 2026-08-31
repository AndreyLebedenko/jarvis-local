import logging

from _support_from_test_main import (
    _collecting_subscriber,
    _FakeAudioInput,
    _FakeSoundCues,
)

from jarvis.app import (
    APP_LOGGER_NAME,
    App,
    _on_mic_sleep_toggled,
)
from jarvis.audio.input import (
    MicSleepToggled,
)
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    JournalSettings,
    Settings,
    UiSettings,
)
from jarvis.ui.contract import (
    EventLevel,
    SystemEvent,
)

# --- mic sleep/wake sound cue (task-10) -------------------------------------


def _app_for_mic_toggle(
    *,
    bus: EventBus | None = None,
    sound_cues=None,
    capture_failed: bool = False,
    language: str = "en",
) -> App:
    audio_input = _FakeAudioInput()
    audio_input.capture_failed = capture_failed
    return App(
        bus=bus or EventBus(),
        backend=None,
        audio_input=audio_input,
        tts_output=None,
        capture_input=None,
        orchestrator=None,
        sound_cues=sound_cues or _FakeSoundCues(),
        thinking_mode=None,
        response_mode=None,
        settings=Settings(
            journal=JournalSettings(enabled=False), ui=UiSettings(language=language)
        ),
    )


async def test_on_mic_sleep_toggled_plays_mic_sleep_cue_when_asleep():
    sound_cues = _FakeSoundCues()
    app = _app_for_mic_toggle(sound_cues=sound_cues)

    await _on_mic_sleep_toggled(app, MicSleepToggled(is_awake=False))

    assert sound_cues.played == ["mic_sleep"]


async def test_on_mic_sleep_toggled_plays_mic_wake_cue_when_awake():
    sound_cues = _FakeSoundCues()
    app = _app_for_mic_toggle(sound_cues=sound_cues)

    await _on_mic_sleep_toggled(app, MicSleepToggled(is_awake=True))

    assert sound_cues.played == ["mic_wake"]


async def test_on_mic_sleep_toggled_logs_an_info_message(caplog):
    """Observability follow-up from task-10's human review: INFO-level
    logging was silently dropped everywhere (nothing in the process
    configured a handler for it), making state transitions like this one
    impossible to confirm from the console."""
    app = _app_for_mic_toggle()

    with caplog.at_level(logging.INFO, logger=APP_LOGGER_NAME):
        await _on_mic_sleep_toggled(app, MicSleepToggled(is_awake=False))

    assert any("asleep" in record.message for record in caplog.records)


async def test_on_mic_sleep_toggled_publishes_a_system_event_for_the_ui():
    """task-ui-03: the Status Console's events panel gets this through the
    bus, not by scraping the log line above."""
    bus = EventBus()
    received: list[SystemEvent] = []
    bus.subscribe(SystemEvent, _collecting_subscriber(received))
    app = _app_for_mic_toggle(bus=bus)

    await _on_mic_sleep_toggled(app, MicSleepToggled(is_awake=False))

    assert len(received) == 1
    assert received[0].source == "HOTKEY"
    assert received[0].level is EventLevel.INFO
    assert "sleep" in received[0].message


# --- the sleep toggle after capture has died ---------------------------------
# Grounded in the state machine pinned by tests/test_audio_in.py: nothing
# restarts the loop within a session, and a restart never carries a mute
# forward, so there is no "muted but available again" state to preserve.


async def test_the_sleep_toggle_reports_the_stopped_microphone_instead_of_wake():
    bus = EventBus()
    received: list[SystemEvent] = []
    bus.subscribe(SystemEvent, _collecting_subscriber(received))
    app = _app_for_mic_toggle(bus=bus, capture_failed=True)

    await _on_mic_sleep_toggled(app, MicSleepToggled(is_awake=True))

    assert len(received) == 1
    assert received[0].source == "HOTKEY"
    assert received[0].level is EventLevel.WARN
    assert "stopped" in received[0].message
    assert "awake" not in received[0].message


async def test_the_stopped_microphone_notice_is_localized():
    bus = EventBus()
    received: list[SystemEvent] = []
    bus.subscribe(SystemEvent, _collecting_subscriber(received))
    app = _app_for_mic_toggle(bus=bus, capture_failed=True, language="ru")

    await _on_mic_sleep_toggled(app, MicSleepToggled(is_awake=True))

    assert "Микрофон остановлен" in received[0].message


async def test_the_cue_after_a_capture_failure_never_claims_a_wake():
    """ "Not capturing" is true in both directions once the loop is gone,
    so the sleep cue is the only honest sound to answer the keypress
    with - the wake cue would be the audible half of the same lie."""
    sound_cues = _FakeSoundCues()
    app = _app_for_mic_toggle(sound_cues=sound_cues, capture_failed=True)

    await _on_mic_sleep_toggled(app, MicSleepToggled(is_awake=True))
    await _on_mic_sleep_toggled(app, MicSleepToggled(is_awake=False))

    assert sound_cues.played == ["mic_sleep", "mic_sleep"]
