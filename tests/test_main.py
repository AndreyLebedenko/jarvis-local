import asyncio
import base64
import json
import logging
import sys
import types
from collections.abc import Callable

import httpx
import pytest

import jarvis.app as main_module
from jarvis.app import (
    APP_LOGGER_NAME,
    SYSTEM_PROMPT,
    VOICE_PLACEHOLDER_TEXT,
    App,
    ConversationHistory,
    Orchestrator,
    _microphone_health,
    _on_full_response_complete,
    _on_mic_sleep_toggled,
    _on_reasoning_level_changed,
    build_app,
    create_live_status_console,
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
from jarvis.audio.input import AudioInput, MicSleepToggled, UtteranceChunk
from jarvis.audio.sound_cues import SoundCuePlayer
from jarvis.audio.tts import BilingualTtsEngine
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    BackendSettings,
    McpServerSettings,
    McpSettings,
    MicrophoneSettings,
    PiperTtsSettings,
    PromptSettings,
    Settings,
    SileroTtsSettings,
    TtsSettings,
    VadSettings,
)
from jarvis.core.lifecycle import ModelRequestInput, ModelRequestStarted
from jarvis.dialog.backend import (
    LatencyMetrics,
    OllamaBackend,
    ResponseComplete,
    ResponseToken,
)
from jarvis.dialog.thinking_mode import (
    ReasoningLevel,
    ReasoningLevelChanged,
    ReasoningLevelState,
)
from jarvis.dialog.time_context import format_time_context
from jarvis.dialog.tool_presentation import PromptToolPresentation, ToolAwareDialog
from jarvis.inputs.capture import ScreenshotCaptured
from jarvis.inputs.clipboard import ClipboardSubmitted
from jarvis.tools.host import McpModuleStatus
from jarvis.ui.contract import (
    DataLocality,
    EventLevel,
    HealthStatus,
    ModuleHealth,
    ModuleId,
    RuntimeState,
    SystemEvent,
    VisibilityMode,
)
from jarvis.ui.transport import UiTransportInfo


class _FakeBackend:
    def __init__(self, chat_impl=None) -> None:
        self.calls: list[tuple[list[dict], list[str] | None]] = []
        self.reasoning_level_calls: list[ReasoningLevel] = []
        self._chat_impl = chat_impl

    async def chat(
        self, messages, images_b64=None, reasoning_level=ReasoningLevel.OFF
    ) -> None:
        self.calls.append((messages, images_b64))
        self.reasoning_level_calls.append(reasoning_level)
        if self._chat_impl is not None:
            await self._chat_impl()


class _FakeSoundCues:
    def __init__(self) -> None:
        self.played: list[str] = []

    async def play(self, cue: str) -> None:
        self.played.append(cue)


def _complete_event() -> ResponseComplete:
    return ResponseComplete(
        metrics=LatencyMetrics(
            load_seconds=0, prompt_eval_seconds=0, eval_seconds=0, eval_count=0
        )
    )


# --- system prompt -----------------------------------------------------


def test_system_prompt_includes_russian_and_short_answer_directives():
    assert "по-русски" in SYSTEM_PROMPT
    assert "коротко" in SYSTEM_PROMPT


def test_system_prompt_does_not_ask_for_language_markup():
    assert "<speak>" not in SYSTEM_PROMPT
    assert "<lang" not in SYSTEM_PROMPT
    assert "API names" in SYSTEM_PROMPT
    assert "identifiers" in SYSTEM_PROMPT
    assert "Markdown" in SYSTEM_PROMPT
    assert "языковую разметку добавлять не нужно" in SYSTEM_PROMPT


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
    chat_impl=None, audio_input=None, thinking_mode=None, bus=None, clock=None
) -> tuple[Orchestrator, _FakeBackend, _FakeSoundCues]:
    backend = _FakeBackend(chat_impl)
    sound_cues = _FakeSoundCues()
    orchestrator = Orchestrator(
        backend,
        ConversationHistory(),
        sound_cues,
        audio_input=audio_input,
        thinking_mode=thinking_mode,
        bus=bus,
        clock=clock,
    )
    return orchestrator, backend, sound_cues


class _RequestRecorder:
    def __init__(self, bus: EventBus) -> None:
        self.events: list[ModelRequestStarted] = []
        bus.subscribe(ModelRequestStarted, self._on_event)

    async def _on_event(self, event: ModelRequestStarted) -> None:
        self.events.append(event)


