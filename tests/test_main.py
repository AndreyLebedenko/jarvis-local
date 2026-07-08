import asyncio
import base64
import json
import logging
from collections.abc import Callable

import httpx

from audio_in import AudioInput, MicSleepToggled, UtteranceChunk
from backend import BackendSettings, LatencyMetrics, OllamaBackend, ResponseComplete, ResponseToken
from capture import ScreenshotCaptured
from clipboard_input import ClipboardSubmitted
from config import MicrophoneSettings, Settings, VadSettings
from bus import EventBus
from main import (
    SYSTEM_PROMPT,
    App,
    ConversationHistory,
    Orchestrator,
    _on_full_response_complete,
    _on_mic_sleep_toggled,
    _on_thinking_mode_toggled,
    build_app,
    create_live_status_console,
    is_elevated,
    parse_args,
    run_clipboard_hotkey_listener,
    run_mic_sleep_hotkey_listener,
    run_thinking_hotkey_listener,
    run_until_shutdown,
    unwire,
    warm_up,
    wire,
    wire_status_console,
)
from sound_cues import SoundCuePlayer
from status_console import MicrophoneOptionsAvailable, ModelOptionsAvailable, UiConfigSaved
from thinking_mode import ThinkingModeState, ThinkingModeToggled
from ui_contract import (
    DataLocality,
    EventLevel,
    HealthStatus,
    ModuleHealth,
    ModuleId,
    RuntimeState,
    SystemEvent,
    VisibilityMode,
)
from visibility_mode import VisibilityModeChanged


class _FakeBackend:
    def __init__(self, chat_impl=None) -> None:
        self.calls: list[tuple[list[dict], list[str] | None]] = []
        self.thinking_enabled_calls: list[bool] = []
        self._chat_impl = chat_impl

    async def chat(self, messages, images_b64=None, thinking_enabled=False) -> None:
        self.calls.append((messages, images_b64))
        self.thinking_enabled_calls.append(thinking_enabled)
        if self._chat_impl is not None:
            await self._chat_impl()


class _FakeSoundCues:
    def __init__(self) -> None:
        self.played: list[str] = []

    async def play(self, cue: str) -> None:
        self.played.append(cue)


def _complete_event() -> ResponseComplete:
    return ResponseComplete(
        metrics=LatencyMetrics(load_seconds=0, prompt_eval_seconds=0, eval_seconds=0, eval_count=0)
    )


# --- system prompt -----------------------------------------------------


def test_system_prompt_includes_russian_and_short_answer_directives():
    assert "по-русски" in SYSTEM_PROMPT
    assert "коротко" in SYSTEM_PROMPT


# --- ConversationHistory (text-only, extensible) ------------------------


def test_history_messages_are_text_only_by_default():
    history = ConversationHistory()
    history.add("user", "привет")
    history.add("assistant", "привет!")

    messages = history.as_messages()

    assert messages == [
        {"role": "user", "content": "привет"},
        {"role": "assistant", "content": "привет!"},
    ]
    assert all("images" not in m for m in messages)


def test_history_messages_include_media_when_provided():
    """v1.0 never calls add() with media_b64, but the mechanism already
    works - a later release extending history to carry media doesn't
    need to restructure this class."""
    history = ConversationHistory()
    history.add("user", "смотри", media_b64=("base64data",))

    [message] = history.as_messages()

    assert message["images"] == ["base64data"]


def test_clear_drops_every_recorded_turn():
    """task-ui-04's global context reset."""
    history = ConversationHistory()
    history.add("user", "привет")
    history.add("assistant", "привет!")

    history.clear()

    assert history.as_messages() == []


# --- Orchestrator --------------------------------------------------------


def _orchestrator(
    chat_impl=None, audio_input=None, thinking_mode=None
) -> tuple[Orchestrator, _FakeBackend, _FakeSoundCues]:
    backend = _FakeBackend(chat_impl)
    sound_cues = _FakeSoundCues()
    orchestrator = Orchestrator(
        backend, ConversationHistory(), sound_cues, audio_input=audio_input, thinking_mode=thinking_mode
    )
    return orchestrator, backend, sound_cues


async def test_on_utterance_sends_media_and_plays_thinking_cue():
    orchestrator, backend, sound_cues = _orchestrator()

    await orchestrator.on_screenshot(ScreenshotCaptured(png_bytes=b"png", mode="full", width=1, height=1))
    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"wav", start_seconds=0, end_seconds=1))

    assert sound_cues.played == ["thinking"]
    [(messages, media)] = backend.calls
    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert messages[-1] == {"role": "user", "content": "[голосовое сообщение]"}
    # audio first, then the pending screenshot
    assert media == [base64.b64encode(b"wav").decode(), base64.b64encode(b"png").decode()]


async def test_on_utterance_without_screenshot_sends_only_audio():
    orchestrator, backend, sound_cues = _orchestrator()

    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"wav", start_seconds=0, end_seconds=1))

    [(_messages, media)] = backend.calls
    assert len(media) == 1


async def test_screenshot_is_consumed_once_not_resent_on_next_utterance():
    orchestrator, backend, _ = _orchestrator()

    await orchestrator.on_screenshot(ScreenshotCaptured(png_bytes=b"png", mode="full", width=1, height=1))
    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"wav1", start_seconds=0, end_seconds=1))
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()  # normally called after wait_for_pending() - see wire()
    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"wav2", start_seconds=0, end_seconds=1))

    assert len(backend.calls[0][1]) == 2  # first turn: audio + screenshot
    assert len(backend.calls[1][1]) == 1  # second turn: audio only


# --- Orchestrator: clipboard turns (task-08) ------------------------------
#
# on_clipboard() goes through the same _start_turn() shared path as
# on_utterance() - these tests confirm the shared behavior (busy-guard,
# thinking cue, history recording) rather than re-testing it from
# scratch, plus the clipboard-specific behavior (real text, no media,
# truncation/empty handling).


