from _support_from_test_main import (
    _collecting_subscriber,
    _fake_app,
    _FakeSoundCues,
)

from jarvis.app import (
    App,
    _on_microphone_capture_failed,
    unwire,
    wire,
)
from jarvis.audio.input import (
    MicrophoneCaptureFailed,
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

# --- microphone capture failure SystemEvent --------------------------------


async def _capture_failure_event(language: str, reason: str) -> SystemEvent:
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
        settings=Settings(
            journal=JournalSettings(enabled=False), ui=UiSettings(language=language)
        ),
    )

    await _on_microphone_capture_failed(app, MicrophoneCaptureFailed(reason=reason))

    assert len(received) == 1
    return received[0]


async def test_microphone_capture_failure_is_reported_as_an_error_from_stt():
    event = await _capture_failure_event(
        "en", "Multiple input devices found for 'Microphone (Yeti X)'"
    )

    assert event.source == "STT"
    assert event.level is EventLevel.ERROR


async def test_microphone_capture_failure_message_is_localized():
    event = await _capture_failure_event("ru", "device unplugged")

    assert "Микрофон остановлен" in event.message


async def test_microphone_capture_failure_panel_entry_carries_no_device_name():
    """The content rule from the two-log contract: the system log gets the
    driver's own reason, the panel entry gets the fact and the remedy. A
    device name is payload-adjacent and stays out of the panel."""
    event = await _capture_failure_event("en", "Microphone (Yeti X), MME")

    assert "Yeti" not in event.message


async def test_wire_subscribes_the_microphone_capture_failure_reporter():
    """Without this subscription the event is published into nothing and
    the failure is silent again - the exact regression this work fixed."""
    bus = EventBus()
    received: list[SystemEvent] = []
    bus.subscribe(SystemEvent, _collecting_subscriber(received))
    app = _fake_app(bus=bus)
    subscriptions = wire(app)

    await bus.publish(
        MicrophoneCaptureFailed, MicrophoneCaptureFailed(reason="device unplugged")
    )

    assert [event.source for event in received] == ["STT"]

    unwire(app, subscriptions)