async def test_accepted_voice_request_reports_its_exact_media_composition():
    bus = EventBus()
    recorder = _RequestRecorder(bus)
    orchestrator, _backend, _sound_cues = _orchestrator(
        bus=bus, clock=lambda: 1700000123.0
    )
    await orchestrator.on_screenshot(
        ScreenshotCaptured(png_bytes=b"screen", mode="full", width=1, height=1)
    )

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"audio", start_seconds=2.5, end_seconds=6.75)
    )

    assert recorder.events == [
        ModelRequestStarted(
            timestamp=1700000123.0,
            inputs=(ModelRequestInput.AUDIO, ModelRequestInput.SCREENSHOT),
            audio_duration_seconds=4.25,
        )
    ]


async def test_accepted_voice_request_without_screenshot_reports_audio_only():
    bus = EventBus()
    recorder = _RequestRecorder(bus)
    orchestrator, _backend, _sound_cues = _orchestrator(
        bus=bus, clock=lambda: 1700000125.0
    )

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"audio", start_seconds=2.0, end_seconds=3.5)
    )

    assert recorder.events == [
        ModelRequestStarted(
            timestamp=1700000125.0,
            inputs=(ModelRequestInput.AUDIO,),
            audio_duration_seconds=1.5,
        )
    ]


async def test_request_composition_event_is_published_before_backend_chat():
    bus = EventBus()
    orchestrator, backend, _sound_cues = _orchestrator(bus=bus)
    backend_call_counts: list[int] = []

    async def on_request_started(event: ModelRequestStarted) -> None:
        del event
        backend_call_counts.append(len(backend.calls))

    bus.subscribe(ModelRequestStarted, on_request_started)

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"audio", start_seconds=0, end_seconds=1)
    )

    assert backend_call_counts == [0]
    assert len(backend.calls) == 1


async def test_accepted_clipboard_request_reports_no_content_or_audio_duration():
    bus = EventBus()
    recorder = _RequestRecorder(bus)
    orchestrator, _backend, _sound_cues = _orchestrator(
        bus=bus, clock=lambda: 1700000124.0
    )

    await orchestrator.on_clipboard(
        ClipboardSubmitted(text="private text", truncated=False, is_empty=False)
    )

    assert recorder.events == [
        ModelRequestStarted(
            timestamp=1700000124.0,
            inputs=(ModelRequestInput.CLIPBOARD,),
            audio_duration_seconds=None,
        )
    ]


async def test_empty_and_busy_rejected_input_does_not_report_a_model_request():
    bus = EventBus()
    recorder = _RequestRecorder(bus)
    pending = asyncio.Event()

    async def slow_chat() -> None:
        await pending.wait()

    orchestrator, _backend, _sound_cues = _orchestrator(bus=bus, chat_impl=slow_chat)
    accepted = asyncio.create_task(
        orchestrator.on_utterance(
            UtteranceChunk(wav_bytes=b"audio", start_seconds=0, end_seconds=1)
        )
    )
    await asyncio.sleep(0)
    await orchestrator.on_clipboard(
        ClipboardSubmitted(text="ignored", truncated=False, is_empty=False)
    )
    await orchestrator.on_clipboard(
        ClipboardSubmitted(text="", truncated=False, is_empty=True)
    )
    pending.set()
    await accepted

    assert len(recorder.events) == 1


async def test_on_utterance_sends_media_and_plays_thinking_cue():
    orchestrator, backend, sound_cues = _orchestrator()

    await orchestrator.on_screenshot(
        ScreenshotCaptured(png_bytes=b"png", mode="full", width=1, height=1)
    )
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"wav", start_seconds=0, end_seconds=1)
    )

    assert sound_cues.played == ["thinking"]
    [(messages, media)] = backend.calls
    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert messages[-1] == {"role": "user", "content": "[голосовое сообщение]"}
    # audio first, then the pending screenshot
    assert media == [
        base64.b64encode(b"wav").decode(),
        base64.b64encode(b"png").decode(),
    ]


async def test_on_utterance_without_screenshot_sends_only_audio():
    orchestrator, backend, sound_cues = _orchestrator()

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"wav", start_seconds=0, end_seconds=1)
    )

    [(_messages, media)] = backend.calls
    assert len(media) == 1


async def test_screenshot_is_consumed_once_not_resent_on_next_utterance():
    orchestrator, backend, _ = _orchestrator()

    await orchestrator.on_screenshot(
        ScreenshotCaptured(png_bytes=b"png", mode="full", width=1, height=1)
    )
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"wav1", start_seconds=0, end_seconds=1)
    )
    await orchestrator.on_response_complete(_complete_event())
    await (
        orchestrator.finish_turn()
    )  # normally called after wait_for_pending() - see wire()
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"wav2", start_seconds=0, end_seconds=1)
    )

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

    await orchestrator.on_clipboard(
        ClipboardSubmitted(text="", truncated=False, is_empty=True)
    )

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
        orchestrator.on_utterance(
            UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
        )
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