async def test_on_clipboard_sends_real_text_with_no_media():
    orchestrator, backend, sound_cues = _orchestrator()

    await orchestrator.on_clipboard(
        ClipboardSubmitted(text="print('hi')", truncated=False, is_empty=False)
    )

    assert sound_cues.played == ["clipboard", "thinking"]
    [(messages, media)] = backend.calls
    assert messages[-1] == {"role": "user", "content": "print('hi')"}
    assert media is None


async def test_on_clipboard_truncated_plays_input_error_instead_of_clipboard_cue():
    orchestrator, backend, sound_cues = _orchestrator()

    await orchestrator.on_clipboard(
        ClipboardSubmitted(text="truncated text [...]", truncated=True, is_empty=False)
    )

    assert sound_cues.played == ["input_error", "thinking"]
    assert len(backend.calls) == 1  # still starts the turn - truncation is recoverable


async def test_on_clipboard_empty_plays_input_error_and_does_not_start_a_turn():
    orchestrator, backend, sound_cues = _orchestrator()

    await orchestrator.on_clipboard(ClipboardSubmitted(text="", truncated=False, is_empty=True))

    assert sound_cues.played == ["input_error"]
    assert backend.calls == []


async def test_clipboard_submission_does_not_consume_pending_screenshot():
    orchestrator, backend, _sound_cues = _orchestrator()

    await orchestrator.on_screenshot(
        ScreenshotCaptured(png_bytes=b"png", mode="full", width=1, height=1)
    )
    await orchestrator.on_clipboard(
        ClipboardSubmitted(text="some code", truncated=False, is_empty=False)
    )
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"wav", start_seconds=0, end_seconds=1)
    )

    assert backend.calls[0][1] is None  # clipboard turn: no media at all
    assert len(backend.calls[1][1]) == 2  # audio turn: screenshot survived


async def test_on_clipboard_records_real_text_in_history_not_a_placeholder():
    orchestrator, _backend, _sound_cues = _orchestrator()

    await orchestrator.on_clipboard(
        ClipboardSubmitted(text="какой сегодня день?", truncated=False, is_empty=False)
    )
    await orchestrator.on_response_token(ResponseToken(text="Сегодня четверг."))
    await orchestrator.on_response_complete(_complete_event())

    messages = orchestrator._history.as_messages()
    assert messages[-2] == {"role": "user", "content": "какой сегодня день?"}
    assert messages[-1] == {"role": "assistant", "content": "Сегодня четверг."}


async def test_clipboard_turn_is_ignored_while_busy_same_as_audio():
    """Regression test for a real bug: on_clipboard() used to play its
    ack/warning cue ("clipboard" or "input_error") before checking busy,
    so a submission silently dropped by the busy-guard still told the
    user it had been received. Confirms the cue does not play either -
    not just that the backend was not called."""
    still_busy = asyncio.Event()

    async def slow_chat() -> None:
        await still_busy.wait()

    orchestrator, backend, sound_cues = _orchestrator(chat_impl=slow_chat)

    first = asyncio.create_task(
        orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1))
    )
    await asyncio.sleep(0)
    await orchestrator.on_clipboard(
        ClipboardSubmitted(text="ignored while busy", truncated=False, is_empty=False)
    )

    assert len(backend.calls) == 1  # the clipboard submission was ignored
    assert "clipboard" not in sound_cues.played
    assert "input_error" not in sound_cues.played

    still_busy.set()
    await first


async def test_on_response_token_plays_speaking_cue_only_once():
    orchestrator, _backend, sound_cues = _orchestrator()

    await orchestrator.on_response_token(ResponseToken(text="Привет"))
    await orchestrator.on_response_token(ResponseToken(text=", мир"))

    assert sound_cues.played.count("speaking") == 1


async def test_on_response_complete_records_history():
    orchestrator, _backend, _sound_cues = _orchestrator()

    await orchestrator.on_response_token(ResponseToken(text="Привет"))
    await orchestrator.on_response_token(ResponseToken(text=", мир"))
    await orchestrator.on_response_complete(_complete_event())

    messages = orchestrator._history.as_messages()
    assert messages[-2] == {"role": "user", "content": "[голосовое сообщение]"}
    assert messages[-1] == {"role": "assistant", "content": "Привет, мир"}


async def test_busy_utterance_is_ignored_until_previous_turn_completes():
    still_busy = asyncio.Event()

    async def slow_chat() -> None:
        await still_busy.wait()

    orchestrator, backend, _sound_cues = _orchestrator(chat_impl=slow_chat)

    first = asyncio.create_task(
        orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1))
    )
    await asyncio.sleep(0)  # let the first call start and set _busy
    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1))

    assert len(backend.calls) == 1  # second utterance was ignored while busy

    still_busy.set()
    await first


async def test_ignored_utterance_while_busy_does_not_consume_pending_screenshot():
    """Regression test for a real bug: on_utterance() used to consume
    _pending_screenshot_b64 before _start_turn()'s busy-guard could reject
    the turn, permanently losing a screenshot meant for the next turn if
    the utterance that happened to arrive while busy already had one
    pending. The busy-check must happen before any screenshot consumption."""
    still_busy = asyncio.Event()

    async def slow_chat() -> None:
        await still_busy.wait()

    orchestrator, backend, _sound_cues = _orchestrator(chat_impl=slow_chat)

    first = asyncio.create_task(
        orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1))
    )
    await asyncio.sleep(0)  # let the first call start and set _busy

    await orchestrator.on_screenshot(
        ScreenshotCaptured(png_bytes=b"png", mode="full", width=1, height=1)
    )
    # ignored while busy - the screenshot above must survive this
    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1))

    still_busy.set()
    await first
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()

    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"c", start_seconds=0, end_seconds=1))

    assert len(backend.calls) == 2  # "b" was ignored; "a" and "c" went through
    assert len(backend.calls[-1][1]) == 2  # "c" still got the screenshot from before "b"


async def test_finish_turn_cooldown_rejects_a_self_heard_echo():
    """Regression test for a real bug: after Jarvis stops speaking,
    audio_in.py can still be sitting on a self-heard "utterance" (its own
    voice picked up by the mic - no echo cancellation in v1.0) for up to
    request_end_pause_seconds before it publishes it. If busy had already
    cleared by then, that echo was accepted and answered as if it were a
    genuine new question - Jarvis talking to itself. finish_turn()'s
    cooldown keeps busy True for that whole window."""
    orchestrator, backend, _sound_cues = _orchestrator()
    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1))
    await orchestrator.on_response_complete(_complete_event())

    finish_task = asyncio.create_task(orchestrator.finish_turn(cooldown_seconds=0.05))
    await asyncio.sleep(0)  # let finish_turn() start its cooldown sleep

    # still within the cooldown: a self-heard echo must be rejected, same as mid-turn
    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"echo", start_seconds=0, end_seconds=1))
    assert len(backend.calls) == 1

    await finish_task  # cooldown elapses, busy clears

    # a genuine new utterance after the cooldown is accepted
    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1))
    assert len(backend.calls) == 2


# --- mic auto-pause during speech (task-10, layered on the cooldown above) --


class _FakeAudioInputForEcho:
    """Records calls only - the "must not override an explicit user
    privacy sleep" guarantee no longer lives in Orchestrator (see
    audio_in.py's AudioInput.auto_pause_for_speech()/
    auto_resume_after_speech(), which own that composition themselves
    now, per task-10's review). Orchestrator just calls these
    unconditionally around a turn's speech."""

    def __init__(self) -> None:
        self.auto_pause_calls = 0
        self.auto_resume_calls = 0

    async def auto_pause_for_speech(self) -> None:
        self.auto_pause_calls += 1

    async def auto_resume_after_speech(self) -> None:
        self.auto_resume_calls += 1


async def test_speaking_auto_pauses_mic_and_resumes_after_cooldown():
    audio_input = _FakeAudioInputForEcho()
    orchestrator, _backend, _sound_cues = _orchestrator(audio_input=audio_input)

    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1))
    await orchestrator.on_response_token(ResponseToken(text="Привет"))

    assert audio_input.auto_pause_calls == 1
    assert audio_input.auto_resume_calls == 0

    finish_task = asyncio.create_task(orchestrator.finish_turn(cooldown_seconds=0.05))
    await asyncio.sleep(0)
    assert audio_input.auto_resume_calls == 0  # still within the cooldown

    await finish_task

    assert audio_input.auto_resume_calls == 1


async def test_turn_with_no_speech_does_not_auto_pause_or_resume():
    """A turn that never produces a response token (e.g. an empty
    response) never starts speaking, so there is nothing for the mic
    auto-pause to do either."""
    audio_input = _FakeAudioInputForEcho()
    orchestrator, _backend, _sound_cues = _orchestrator(audio_input=audio_input)

    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1))
    await orchestrator.finish_turn()  # no response token in this turn

    assert audio_input.auto_pause_calls == 0
    assert audio_input.auto_resume_calls == 1  # finish_turn() always resumes - harmless no-op


async def test_error_during_chat_plays_error_cue_and_clears_busy():
    async def failing_chat() -> None:
        raise ValueError("boom")

    orchestrator, backend, sound_cues = _orchestrator(chat_impl=failing_chat)

    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1))

    assert sound_cues.played == ["thinking", "error"]

    # busy was cleared, so a subsequent utterance is not ignored
    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1))
    assert len(backend.calls) == 2


# --- thinking mode (task-13) ------------------------------------------------
#
# Orchestrator samples ThinkingModeState.is_enabled at turn start (in
# _start_turn(), synchronously with no `await` before the value reaches
# backend.chat()) and passes it through, per the story's decision that a
# hotkey toggle applies to the next accepted turn, not any request already
# in flight.


async def test_start_turn_passes_thinking_enabled_false_by_default():
    thinking_mode = ThinkingModeState(bus=EventBus())
    orchestrator, backend, _sound_cues = _orchestrator(thinking_mode=thinking_mode)

    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1))

    assert backend.thinking_enabled_calls == [False]


async def test_start_turn_passes_thinking_enabled_true_after_toggle():
    thinking_mode = ThinkingModeState(bus=EventBus())
    orchestrator, backend, _sound_cues = _orchestrator(thinking_mode=thinking_mode)

    await thinking_mode.toggle()
    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1))

    assert backend.thinking_enabled_calls == [True]


async def test_toggle_while_busy_does_not_affect_the_in_flight_turn():
    """Regression guard for the story's explicit boundary: changing a live
    Ollama stream mid-response is out of scope. A toggle that lands while
    a turn's backend.chat() call is already in flight must not retroactively
    change what was already passed for that call - only the next accepted
    turn should see the new value."""
    still_busy = asyncio.Event()

    async def slow_chat() -> None:
        await still_busy.wait()

    thinking_mode = ThinkingModeState(bus=EventBus())
    orchestrator, backend, _sound_cues = _orchestrator(chat_impl=slow_chat, thinking_mode=thinking_mode)

    first = asyncio.create_task(
        orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1))
    )
    await asyncio.sleep(0)  # let the first call start and sample thinking_enabled=False

    await thinking_mode.toggle()  # toggled to True while the first call is in flight

    still_busy.set()
    await first

    assert backend.thinking_enabled_calls == [False]  # the in-flight call was unaffected

    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()
    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1))

    assert backend.thinking_enabled_calls == [False, True]  # next accepted turn sees the new value