async def test_on_response_complete_records_plain_response_text_in_history():
    orchestrator, _backend, _sound_cues = _orchestrator()

    await orchestrator.on_response_token(ResponseToken(text="Ответ через API готов."))
    await orchestrator.on_response_complete(_complete_event())

    messages = orchestrator._history.as_messages()
    assert messages[-1] == {"role": "assistant", "content": "Ответ через API готов."}


async def test_busy_utterance_is_ignored_until_previous_turn_completes():
    still_busy = asyncio.Event()

    async def slow_chat() -> None:
        await still_busy.wait()

    orchestrator, backend, _sound_cues = _orchestrator(chat_impl=slow_chat)

    first = asyncio.create_task(
        orchestrator.on_utterance(
            UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
        )
    )
    await asyncio.sleep(0)  # let the first call start and set _busy
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1)
    )

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
        orchestrator.on_utterance(
            UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
        )
    )
    await asyncio.sleep(0)  # let the first call start and set _busy

    await orchestrator.on_screenshot(
        ScreenshotCaptured(png_bytes=b"png", mode="full", width=1, height=1)
    )
    # ignored while busy - the screenshot above must survive this
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1)
    )

    still_busy.set()
    await first
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"c", start_seconds=0, end_seconds=1)
    )

    assert len(backend.calls) == 2  # "b" was ignored; "a" and "c" went through
    assert (
        len(backend.calls[-1][1]) == 2
    )  # "c" still got the screenshot from before "b"


async def test_finish_turn_cooldown_rejects_a_self_heard_echo():
    """Regression test for a real bug: after Jarvis stops speaking,
    audio_in.py can still be sitting on a self-heard "utterance" (its own
    voice picked up by the mic - no echo cancellation in v1.0) for up to
    request_end_pause_seconds before it publishes it. If busy had already
    cleared by then, that echo was accepted and answered as if it were a
    genuine new question - Jarvis talking to itself. finish_turn()'s
    cooldown keeps busy True for that whole window."""
    orchestrator, backend, _sound_cues = _orchestrator()
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    await orchestrator.on_response_complete(_complete_event())

    finish_task = asyncio.create_task(orchestrator.finish_turn(cooldown_seconds=0.05))
    await asyncio.sleep(0)  # let finish_turn() start its cooldown sleep

    # still within the cooldown: a self-heard echo must be rejected, same as mid-turn
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"echo", start_seconds=0, end_seconds=1)
    )
    assert len(backend.calls) == 1

    await finish_task  # cooldown elapses, busy clears

    # a genuine new utterance after the cooldown is accepted
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1)
    )
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
        self.is_awake = True

    async def auto_pause_for_speech(self) -> None:
        self.auto_pause_calls += 1

    async def auto_resume_after_speech(self) -> None:
        self.auto_resume_calls += 1


async def test_speaking_auto_pauses_mic_and_resumes_after_cooldown():
    audio_input = _FakeAudioInputForEcho()
    orchestrator, _backend, _sound_cues = _orchestrator(audio_input=audio_input)

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
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

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    await orchestrator.finish_turn()  # no response token in this turn

    assert audio_input.auto_pause_calls == 0
    assert (
        audio_input.auto_resume_calls == 1
    )  # finish_turn() always resumes - harmless no-op


async def test_error_during_chat_plays_error_cue_and_clears_busy():
    async def failing_chat() -> None:
        raise ValueError("boom")

    orchestrator, backend, sound_cues = _orchestrator(chat_impl=failing_chat)

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert sound_cues.played == ["thinking", "error"]

    # busy was cleared, so a subsequent utterance is not ignored
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1)
    )
    assert len(backend.calls) == 2


# --- current-turn time context (v1.3.2) -------------------------------------
#
# format_time_context() is injected as an extra system message immediately
# before the user turn - closest to the query, not buried ahead of a
# potentially long history block - and must never reach
# ConversationHistory.add() (mirrors the current-turn-only media_b64
# pattern applied to time instead of images; see PROJECT.md's v1.3.2 note).


async def test_start_turn_appends_time_context_system_message_before_user_turn():
    orchestrator, backend, _sound_cues = _orchestrator(clock=lambda: 1700000123.0)

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    [(messages, _images)] = backend.calls
    assert messages[-2] == {
        "role": "system",
        "content": format_time_context(1700000123.0),
    }
    assert messages[-1] == {"role": "user", "content": VOICE_PLACEHOLDER_TEXT}