async def test_start_turn_with_no_thinking_mode_defaults_to_false():
    """Orchestrator can be constructed without a thinking_mode (e.g. older
    tests/callers) - must not crash, and must behave as if thinking is
    permanently disabled."""
    orchestrator, backend, _sound_cues = _orchestrator()

    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1))

    assert backend.thinking_enabled_calls == [False]


# --- thinking mode cue/log wiring (task-13) ---------------------------------


async def test_on_thinking_mode_toggled_plays_thinking_on_cue_when_enabled():
    sound_cues = _FakeSoundCues()
    app = App(
        bus=EventBus(),
        backend=None,
        audio_input=None,
        tts_output=None,
        capture_input=None,
        orchestrator=None,
        sound_cues=sound_cues,
        thinking_mode=None,
        settings=_settings(),
    )

    await _on_thinking_mode_toggled(app, ThinkingModeToggled(is_enabled=True))

    assert sound_cues.played == ["thinking_on"]


async def test_on_thinking_mode_toggled_plays_thinking_off_cue_when_disabled():
    sound_cues = _FakeSoundCues()
    app = App(
        bus=EventBus(),
        backend=None,
        audio_input=None,
        tts_output=None,
        capture_input=None,
        orchestrator=None,
        sound_cues=sound_cues,
        thinking_mode=None,
        settings=_settings(),
    )

    await _on_thinking_mode_toggled(app, ThinkingModeToggled(is_enabled=False))

    assert sound_cues.played == ["thinking_off"]


async def test_on_thinking_mode_toggled_logs_an_info_message(caplog):
    app = App(
        bus=EventBus(),
        backend=None,
        audio_input=None,
        tts_output=None,
        capture_input=None,
        orchestrator=None,
        sound_cues=_FakeSoundCues(),
        thinking_mode=None,
        settings=_settings(),
    )

    with caplog.at_level(logging.INFO, logger="main"):
        await _on_thinking_mode_toggled(app, ThinkingModeToggled(is_enabled=True))

    assert any("enabled" in record.message for record in caplog.records)

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="main"):
        await _on_thinking_mode_toggled(app, ThinkingModeToggled(is_enabled=False))

    assert any("disabled" in record.message for record in caplog.records)


async def test_on_thinking_mode_toggled_publishes_a_system_event_for_the_ui(caplog):
    """task-ui-03: the Status Console's events panel gets this through the
    bus, not by scraping the log line above."""
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
        settings=_settings(),
    )

    with caplog.at_level(logging.INFO, logger="main"):
        await _on_thinking_mode_toggled(app, ThinkingModeToggled(is_enabled=True))

    assert len(received) == 1
    assert received[0].source == "HOTKEY"
    assert received[0].level is EventLevel.INFO
    assert "включ" in received[0].message


# --- warm-up SystemEvent (task-ui-03) ---------------------------------------


async def test_warm_up_publishes_info_system_event_on_success():
    bus = EventBus()
    received: list[SystemEvent] = []
    bus.subscribe(SystemEvent, _collecting_subscriber(received))

    await warm_up(_FakeBackend(), bus)

    assert len(received) == 1
    assert received[0].source == "WARMUP"
    assert received[0].level is EventLevel.INFO


async def test_warm_up_publishes_warn_system_event_and_still_logs_exception_on_failure(caplog):
    bus = EventBus()
    received: list[SystemEvent] = []
    bus.subscribe(SystemEvent, _collecting_subscriber(received))

    async def failing_chat() -> None:
        raise RuntimeError("Ollama unreachable")

    backend = _FakeBackend(chat_impl=failing_chat)

    with caplog.at_level(logging.ERROR, logger="main"):
        await warm_up(backend, bus)

    assert any(record.levelno == logging.ERROR for record in caplog.records)  # logger.exception
    assert len(received) == 1
    assert received[0].source == "WARMUP"
    assert received[0].level is EventLevel.WARN


# --- wiring --------------------------------------------------------------


class _FakeAudioInput:
    is_awake = True

    async def stop(self) -> None:
        return None


class _FakeTtsOutput:
    async def on_token(self, event) -> None:
        pass

    async def on_response_complete(self, event) -> None:
        pass

    async def wait_for_pending(self) -> None:
        return None


class _FakeCaptureInput:
    pass


class _FakeStatusSurface:
    def __init__(self) -> None:
        self.created_with_api: object | None = None
        self.close_calls = 0
        self.runtime_states: list[tuple[RuntimeState, str | None]] = []
        self.model_labels: list[str] = []
        self.localities: list[DataLocality] = []
        self.thinking_modes: list[bool] = []
        self.visibility_modes: list[VisibilityMode] = []
        self.system_events: list[SystemEvent] = []
        self.module_health: list[ModuleHealth] = []
        self.model_options: list[tuple[list[str], str]] = []
        self.microphone_options: list[tuple[list[str], str]] = []
        self.pending_restart: list[bool] = []

    def create(self, js_api: object | None = None) -> object:
        self.created_with_api = js_api
        return object()

    def close(self) -> None:
        self.close_calls += 1

    def push_runtime_state(self, state: RuntimeState, substatus: str | None = None) -> None:
        self.runtime_states.append((state, substatus))

    def push_model_label(self, label: str) -> None:
        self.model_labels.append(label)

    def push_data_locality(self, locality: DataLocality) -> None:
        self.localities.append(locality)

    def push_thinking_mode(self, is_enabled: bool) -> None:
        self.thinking_modes.append(is_enabled)

    def push_visibility_mode(self, mode: VisibilityMode) -> None:
        self.visibility_modes.append(mode)

    def push_system_event(self, event: SystemEvent) -> None:
        self.system_events.append(event)

    def push_module_health(self, health: ModuleHealth) -> None:
        self.module_health.append(health)

    def push_model_options(self, options: list[str], current: str) -> None:
        self.model_options.append((options, current))

    def push_microphone_options(self, options: list[str], current: str) -> None:
        self.microphone_options.append((options, current))

    def push_pending_restart(self, pending: bool) -> None:
        self.pending_restart.append(pending)


def _settings() -> Settings:
    return Settings()


def _collecting_subscriber(items: list) -> Callable:
    """bus.py awaits every handler, so a plain list.append cannot be
    subscribed directly (it isn't a coroutine function) - wrap it."""

    async def on_event(event) -> None:
        items.append(event)

    return on_event


def _fake_app() -> App:
    """build_app() with fakes for every hardware-touching module, plus a
    fake backend so a bug in unwire()/shutdown can never trigger a real
    network call - not just "shouldn't happen if the code is correct"."""
    return build_app(
        _settings(),
        backend=_FakeBackend(),
        audio_input=_FakeAudioInput(),
        tts_output=_FakeTtsOutput(),
        capture_input=_FakeCaptureInput(),
    )


def test_wire_registers_expected_subscriptions():
    app = _fake_app()

    subscriptions = wire(app)
    event_types = [event_type for event_type, _handler in subscriptions]

    assert event_types.count(UtteranceChunk) == 1
    assert event_types.count(ScreenshotCaptured) == 1
    assert event_types.count(ClipboardSubmitted) == 1
    assert event_types.count(ResponseToken) == 2  # tts_output + orchestrator
    # A single coordinating handler, not three concurrent subscribers -
    # see _on_full_response_complete's docstring for why that mattered.
    assert event_types.count(ResponseComplete) == 1
    assert event_types.count(MicSleepToggled) == 1
    assert event_types.count(ThinkingModeToggled) == 1

    handlers = [handler for _event_type, handler in subscriptions]
    assert app.orchestrator.on_utterance in handlers
    assert app.orchestrator.on_screenshot in handlers
    assert app.orchestrator.on_clipboard in handlers


def test_create_live_status_console_shares_one_api_between_surfaces():
    app = _fake_app()
    console = _FakeStatusSurface()
    touchstrip = _FakeStatusSurface()

    live_console = create_live_status_console(
        app, console=console, touchstrip=touchstrip, include_touchstrip=True
    )

    assert live_console.api is console.created_with_api
    assert live_console.api is touchstrip.created_with_api


def test_live_status_console_closes_all_surfaces():
    app = _fake_app()
    console = _FakeStatusSurface()
    touchstrip = _FakeStatusSurface()
    live_console = create_live_status_console(
        app, console=console, touchstrip=touchstrip, include_touchstrip=True
    )

    live_console.close()
    live_console.close()

    assert console.close_calls == 2
    assert touchstrip.close_calls == 2


async def test_wire_status_console_pushes_initial_state_and_live_events():
    app = _fake_app()
    console = _FakeStatusSurface()
    touchstrip = _FakeStatusSurface()
    live_console = create_live_status_console(
        app, console=console, touchstrip=touchstrip, include_touchstrip=True
    )

    subscriptions = wire_status_console(app, live_console, asyncio.get_running_loop())

    assert console.model_labels == [app.settings.backend.model]
    assert touchstrip.model_labels == [app.settings.backend.model]
    assert console.localities == [DataLocality.LOCAL]
    assert touchstrip.localities == [DataLocality.LOCAL]
    assert console.thinking_modes == [False]
    assert touchstrip.thinking_modes == [False]
    assert console.visibility_modes == [VisibilityMode.OPEN]
    assert touchstrip.visibility_modes == [VisibilityMode.OPEN]
    assert console.module_health == [
        ModuleHealth(module=ModuleId.MICROPHONE, status=HealthStatus.OK, detail="слушает")
    ]
    assert touchstrip.module_health == [
        ModuleHealth(module=ModuleId.MICROPHONE, status=HealthStatus.OK, detail="слушает")
    ]
    assert console.runtime_states == [(RuntimeState.WARMING, "Прогреваю модель...")]

    await app.bus.publish(
        SystemEvent,
        SystemEvent(timestamp=1, source="ENGINE", level=EventLevel.INFO, message="ok"),
    )
    await app.bus.publish(
        VisibilityModeChanged, VisibilityModeChanged(mode=VisibilityMode.HIDDEN)
    )
    await app.bus.publish(ResponseToken, ResponseToken(text="Привет"))

    assert [event.message for event in console.system_events] == ["ok"]
    assert touchstrip.system_events == []
    assert console.visibility_modes[-1] is VisibilityMode.HIDDEN
    assert touchstrip.visibility_modes[-1] is VisibilityMode.HIDDEN
    assert console.runtime_states[-1] == (RuntimeState.SPEAKING, "Произношу ответ...")
    assert touchstrip.runtime_states[-1] == (RuntimeState.SPEAKING, "Произношу ответ...")

    unwire(app, subscriptions)


async def test_wire_status_console_updates_microphone_chip_from_mic_sleep_events():
    app = _fake_app()
    console = _FakeStatusSurface()
    touchstrip = _FakeStatusSurface()
    live_console = create_live_status_console(
        app, console=console, touchstrip=touchstrip, include_touchstrip=True
    )
    subscriptions = wire_status_console(app, live_console, asyncio.get_running_loop())

    await app.bus.publish(MicSleepToggled, MicSleepToggled(is_awake=False))
    await app.bus.publish(MicSleepToggled, MicSleepToggled(is_awake=True))

    expected = [
        ModuleHealth(
            module=ModuleId.MICROPHONE,
            status=HealthStatus.OK,
            detail="слушает",
        ),
        ModuleHealth(
            module=ModuleId.MICROPHONE,
            status=HealthStatus.UNAVAILABLE,
            detail="усыплён",
        ),
        ModuleHealth(
            module=ModuleId.MICROPHONE,
            status=HealthStatus.OK,
            detail="слушает",
        ),
    ]
    assert console.module_health == expected
    assert touchstrip.module_health == expected

    unwire(app, subscriptions)