async def test_time_context_message_is_not_recorded_in_history():
    orchestrator, _backend, _sound_cues = _orchestrator(clock=lambda: 1700000123.0)

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    await orchestrator.on_response_token(ResponseToken(text="Привет"))
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()

    time_context_text = format_time_context(1700000123.0)
    recorded_texts = [m["content"] for m in orchestrator._history.as_messages()]
    assert time_context_text not in recorded_texts
    assert all(m.get("role") != "system" for m in orchestrator._history.as_messages())


# --- graded reasoning level (story-v1.3.1 task 2) ---------------------------
#
# Orchestrator samples ReasoningLevelState.level at turn start (in
# _start_turn(), synchronously with no `await` before the value reaches
# backend.chat()) and passes it through, per the story's decision that a
# hotkey/UI change applies to the next accepted turn, not any request
# already in flight.


async def test_start_turn_passes_off_by_default():
    thinking_mode = ReasoningLevelState(bus=EventBus())
    orchestrator, backend, _sound_cues = _orchestrator(thinking_mode=thinking_mode)

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert backend.reasoning_level_calls == [ReasoningLevel.OFF]


async def test_start_turn_passes_the_sampled_level_after_a_cycle():
    thinking_mode = ReasoningLevelState(bus=EventBus())
    orchestrator, backend, _sound_cues = _orchestrator(thinking_mode=thinking_mode)

    await thinking_mode.cycle_level(source="HOTKEY")  # off -> low
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert backend.reasoning_level_calls == [ReasoningLevel.LOW]


async def test_level_change_while_busy_does_not_affect_the_in_flight_turn():
    """Regression guard for the story's explicit boundary: changing a live
    Ollama stream mid-response is out of scope. A level change that lands
    while a turn's backend.chat() call is already in flight must not
    retroactively change what was already passed for that call - only the
    next accepted turn should see the new value."""
    still_busy = asyncio.Event()

    async def slow_chat() -> None:
        await still_busy.wait()

    thinking_mode = ReasoningLevelState(bus=EventBus())
    orchestrator, backend, _sound_cues = _orchestrator(
        chat_impl=slow_chat, thinking_mode=thinking_mode
    )

    first = asyncio.create_task(
        orchestrator.on_utterance(
            UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
        )
    )
    await asyncio.sleep(0)  # let the first call start and sample level=off

    await thinking_mode.cycle_level(
        source="HOTKEY"
    )  # off -> low, while the first call is in flight

    still_busy.set()
    await first

    assert backend.reasoning_level_calls == [
        ReasoningLevel.OFF
    ]  # the in-flight call was unaffected

    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1)
    )

    assert backend.reasoning_level_calls == [
        ReasoningLevel.OFF,
        ReasoningLevel.LOW,
    ]  # next accepted turn sees the new value


async def test_start_turn_with_no_thinking_mode_defaults_to_off():
    """Orchestrator can be constructed without a thinking_mode (e.g. older
    tests/callers) - must not crash, and must behave as if reasoning is
    permanently off."""
    orchestrator, backend, _sound_cues = _orchestrator()

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert backend.reasoning_level_calls == [ReasoningLevel.OFF]


# --- graded reasoning-level cue/log wiring (story-v1.3.1 task 3) ------------


def _app_with_sound_cues(sound_cues) -> App:
    return App(
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
        settings=_settings(),
    )

    await _on_reasoning_level_changed(
        app, ReasoningLevelChanged(level=ReasoningLevel.MEDIUM, source=source)
    )

    assert len(received) == 1
    assert received[0].source == source
    assert received[0].level is EventLevel.INFO
    assert "medium" in received[0].message.lower()


# --- warm-up SystemEvent (task-ui-03) ---------------------------------------


async def test_warm_up_publishes_info_system_event_on_success():
    bus = EventBus()
    received: list[SystemEvent] = []
    bus.subscribe(SystemEvent, _collecting_subscriber(received))

    await warm_up(_FakeBackend(), bus)

    assert len(received) == 1
    assert received[0].source == "WARMUP"
    assert received[0].level is EventLevel.INFO


async def test_warm_up_publishes_warn_system_event_and_still_logs_exception_on_failure(
    caplog,
):
    bus = EventBus()
    received: list[SystemEvent] = []
    bus.subscribe(SystemEvent, _collecting_subscriber(received))

    async def failing_chat() -> None:
        raise RuntimeError("Ollama unreachable")

    backend = _FakeBackend(chat_impl=failing_chat)

    with caplog.at_level(logging.ERROR, logger=APP_LOGGER_NAME):
        await warm_up(backend, bus)

    assert any(
        record.levelno == logging.ERROR for record in caplog.records
    )  # logger.exception
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
        self.close_calls = 0

    def create(
        self,
        on_closed: object | None = None,
        url: str | None = None,
    ) -> object:
        self.created_with_on_closed = on_closed
        self.created_with_url = url
        return object()

    def close(self) -> None:
        self.close_calls += 1

    def load_url(self, url: str) -> None:
        self.loaded_url = url


class _FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def set_model_label(self, label: str) -> None:
        self.calls.append(("model", label))

    def set_data_locality(self, locality: DataLocality) -> None:
        self.calls.append(("locality", locality))

    def set_thinking_mode(self, level: ReasoningLevel) -> None:
        self.calls.append(("thinking", level))

    def set_visibility_mode(self, mode: VisibilityMode) -> None:
        self.calls.append(("visibility", mode))

    def set_module_health(self, health: ModuleHealth) -> None:
        self.calls.append(("module", health))

    def set_runtime_state(
        self, state: RuntimeState, substatus: str | None = None
    ) -> None:
        self.calls.append(("runtime", (state, substatus)))


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
    assert event_types.count(ReasoningLevelChanged) == 1

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

    assert live_console.transport is None
    assert live_console.console is console
    assert live_console.touchstrip is touchstrip


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


async def test_wire_status_console_seeds_the_transport_snapshot():
    app = _fake_app()
    live_console = create_live_status_console(app, include_touchstrip=False)
    transport = _FakeTransport()
    live_console.transport = transport

    subscriptions = wire_status_console(app, live_console, asyncio.get_running_loop())

    # Runtime state is no longer seeded here: the initial snapshot value is
    # set where the UiStateStore is constructed, and every transition comes
    # from RuntimeStateTracker (subscribed by this call, hence non-empty
    # subscriptions).
    assert len(subscriptions) > 0
    assert transport.calls == [
        ("model", app.settings.backend.model),
        ("locality", DataLocality.LOCAL),
        ("thinking", ReasoningLevel.OFF),
        ("visibility", VisibilityMode.OPEN),
        (
            "module",
            ModuleHealth(
                module=ModuleId.MICROPHONE, status=HealthStatus.OK, detail="listening"
            ),
        ),
    ]

    unwire(app, subscriptions)


def test_microphone_health_reports_user_muted_as_not_in_use():
    assert _microphone_health(False, "en") == ModuleHealth(
        module=ModuleId.MICROPHONE,
        status=HealthStatus.UNAVAILABLE,
        detail="not in use",
    )


def test_microphone_health_keeps_the_v1_2_10_russian_muted_wording():
    assert _microphone_health(False, "ru").detail == "не используется"


async def test_wire_status_console_leaves_bus_projection_to_the_transport_server():
    app = _fake_app()
    live_console = create_live_status_console(app, include_touchstrip=False)
    transport = _FakeTransport()
    live_console.transport = transport
    subscriptions = wire_status_console(app, live_console, asyncio.get_running_loop())

    await app.bus.publish(MicSleepToggled, MicSleepToggled(is_awake=False))
    await app.bus.publish(MicSleepToggled, MicSleepToggled(is_awake=True))

    # Only the five snapshot seeds: mic-toggle projection belongs to the
    # real transport server's own bus subscription, not to this wiring.
    assert len(transport.calls) == 5
    assert transport.calls[-1][0] == "module"

    unwire(app, subscriptions)


async def test_accepted_voice_turn_renders_thinking_through_the_tracker():
    app = _fake_app()
    live_console = create_live_status_console(app, include_touchstrip=False)
    transport = _FakeTransport()
    live_console.transport = transport
    wire_status_console(app, live_console, asyncio.get_running_loop())
    wire(app)

    await app.bus.publish(
        UtteranceChunk, UtteranceChunk(wav_bytes=b"x", start_seconds=0, end_seconds=1)
    )

    runtime_calls = [call for call in transport.calls if call[0] == "runtime"]
    assert ("runtime", (RuntimeState.THINKING, "Processing voice...")) in runtime_calls


async def test_rejected_busy_turn_does_not_render_thinking():
    """The busy guard lives in the Orchestrator alone: a turn rejected
    there publishes no TurnAccepted, so the tracker never announces
    THINKING - previously this required duplicating the busy check in the
    wire() closures."""
    app = _fake_app()
    live_console = create_live_status_console(app, include_touchstrip=False)
    transport = _FakeTransport()
    live_console.transport = transport
    wire_status_console(app, live_console, asyncio.get_running_loop())
    wire(app)
    app.orchestrator._busy = True

    await app.bus.publish(
        UtteranceChunk, UtteranceChunk(wav_bytes=b"x", start_seconds=0, end_seconds=1)
    )

    assert [call for call in transport.calls if call[0] == "runtime"] == []