async def test_wire_status_console_routes_config_menu_events_to_desktop_only():
    """story-v1.2.4-task-3: config menu is desktop-only (Scope decision) -
    ModelOptionsAvailable/MicrophoneOptionsAvailable/UiConfigSaved must
    reach console but never touchstrip, unlike most other state here."""
    app = _fake_app()
    console = _FakeStatusSurface()
    touchstrip = _FakeStatusSurface()
    live_console = create_live_status_console(
        app, console=console, touchstrip=touchstrip, include_touchstrip=True
    )
    subscriptions = wire_status_console(app, live_console, asyncio.get_running_loop())

    await app.bus.publish(
        ModelOptionsAvailable,
        ModelOptionsAvailable(options=["a", "b"], current="a"),
    )
    await app.bus.publish(
        MicrophoneOptionsAvailable,
        MicrophoneOptionsAvailable(options=["mic-1"], current="mic-1"),
    )
    await app.bus.publish(UiConfigSaved, UiConfigSaved())

    assert console.model_options == [(["a", "b"], "a")]
    assert console.microphone_options == [(["mic-1"], "mic-1")]
    assert console.pending_restart == [True]
    assert touchstrip.model_options == []
    assert touchstrip.microphone_options == []
    assert touchstrip.pending_restart == []

    unwire(app, subscriptions)


async def test_wire_with_live_status_console_reports_thinking_before_accepted_turn():
    app = _fake_app()
    console = _FakeStatusSurface()
    live_console = create_live_status_console(app, console=console, include_touchstrip=False)
    wire(app, live_console)

    await app.bus.publish(
        UtteranceChunk, UtteranceChunk(wav_bytes=b"x", start_seconds=0, end_seconds=1)
    )

    assert console.runtime_states == [(RuntimeState.THINKING, "Обрабатываю голос...")]


async def test_wire_pushes_listening_state_after_response_complete():
    """Regression for a real live-session bug (2026-07-07): RuntimeState
    stayed stuck on SPEAKING ("Отвечаю") forever after the very first
    turn - nothing ever pushed the orb back to LISTENING once
    ResponseComplete fired, even though the engine kept handling later
    turns correctly in the background (sound_cues' own "listening" cue
    already played correctly every turn in _on_full_response_complete();
    only the Status Console's own runtime-state push was missing). The
    SPEAKING push itself is registered by wire_status_console(), not
    wire() (this fix's home) - both run together in main.py's real run(),
    so this test only needs to prove wire()'s own ResponseComplete
    handler pushes LISTENING, independent of that other wiring."""
    settings = Settings(vad=VadSettings(request_end_pause_seconds=0.001))
    app = build_app(
        settings,
        backend=_FakeBackend(),
        audio_input=_FakeAudioInputForEcho(),
        tts_output=_FakeTtsOutput(),
        capture_input=_FakeCaptureInput(),
    )
    console = _FakeStatusSurface()
    live_console = create_live_status_console(app, console=console, include_touchstrip=False)
    wire(app, live_console)

    await app.bus.publish(
        ResponseComplete, ResponseComplete(metrics=LatencyMetrics(0.0, 0.0, 0.0, 1))
    )

    assert console.runtime_states == [(RuntimeState.LISTENING, "Готов слушать")]


def test_parse_args_enables_status_console_without_touchstrip():
    args = parse_args(["--status-console", "--no-touchstrip"])

    assert args.status_console is True
    assert args.no_touchstrip is True


async def test_unwire_removes_all_subscriptions():
    app = _fake_app()
    subscriptions = wire(app)

    unwire(app, subscriptions)

    # the orchestrator's own handler should no longer be subscribed - if
    # it were, backend.chat() would have been called
    await app.bus.publish(
        UtteranceChunk, UtteranceChunk(wav_bytes=b"x", start_seconds=0, end_seconds=1)
    )
    assert app.backend.calls == []


# --- shutdown --------------------------------------------------------------


async def test_run_until_shutdown_cancels_tasks_and_unsubscribes():
    app = _fake_app()
    subscriptions = wire(app)
    shutdown_event = asyncio.Event()
    background_tasks = [asyncio.create_task(asyncio.Event().wait()) for _ in range(2)]

    shutdown_event.set()
    await asyncio.wait_for(
        run_until_shutdown(app, subscriptions, shutdown_event, background_tasks),
        timeout=2,
    )

    assert all(task.cancelled() for task in background_tasks)

    # confirm unsubscribed: publishing no longer reaches the orchestrator
    await app.bus.publish(
        UtteranceChunk, UtteranceChunk(wav_bytes=b"x", start_seconds=0, end_seconds=1)
    )
    assert app.backend.calls == []


class _FakeKeyboardModuleForShutdownTest:
    def __init__(self) -> None:
        self.removed_handles: list[object] = []

    def add_hotkey(self, binding, callback):
        return object()

    def remove_hotkey(self, handle) -> None:
        self.removed_handles.append(handle)