async def test_wire_pushes_listening_state_after_response_complete():
    """Regression for a real live-session bug (2026-07-07): RuntimeState
    stayed stuck on SPEAKING ("Отвечаю") forever after the very first
    turn - nothing ever pushed the orb back to LISTENING once
    ResponseComplete fired, even though the engine kept handling later
    turns correctly in the background. Since v1.2.14 the guarantee is
    owned by one chain: _on_full_response_complete publishes
    TurnCompleted after the turn fully finishes, RuntimeStateTracker
    turns it into RuntimeStateChanged(LISTENING), and
    wire_status_console()'s render handler pushes it to the transport."""
    settings = Settings(
        vad=VadSettings(request_end_pause_seconds=0.001, resume_cooldown_seconds=0.001)
    )
    app = build_app(
        settings,
        backend=_FakeBackend(),
        audio_input=_FakeAudioInputForEcho(),
        tts_output=_FakeTtsOutput(),
        capture_input=_FakeCaptureInput(),
    )
    live_console = create_live_status_console(app, include_touchstrip=False)
    transport = _FakeTransport()
    live_console.transport = transport
    wire_status_console(app, live_console, asyncio.get_running_loop())
    wire(app)

    await app.bus.publish(
        ResponseComplete, ResponseComplete(metrics=LatencyMetrics(0.0, 0.0, 0.0, 1))
    )

    assert transport.calls[-1] == (
        "runtime",
        (RuntimeState.LISTENING, "Waiting for a request"),
    )


def test_parse_args_enables_status_console_without_touchstrip():
    args = parse_args(["--status-console", "--no-touchstrip"])

    assert args.status_console is True
    assert args.no_touchstrip is True


def test_status_console_creates_windows_before_starting_pywebview(monkeypatch):
    fake_app = types.SimpleNamespace(
        bus=EventBus(),
        thinking_mode=types.SimpleNamespace(level=ReasoningLevel.OFF),
        visibility_mode=types.SimpleNamespace(mode=VisibilityMode.OPEN),
    )
    fake_live_console = types.SimpleNamespace(
        api=object(),
        transport=None,
        windows_created=False,
    )

    def create_windows() -> None:
        fake_live_console.windows_created = True

    fake_live_console.create_windows = create_windows
    monkeypatch.setattr(main_module, "build_app", lambda settings: fake_app)
    monkeypatch.setattr(
        main_module,
        "create_live_status_console",
        lambda app, include_touchstrip: fake_live_console,
    )
    monkeypatch.setattr(
        main_module, "UiTransportServer", lambda *args, **kwargs: object()
    )

    def start(callback) -> None:
        del callback
        assert fake_live_console.windows_created is True

    monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace(start=start))

    main_module.run_with_status_console(settings=Settings(), include_touchstrip=False)


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


async def test_run_until_shutdown_disables_mcp_host_when_present():
    """run()'s startup calls app.mcp_host.enable() when MCP is configured
    on; this is the matching teardown half - a live MCP connection must
    not outlive clean shutdown."""
    app = _fake_app()
    disable_calls = []

    class _FakeMcpHost:
        async def disable(self) -> None:
            disable_calls.append(1)

    app.mcp_host = _FakeMcpHost()
    subscriptions = wire(app)
    shutdown_event = asyncio.Event()

    shutdown_event.set()
    await asyncio.wait_for(
        run_until_shutdown(app, subscriptions, shutdown_event, []), timeout=2
    )

    assert disable_calls == [1]


async def test_run_until_shutdown_disables_mcp_before_unwiring_subscriptions():
    """Review finding 4: disable() publishes a SystemEvent the Status
    Console's own subscription relays to the UI - unwiring that
    subscription first would mean the UI silently never learns MCP went
    offline. A subscription that is still active when disable() runs must
    actually receive the event."""
    app = _fake_app()
    received: list = []

    async def on_system_event(event) -> None:
        received.append(event)

    class _FakeMcpHost:
        async def disable(self) -> None:
            await app.bus.publish(
                SystemEvent, SystemEvent(0.0, "MCP", EventLevel.INFO, "off")
            )

    app.mcp_host = _FakeMcpHost()
    subscriptions = [*wire(app), (SystemEvent, on_system_event)]
    app.bus.subscribe(SystemEvent, on_system_event)
    shutdown_event = asyncio.Event()

    shutdown_event.set()
    await asyncio.wait_for(
        run_until_shutdown(app, subscriptions, shutdown_event, []), timeout=2
    )

    assert len(received) == 1


class _FakeKeyboardModuleForShutdownTest:
    def __init__(self) -> None:
        self.removed_handles: list[object] = []

    def register(self, binding, callback) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        self.removed_handles.append(object())


async def test_run_until_shutdown_cancels_real_hotkey_listeners():
    """Same shape as test_run_until_shutdown_cancels_tasks_and_unsubscribes,
    but with the real listener coroutines (task-10's clipboard/mic-sleep,
    task-13's thinking-mode) instead of arbitrary fake tasks - confirms
    run()'s pattern of handing these to run_until_shutdown actually cancels
    them and stops each provider during cleanup."""
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
                provider=fake_kb_clipboard,
            )
        ),
        asyncio.create_task(
            run_mic_sleep_hotkey_listener(
                mic_sleep_audio_input, app.settings.hotkeys, provider=fake_kb_mic_sleep
            )
        ),
        asyncio.create_task(
            run_thinking_hotkey_listener(
                app.thinking_mode, app.settings.hotkeys, provider=fake_kb_thinking
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

    with caplog.at_level(logging.INFO, logger=APP_LOGGER_NAME):
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
    assert "sleep" in received[0].message


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
        # (1.0 s) is exercised by design, not by this test's timing
        settings=Settings(vad=VadSettings(resume_cooldown_seconds=0.001)),
    )

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    await _on_full_response_complete(app, _complete_event())

    assert sound_cues.played[-1] == "error"

    # busy was cleared despite the failure - a subsequent utterance is not ignored
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1)
    )
    assert len(backend.calls) == 2


# --- shared playback lock (prevents device-contention crackling) -----------


def test_build_app_shares_one_playback_lock_between_tts_and_sound_cues():
    app = build_app(_settings(), backend=_FakeBackend())

    assert app.tts_output._playback_lock is app.sound_cues._playback_lock


def test_build_app_wires_the_configured_system_prompt_into_the_orchestrator():
    """task-v1.2.12: build_app() must bind settings.prompts.system, not the
    built-in default, so a config-file prompt actually reaches every turn."""
    settings = Settings(prompts=PromptSettings(system="You are Jarvis.", warmup="Hi"))

    app = build_app(settings, backend=_FakeBackend())

    assert app.orchestrator._system_prompt == "You are Jarvis."


async def test_warm_up_sends_the_configured_warmup_prompt():
    backend = _FakeBackend()

    await warm_up(backend, EventBus(), "en", "Hello")

    assert backend.calls[-1][0] == [{"role": "user", "content": "Hello"}]


def test_build_app_wires_the_configured_microphone_device_into_the_stream_factory():
    """story-v1.2.4-task-3: restart-to-apply for microphone selection -
    build_app() must bind settings.microphone.device into the real
    AudioInput's stream_factory when audio_input is not injected. Never
    calls the resulting factory (would try to open a real device) -
    functools.partial inspection only, same as audio_in.py's own test."""
    settings = Settings(microphone=MicrophoneSettings(device="USB Headset"))

    app = build_app(settings, backend=_FakeBackend())

    assert app.audio_input._stream_factory.keywords == {"device": "USB Headset"}


def test_build_app_always_constructs_an_inert_mcp_host_when_mcp_is_disabled():
    """story-v1.4.0 task 3's own acceptance criterion: "off equals the
    capability does not exist" must be a structural fact, not just
    McpHost's own runtime behavior. Per the code-review revision, McpHost
    is now always constructed (so a later live toggle has something to
    call enable() on) - the structural guarantee lives in McpHost itself
    being side-effect-free until enable() runs, asserted here as status
    OFF and an empty registry rather than the object's mere absence."""
    app = build_app(_settings(), backend=_FakeBackend())

    assert app.mcp_host is not None
    assert app.mcp_host.status == McpModuleStatus.OFF
    assert app.mcp_host.enabled is False
    assert app.mcp_host.registry.all() == ()


def test_build_app_constructs_an_mcp_host_when_mcp_is_enabled():
    settings = Settings(
        mcp=McpSettings(
            enabled=True, servers={"search": McpServerSettings(command="search-server")}
        )
    )

    app = build_app(settings, backend=_FakeBackend())

    assert app.mcp_host is not None
    # build_app() itself never connects - run() decides that based on
    # settings.mcp.enabled, after build_app() returns.
    assert app.mcp_host.status == McpModuleStatus.OFF
    assert app.mcp_host.enabled is False  # constructed, not yet connected