async def test_run_until_shutdown_cancels_clipboard_mic_sleep_and_thinking_hotkey_listeners():
    """Same shape as test_run_until_shutdown_cancels_tasks_and_unsubscribes,
    but with the real listener coroutines (task-10's clipboard/mic-sleep,
    task-13's thinking-mode) instead of arbitrary fake tasks - confirms
    run()'s pattern of handing these to run_until_shutdown actually cancels
    them and runs their cleanup (kb.remove_hotkey)."""
    app = _fake_app()
    subscriptions = wire(app)
    shutdown_event = asyncio.Event()

    fake_kb_clipboard = _FakeKeyboardModuleForShutdownTest()
    fake_kb_mic_sleep = _FakeKeyboardModuleForShutdownTest()
    fake_kb_thinking = _FakeKeyboardModuleForShutdownTest()
    mic_sleep_audio_input = AudioInput(bus=app.bus, chunker=None)

    background_tasks = [
        asyncio.create_task(
            run_clipboard_hotkey_listener(
                app.bus,
                app.settings.hotkeys,
                app.settings.clipboard,
                keyboard_module=fake_kb_clipboard,
            )
        ),
        asyncio.create_task(
            run_mic_sleep_hotkey_listener(
                mic_sleep_audio_input, app.settings.hotkeys, keyboard_module=fake_kb_mic_sleep
            )
        ),
        asyncio.create_task(
            run_thinking_hotkey_listener(
                app.thinking_mode, app.settings.hotkeys, keyboard_module=fake_kb_thinking
            )
        ),
    ]
    await asyncio.sleep(0)  # let all listeners register their hotkeys

    shutdown_event.set()
    await asyncio.wait_for(
        run_until_shutdown(app, subscriptions, shutdown_event, background_tasks),
        timeout=2,
    )

    assert all(task.cancelled() for task in background_tasks)
    assert len(fake_kb_clipboard.removed_handles) == 1
    assert len(fake_kb_mic_sleep.removed_handles) == 1
    assert len(fake_kb_thinking.removed_handles) == 1


# --- mic sleep/wake sound cue (task-10) -------------------------------------


async def test_on_mic_sleep_toggled_plays_mic_sleep_cue_when_asleep():
    sound_cues = _FakeSoundCues()
    app = App(
        bus=EventBus(),
        backend=None,
        audio_input=None,
        tts_output=None,
        capture_input=None,
        orchestrator=None,
        sound_cues=sound_cues,
        thinking_mode=None,
        settings=_settings(),
    )

    await _on_mic_sleep_toggled(app, MicSleepToggled(is_awake=False))

    assert sound_cues.played == ["mic_sleep"]


async def test_on_mic_sleep_toggled_plays_mic_wake_cue_when_awake():
    sound_cues = _FakeSoundCues()
    app = App(
        bus=EventBus(),
        backend=None,
        audio_input=None,
        tts_output=None,
        capture_input=None,
        orchestrator=None,
        sound_cues=sound_cues,
        thinking_mode=None,
        settings=_settings(),
    )

    await _on_mic_sleep_toggled(app, MicSleepToggled(is_awake=True))

    assert sound_cues.played == ["mic_wake"]


async def test_on_mic_sleep_toggled_logs_an_info_message(caplog):
    """Observability follow-up from task-10's human review: INFO-level
    logging was silently dropped everywhere (nothing in the process
    configured a handler for it), making state transitions like this one
    impossible to confirm from the console."""
    app = App(
        bus=EventBus(),
        backend=None,
        audio_input=None,
        tts_output=None,
        capture_input=None,
        orchestrator=None,
        sound_cues=_FakeSoundCues(),
        thinking_mode=None,
        settings=_settings(),
    )

    with caplog.at_level(logging.INFO, logger="main"):
        await _on_mic_sleep_toggled(app, MicSleepToggled(is_awake=False))

    assert any("asleep" in record.message for record in caplog.records)


async def test_on_mic_sleep_toggled_publishes_a_system_event_for_the_ui():
    """task-ui-03: the Status Console's events panel gets this through the
    bus, not by scraping the log line above."""
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
        settings=_settings(),
    )

    await _on_mic_sleep_toggled(app, MicSleepToggled(is_awake=False))

    assert len(received) == 1
    assert received[0].source == "HOTKEY"
    assert received[0].level is EventLevel.INFO
    assert "усыпл" in received[0].message


# --- elevation check -------------------------------------------------------


def test_is_elevated_returns_a_bool():
    assert isinstance(is_elevated(), bool)


# --- ResponseComplete ordering (review finding) -----------------------------


async def test_on_full_response_complete_plays_listening_only_after_trailing_speech():
    """Regression test for a real bug: an earlier version subscribed
    tts_output, orchestrator, and a "replay listening cue" closure
    separately to ResponseComplete. bus.py delivers same-event subscribers
    concurrently (asyncio.gather), so the listening cue could play before
    a trailing sentence (scheduled by on_response_complete, without
    final punctuation) had even started, let alone finished, playing.
    _on_full_response_complete does all of this in one coroutine instead;
    this test simulates a delayed trailing-speech task and asserts the
    listening cue is provably last.
    """
    events: list[str] = []

    class _FakeTts:
        def __init__(self) -> None:
            self._task: asyncio.Task | None = None

        async def on_response_complete(self, event) -> None:
            events.append("trailing_sentence_scheduled")
            self._task = asyncio.create_task(self._delayed_finish())

        async def _delayed_finish(self) -> None:
            await asyncio.sleep(0)  # yield once, like real synthesis would
            events.append("trailing_speech_finished")

        async def wait_for_pending(self) -> None:
            if self._task is not None:
                await self._task

    class _FakeOrchestrator:
        async def on_response_complete(self, event) -> None:
            events.append("history_recorded")

        async def finish_turn(self, cooldown_seconds: float = 0.0) -> None:
            events.append("busy_cleared")

    class _FakeSoundCuesForOrdering:
        async def play(self, cue: str) -> None:
            events.append(f"cue:{cue}")

    app = App(
        bus=EventBus(),
        backend=None,
        audio_input=None,
        tts_output=_FakeTts(),
        capture_input=None,
        orchestrator=_FakeOrchestrator(),
        sound_cues=_FakeSoundCuesForOrdering(),
        thinking_mode=None,
        settings=_settings(),
    )

    await _on_full_response_complete(app, _complete_event())

    assert events == [
        "trailing_sentence_scheduled",
        "history_recorded",
        "trailing_speech_finished",
        "busy_cleared",
        "cue:listening",
    ]