def test_build_app_wires_configured_tool_presentation_and_budget():
    settings = Settings(
        mcp=McpSettings(presentation_strategy="prompt", max_tool_calls_per_turn=5)
    )

    app = build_app(settings, backend=_FakeBackend())

    dialog = app.orchestrator._backend
    assert isinstance(dialog, ToolAwareDialog)
    assert isinstance(dialog._presentation, PromptToolPresentation)
    assert dialog._max_tool_calls == 5


def test_build_app_wires_configured_bilingual_tts_engine(tmp_path):
    model_path = tmp_path / "en.onnx"
    config_path = tmp_path / "en.onnx.json"
    model_path.write_bytes(b"model")
    config_path.write_text("{}", encoding="utf-8")
    settings = Settings(
        tts=TtsSettings(
            languages={
                "ru": SileroTtsSettings(),
                "en": PiperTtsSettings(model=str(model_path)),
            }
        )
    )

    app = build_app(
        settings,
        backend=_FakeBackend(),
        audio_input=_FakeAudioInput(),
        capture_input=_FakeCaptureInput(),
    )

    assert isinstance(app.tts_output._engine, BilingualTtsEngine)


def test_build_app_does_not_probe_configured_piper_paths_before_playback(tmp_path):
    settings = Settings(
        tts=TtsSettings(
            languages={
                "ru": SileroTtsSettings(),
                "en": PiperTtsSettings(model=str(tmp_path / "missing.onnx")),
            }
        )
    )

    app = build_app(
        settings,
        backend=_FakeBackend(),
        audio_input=_FakeAudioInput(),
        capture_input=_FakeCaptureInput(),
    )

    assert isinstance(app.tts_output._engine, BilingualTtsEngine)


async def test_shared_playback_lock_prevents_overlapping_device_access(
    tmp_path, monkeypatch
):
    """Exercises the real TtsOutput._default_play and
    SoundCuePlayer._default_play_file with sounddevice/soundfile mocked
    out, sharing one lock - asserts the underlying device is never
    accessed by both at once, which is what caused the audible
    crackling/tempo artifacts reported live."""
    from jarvis.audio import sound_cues as sound_cues_module
    from jarvis.audio import tts as tts_module
    from jarvis.audio.tts import TtsOutput
    from jarvis.core.config import SoundCueSettings, TtsSettings

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
    monkeypatch.setattr(
        sound_cues_module.sf, "read", lambda *a, **k: (b"samples", 22050)
    )

    cue_path = tmp_path / "thinking.wav"
    cue_path.write_bytes(b"dummy")

    lock = asyncio.Lock()

    class UnusedEngine:
        async def synthesize(self, text: str, language: str = "ru") -> bytes:
            raise AssertionError("This playback-lock test must not synthesize")

    tts_output = TtsOutput(TtsSettings(), engine=UnusedEngine(), playback_lock=lock)
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
    backend = OllamaBackend(
        bus=bus, settings=BackendSettings(), client=_client_with_ndjson_body(lines)
    )
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

    await backend.chat(
        messages=[{"role": "user", "content": "hi"}],
        reasoning_level=ReasoningLevel.HIGH,
    )

    assert tts_output.received_texts == ["Hello"]


def test_push_runtime_state_is_not_suppressed_by_a_direct_transport_update():
    from jarvis.app import LiveStatusConsole, _push_runtime_state

    surface = _FakeStatusSurface()
    transport = _FakeTransport()
    live_console = LiveStatusConsole(
        console=surface, touchstrip=None, api=object(), transport=transport
    )

    transport.set_runtime_state(RuntimeState.SPEAKING, "Произношу ответ...")
    _push_runtime_state(live_console, RuntimeState.THINKING, "Обрабатываю голос...")
    _push_runtime_state(live_console, RuntimeState.LISTENING, "Готов слушать")

    assert transport.calls == [
        ("runtime", (RuntimeState.SPEAKING, "Произношу ответ...")),
        ("runtime", (RuntimeState.THINKING, "Обрабатываю голос...")),
        ("runtime", (RuntimeState.LISTENING, "Готов слушать")),
    ]


def test_desktop_console_native_close_is_wired_to_shutdown_request():
    app = _fake_app()
    console = _FakeStatusSurface()
    touchstrip = _FakeStatusSurface()

    live_console = create_live_status_console(
        app, console=console, touchstrip=touchstrip, include_touchstrip=True
    )

    live_console.transport = _FakeTransport()
    transport_info = UiTransportInfo(host="127.0.0.1", port=4321, token="token")
    live_console.create_windows()
    live_console.load_transport_urls(transport_info)

    assert console.created_with_on_closed == live_console.api.request_shutdown
    assert console.loaded_url.endswith("/?token=token")
    assert touchstrip.loaded_url.endswith("/touchstrip.html?token=token")