async def test_on_full_response_complete_clears_busy_and_plays_error_when_tts_fails():
    """Regression test for a real bug: without try/finally around the
    finish sequence, an exception from tts_output.on_response_complete()
    or wait_for_pending() (model/cache/audio-device failure) skipped
    orchestrator.finish_turn() entirely. Since bus.py only logs a
    subscriber's exception (it does not retry or restart the handler),
    the orchestrator stayed permanently busy - every later utterance
    ignored as "previous request still in flight" forever, wedging the
    whole process on a single failed turn."""
    orchestrator, backend, sound_cues = _orchestrator()

    class _FailingTts:
        async def on_response_complete(self, event) -> None:
            pass

        async def wait_for_pending(self) -> None:
            raise RuntimeError("audio device failure")

    app = App(
        bus=EventBus(),
        backend=backend,
        audio_input=None,
        tts_output=_FailingTts(),
        capture_input=None,
        orchestrator=orchestrator,
        sound_cues=sound_cues,
        thinking_mode=None,
        # negligible cooldown - keeps this test fast; the real default
        # (2.0 s) is exercised by design, not by this test's timing
        settings=Settings(vad=VadSettings(request_end_pause_seconds=0.001)),
    )

    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1))
    await _on_full_response_complete(app, _complete_event())

    assert sound_cues.played[-1] == "error"

    # busy was cleared despite the failure - a subsequent utterance is not ignored
    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1))
    assert len(backend.calls) == 2


# --- shared playback lock (prevents device-contention crackling) -----------


def test_build_app_shares_one_playback_lock_between_tts_and_sound_cues():
    app = build_app(_settings(), backend=_FakeBackend())

    assert app.tts_output._playback_lock is app.sound_cues._playback_lock


def test_build_app_wires_the_configured_microphone_device_into_the_stream_factory():
    """story-v1.2.4-task-3: restart-to-apply for microphone selection -
    build_app() must bind settings.microphone.device into the real
    AudioInput's stream_factory when audio_input is not injected. Never
    calls the resulting factory (would try to open a real device) -
    functools.partial inspection only, same as audio_in.py's own test."""
    settings = Settings(microphone=MicrophoneSettings(device="USB Headset"))

    app = build_app(settings, backend=_FakeBackend())

    assert app.audio_input._stream_factory.keywords == {"device": "USB Headset"}


async def test_shared_playback_lock_prevents_overlapping_device_access(tmp_path, monkeypatch):
    """Exercises the real TtsOutput._default_play and
    SoundCuePlayer._default_play_file with sounddevice/soundfile mocked
    out, sharing one lock - asserts the underlying device is never
    accessed by both at once, which is what caused the audible
    crackling/tempo artifacts reported live."""
    import sound_cues as sound_cues_module
    import tts as tts_module
    from config import SoundCueSettings, TtsSettings
    from tts import TtsOutput

    currently_playing = False

    def fake_play(_data, _sample_rate) -> None:
        nonlocal currently_playing
        assert not currently_playing, "overlapping device access detected"
        currently_playing = True

    def fake_wait() -> None:
        nonlocal currently_playing
        import time

        time.sleep(0.02)
        currently_playing = False

    monkeypatch.setattr(tts_module.sd, "play", fake_play)
    monkeypatch.setattr(tts_module.sd, "wait", fake_wait)
    monkeypatch.setattr(tts_module.sf, "read", lambda *a, **k: (b"samples", 48000))
    monkeypatch.setattr(sound_cues_module.sf, "read", lambda *a, **k: (b"samples", 22050))

    cue_path = tmp_path / "thinking.wav"
    cue_path.write_bytes(b"dummy")

    lock = asyncio.Lock()
    tts_output = TtsOutput(TtsSettings(), playback_lock=lock)
    sound_cues = SoundCuePlayer(
        SoundCueSettings(thinking=str(cue_path)), playback_lock=lock
    )

    await asyncio.gather(
        tts_output._default_play(b"wav-bytes-placeholder"),
        sound_cues._default_play_file(str(cue_path)),
    )


# --- thinking-token isolation through the real bus (task-13) ---------------


def _client_with_ndjson_body(lines: list[dict]) -> httpx.AsyncClient:
    body = "\n".join(json.dumps(line) for line in lines).encode() + b"\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://localhost:11434"
    )


class _RecordingTtsOutput:
    """Records exactly what reaches on_token - the real regression check
    for the story's hard rule (message.thinking must never reach TTS),
    exercised through the real bus/wire() wiring rather than backend.py's
    own unit tests, which only check backend.py in isolation."""

    def __init__(self) -> None:
        self.received_texts: list[str] = []

    async def on_token(self, event: ResponseToken) -> None:
        self.received_texts.append(event.text)

    async def on_response_complete(self, event: ResponseComplete) -> None:
        pass

    async def wait_for_pending(self) -> None:
        return None


async def test_thinking_chunks_never_reach_tts_through_real_bus_wiring():
    lines = [
        {"message": {"thinking": "reasoning step one", "content": ""}, "done": False},
        {"message": {"thinking": "reasoning step two", "content": ""}, "done": False},
        {"message": {"content": "Hello"}, "done": False},
        {"message": {"content": ""}, "done": True, "eval_count": 1},
    ]
    bus = EventBus()
    backend = OllamaBackend(bus=bus, settings=BackendSettings(), client=_client_with_ndjson_body(lines))
    tts_output = _RecordingTtsOutput()

    app = build_app(
        _settings(),
        bus=bus,
        backend=backend,
        audio_input=_FakeAudioInput(),
        tts_output=tts_output,
        capture_input=_FakeCaptureInput(),
    )
    wire(app)

    await backend.chat(messages=[{"role": "user", "content": "hi"}], thinking_enabled=True)

    assert tts_output.received_texts == ["Hello"]
