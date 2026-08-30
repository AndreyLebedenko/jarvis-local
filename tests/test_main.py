import asyncio
import base64
import io
import json
import logging
import sys
import threading
import time
import types
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import httpx
import numpy as np
import pytest
import soundfile as sf

import jarvis.app as main_module
from jarvis.app import (
    APP_LOGGER_NAME,
    SYSTEM_PROMPT,
    VOICE_PLACEHOLDER_TEXT,
    App,
    ConversationHistory,
    Orchestrator,
    _announce_debug_mode_to_panel,
    _cancel_current_turn,
    _microphone_health,
    _on_full_response_complete,
    _on_interrupt_requested,
    _on_mic_sleep_toggled,
    _on_microphone_capture_failed,
    _on_reasoning_level_changed,
    _on_response_mode_changed,
    announce_debug_mode,
    build_app,
    create_live_status_console,
    main,
    parse_args,
    run,
    run_clipboard_hotkey_listener,
    run_interrupt_hotkey_listener,
    run_mic_sleep_hotkey_listener,
    run_thinking_hotkey_listener,
    run_until_shutdown,
    unwire,
    warm_up,
    wire,
    wire_status_console,
)
from jarvis.audio.debug_metrics import on_utterance_captured
from jarvis.audio.input import (
    AudioInput,
    MicrophoneCaptureFailed,
    MicSleepToggled,
    UtteranceChunk,
)
from jarvis.audio.sound_cues import SoundCuePlayer
from jarvis.audio.tts import BilingualTtsEngine, TtsOutput
from jarvis.audio.tts_mute import TtsSpeechEnabledChanged
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    BackendSettings,
    FilesSettings,
    HistoryAnnotationSettings,
    HistorySettings,
    JournalSettings,
    LoggingSettings,
    McpServerSettings,
    McpSettings,
    MemorySettings,
    MicrophoneSettings,
    PiperTtsSettings,
    PromptSettings,
    ResponseSettings,
    Settings,
    SileroTtsSettings,
    TtsSettings,
    UiSettings,
    VadSettings,
)
from jarvis.core.debug_transcript import configure_debug_transcript, recording
from jarvis.core.lifecycle import (
    AttachmentSubmissionReason,
    ModelRequestInput,
    ModelRequestStarted,
    NewContextReason,
    TextSubmissionReason,
    TurnAccepted,
    TurnSource,
)
from jarvis.core.solo_session import SoloSessionState
from jarvis.dialog.backend import (
    LatencyMetrics,
    OllamaBackend,
    ResponseComplete,
    ResponseToken,
)
from jarvis.dialog.response_mode import (
    ResponseMode,
    ResponseModeChanged,
    ResponseModeState,
)
from jarvis.dialog.thinking_mode import (
    ReasoningLevel,
    ReasoningLevelChanged,
    ReasoningLevelState,
)
from jarvis.dialog.time_context import format_time_context
from jarvis.dialog.tool_presentation import PromptToolPresentation, ToolAwareDialog
from jarvis.files import SessionFileRepository, resolve_session_file_scope
from jarvis.history.context_budget import ContextBudgetLimits
from jarvis.inputs.attachments import (
    AttachmentClass,
    AttachmentPlan,
    AttachmentPlanItem,
    AttachmentUpload,
    PendingAudioMedia,
    PlannedImageMedia,
    PlannedTextPart,
    compose_turn_images,
    compose_turn_text,
)
from jarvis.inputs.capture import ScreenshotCaptured
from jarvis.inputs.clipboard import ClipboardSubmitted
from jarvis.inputs.interrupt import InterruptRequested
from jarvis.journal import (
    HistoryRetrievalCandidate,
    HistoryRetrievalFallbackMode,
    HistoryRetrievalQuery,
    HistoryRetrievalResult,
    HistoryRetrievalSourceMode,
    HistoryRetrievalStatus,
    JournalEvent,
    JournalEventRecord,
    JournalEventRef,
    JournalRecorder,
    JournalStore,
    TurnOutcome,
)
from jarvis.journal.fork import ForkSessionReason
from jarvis.tools.host import (
    McpModuleStatus,
    McpModuleStatusChanged,
    ToolEnablementChanged,
)
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


class _FakeStreamingBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[list[dict], ReasoningLevel]] = []

    async def iter_chat(
        self,
        messages,
        images_b64=None,
        reasoning_level=ReasoningLevel.OFF,
        tools=None,
    ):
        self.calls.append((list(messages), reasoning_level))
        yield {"message": {"content": ""}, "done": True}


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


def _assert_model_request_started(
    event: ModelRequestStarted,
    *,
    timestamp: float,
    inputs: tuple[ModelRequestInput, ...],
    audio_duration_seconds: float | None,
    recent_history_message_count: int = 0,
    retrieval_message_count: int = 0,
) -> None:
    assert event.timestamp == timestamp
    assert event.inputs == inputs
    assert event.audio_duration_seconds == audio_duration_seconds
    assert event.prompt_budget is not None
    assert event.prompt_budget["prompt_capacity_tokens"] == 49152
    assert event.prompt_budget["available_prompt_tokens"] == 39936
    assert event.prompt_budget["tool_result_reserve_tokens"] == 8192
    assert event.prompt_budget["reasoning_generation_reserve_tokens"] == 16384
    assert event.prompt_budget["estimator_safety_margin_tokens"] == 1024
    assert (
        event.prompt_budget["recent_history_message_count"]
        == recent_history_message_count
    )
    assert event.prompt_budget["retrieval_message_count"] == retrieval_message_count
    assert event.prompt_budget["truncated_recent_history"] is False
    assert event.prompt_budget["blank_context_cleared"] is False


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
    chat_impl=None,
    audio_input=None,
    thinking_mode=None,
    response_mode=None,
    reasoning_prompt_settings=None,
    bus=None,
    clock=None,
    journal_recorder=None,
    history_retrieval_service=None,
    text_input_max_chars=main_module.DEFAULT_TEXT_INPUT_MAX_CHARS,
    max_audio_attachment_clips=main_module.MAX_CLIPS_PER_FILE,
    solo_session_state=None,
    session_file_repository=None,
    session_file_scope=None,
    on_turn_start=None,
) -> tuple[Orchestrator, _FakeBackend, _FakeSoundCues]:
    backend = _FakeBackend(chat_impl)
    sound_cues = _FakeSoundCues()
    orchestrator = Orchestrator(
        backend,
        ConversationHistory(),
        sound_cues,
        audio_input=audio_input,
        thinking_mode=thinking_mode,
        response_mode=response_mode,
        reasoning_prompt_settings=reasoning_prompt_settings,
        bus=bus,
        journal_recorder=journal_recorder,
        history_retrieval_service=history_retrieval_service,
        clock=clock,
        text_input_max_chars=text_input_max_chars,
        max_audio_attachment_clips=max_audio_attachment_clips,
        solo_session_state=solo_session_state,
        session_file_repository=session_file_repository,
        session_file_scope=session_file_scope,
        on_turn_start=on_turn_start,
    )
    return orchestrator, backend, sound_cues


def test_history_settings_are_explicitly_converted_to_context_budget_limits():
    limits = main_module._history_limits_from_settings(
        HistorySettings(
            prompt_capacity_tokens=1536,
            recent_history_max_tokens=512,
            automatic_retrieval_max_tokens=256,
            tool_result_reserve_tokens=128,
            reasoning_generation_reserve_tokens=512,
            estimator_safety_margin_tokens=64,
            minimum_recent_exchanges=2,
        )
    )

    assert limits == ContextBudgetLimits(
        prompt_capacity_tokens=1536,
        recent_history_max_tokens=512,
        automatic_retrieval_max_tokens=256,
        tool_result_reserve_tokens=128,
        reasoning_generation_reserve_tokens=512,
        estimator_safety_margin_tokens=64,
        minimum_recent_exchanges=2,
    )


class _RequestRecorder:
    def __init__(self, bus: EventBus) -> None:
        self.events: list[ModelRequestStarted] = []
        bus.subscribe(ModelRequestStarted, self._on_event)

    async def _on_event(self, event: ModelRequestStarted) -> None:
        self.events.append(event)


class _FakeHistoryRetrievalService:
    def __init__(self, result: HistoryRetrievalResult) -> None:
        self.result = result
        self.calls: list[HistoryRetrievalQuery] = []

    def retrieve(self, request: HistoryRetrievalQuery) -> HistoryRetrievalResult:
        self.calls.append(request)
        return self.result


class _FakeJournalRecorder:
    def __init__(self) -> None:
        self.voice_wavs: list[bytes] = []
        self.voice_screenshots: list[bytes | None] = []
        self.user_texts: list[str] = []
        self.user_text_sources: list[str] = []
        self.assistant_texts: list[str] = []
        self.assistant_outcomes: list[TurnOutcome | None] = []
        self.assistant_spoken_derivatives: list[str | None] = []
        self.assistant_spoken_derivative_interrupted: list[bool] = []
        self.forks: list[tuple[str, str]] = []
        # Records every write call in the exact order the real recorder
        # would see it - separate from the per-kind lists above, which lose
        # ordering across user/assistant calls (task-v1.7.0-3 review,
        # second round: an assistant-outcome write racing ahead of the
        # user's own entry it belongs to is a real append-only-journal
        # correctness bug, not just a "missing data" one).
        self.call_order: list[str] = []
        self.session_id = "20260719-100000-fake"

    async def record_voice_user(
        self, wav_bytes: bytes, *, screenshot_png_bytes: bytes | None = None
    ) -> None:
        self.voice_wavs.append(wav_bytes)
        self.voice_screenshots.append(screenshot_png_bytes)
        self.call_order.append("voice_user")

    async def record_text_user(self, text: str, *, source: str = "text") -> None:
        self.user_texts.append(text)
        self.user_text_sources.append(source)
        self.call_order.append(f"text_user:{text}")

    async def record_assistant(
        self,
        text: str,
        *,
        outcome: TurnOutcome | None = None,
        spoken_derivative: str | None = None,
        spoken_derivative_interrupted: bool = False,
    ) -> None:
        self.assistant_texts.append(text)
        self.assistant_outcomes.append(outcome)
        self.assistant_spoken_derivatives.append(spoken_derivative)
        self.assistant_spoken_derivative_interrupted.append(
            spoken_derivative_interrupted
        )
        derivative_suffix = (
            f":{spoken_derivative!r}" if spoken_derivative is not None else ""
        )
        if spoken_derivative_interrupted:
            derivative_suffix += ":interrupted"
        self.call_order.append(f"assistant:{text!r}:{outcome}{derivative_suffix}")

    async def wait_for_pending(self) -> None:
        pass

    async def start_fork_session(
        self, *, source_session_id, provenance_text, seed_drop_report
    ) -> str:
        del seed_drop_report
        self.forks.append((source_session_id, provenance_text))
        return self.session_id


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

    assert len(recorder.events) == 1
    _assert_model_request_started(
        recorder.events[0],
        timestamp=1700000123.0,
        inputs=(ModelRequestInput.AUDIO, ModelRequestInput.SCREENSHOT),
        audio_duration_seconds=4.25,
    )


async def test_starting_a_turn_invokes_on_turn_start_to_yield_the_playback_channel():
    calls: list[bool] = []
    orchestrator, _backend, _sound_cues = _orchestrator(
        on_turn_start=lambda: calls.append(True)
    )

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"audio", start_seconds=0.0, end_seconds=1.0)
    )

    assert calls == [True]


async def test_accepted_voice_request_without_screenshot_reports_audio_only():
    bus = EventBus()
    recorder = _RequestRecorder(bus)
    orchestrator, _backend, _sound_cues = _orchestrator(
        bus=bus, clock=lambda: 1700000125.0
    )

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"audio", start_seconds=2.0, end_seconds=3.5)
    )

    assert len(recorder.events) == 1
    _assert_model_request_started(
        recorder.events[0],
        timestamp=1700000125.0,
        inputs=(ModelRequestInput.AUDIO,),
        audio_duration_seconds=1.5,
    )


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


async def test_the_system_log_records_what_the_turn_sent_to_the_model(caplog):
    """story-v1.6.4 task 4: the events panel's localized entry is not a
    diagnostic artifact - the file a user attaches to a problem report is.
    Before this, the file log had no record of any turn's request at all."""
    bus = EventBus()
    orchestrator, _backend, _sound_cues = _orchestrator(bus=bus)
    await orchestrator.on_screenshot(
        ScreenshotCaptured(png_bytes=b"screen", mode="full", width=1, height=1)
    )

    with caplog.at_level(logging.INFO, logger=APP_LOGGER_NAME):
        await orchestrator.on_utterance(
            UtteranceChunk(wav_bytes=b"audio", start_seconds=2.5, end_seconds=6.75)
        )

    request_lines = [
        record.getMessage()
        for record in caplog.records
        if "Model request" in record.getMessage()
    ]
    assert len(request_lines) == 1
    assert request_lines[0].startswith(
        "[LLM] Model request: inputs=audio,screenshot count=2 audio_duration=4.2s"
    )
    assert "budget=" in request_lines[0]
    assert "history_truncated=false" in request_lines[0]


async def test_the_request_line_is_logged_before_the_backend_is_called(caplog):
    """A request that hangs or crashes the backend is exactly the case the
    file log exists for, so the line cannot wait for the call to return."""
    bus = EventBus()
    orchestrator, backend, _sound_cues = _orchestrator(bus=bus)
    backend.calls.clear()

    with caplog.at_level(logging.INFO, logger=APP_LOGGER_NAME):
        await orchestrator.on_clipboard(
            ClipboardSubmitted(text="anything", truncated=False, is_empty=False)
        )
        logged_before_first_call = next(
            index
            for index, record in enumerate(caplog.records)
            if "Model request" in record.getMessage()
        )

    assert logged_before_first_call >= 0
    assert len(backend.calls) == 1


async def test_the_request_line_never_carries_the_content_that_was_sent(caplog):
    """The story's content rule, pinned at the call site rather than only at
    the formatter: kinds, counts, durations - never payload."""
    bus = EventBus()
    orchestrator, _backend, _sound_cues = _orchestrator(bus=bus)
    secret = "the user's private clipboard text"

    with caplog.at_level(logging.INFO, logger=APP_LOGGER_NAME):
        await orchestrator.on_clipboard(
            ClipboardSubmitted(text=secret, truncated=False, is_empty=False)
        )

    request_lines = [
        record.getMessage()
        for record in caplog.records
        if "Model request" in record.getMessage()
    ]
    assert len(request_lines) == 1
    assert request_lines[0].startswith("[LLM] Model request: inputs=clipboard count=1")
    assert "budget=" in request_lines[0]
    assert secret not in "\n".join(request_lines)


async def test_accepted_clipboard_request_reports_no_content_or_audio_duration():
    bus = EventBus()
    recorder = _RequestRecorder(bus)
    orchestrator, _backend, _sound_cues = _orchestrator(
        bus=bus, clock=lambda: 1700000124.0
    )

    await orchestrator.on_clipboard(
        ClipboardSubmitted(text="private text", truncated=False, is_empty=False)
    )

    assert len(recorder.events) == 1
    _assert_model_request_started(
        recorder.events[0],
        timestamp=1700000124.0,
        inputs=(ModelRequestInput.CLIPBOARD,),
        audio_duration_seconds=None,
    )


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
    assert messages[-1] == {
        "role": "user",
        "content": "[голосовое сообщение]",
        "images": [
            base64.b64encode(b"wav").decode(),
            base64.b64encode(b"png").decode(),
        ],
    }
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
    await asyncio.sleep(0)  # task-v1.7.0-2: chat() now runs one hop later
    await orchestrator.on_clipboard(
        ClipboardSubmitted(text="ignored while busy", truncated=False, is_empty=False)
    )

    assert len(backend.calls) == 1  # the clipboard submission was ignored
    assert "clipboard" not in sound_cues.played
    assert "input_error" not in sound_cues.played

    still_busy.set()
    await first


# --- Orchestrator: Journal typed input turns (story-v1.5.2 task 1) ---------


async def test_submit_text_input_starts_shared_turn_without_pending_screenshot():
    journal_recorder = _FakeJournalRecorder()
    bus = EventBus()
    request_recorder = _RequestRecorder(bus)
    orchestrator, backend, sound_cues = _orchestrator(
        bus=bus, journal_recorder=journal_recorder, clock=lambda: 1700000300.0
    )
    await orchestrator.on_screenshot(
        ScreenshotCaptured(png_bytes=b"pending", mode="full", width=1, height=1)
    )

    result = await orchestrator.submit_text_input("typed from dock")

    assert result.reason is TextSubmissionReason.ACCEPTED
    assert sound_cues.played == ["thinking"]
    [(messages, media)] = backend.calls
    assert messages[-1] == {
        "role": "user",
        "content": "typed from dock",
    }
    assert media is None
    assert journal_recorder.user_texts == ["typed from dock"]
    assert journal_recorder.user_text_sources == ["dock"]
    assert len(request_recorder.events) == 1
    _assert_model_request_started(
        request_recorder.events[0],
        timestamp=1700000300.0,
        inputs=(ModelRequestInput.TEXT_INPUT,),
        audio_duration_seconds=None,
    )

    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"wav", start_seconds=0, end_seconds=1)
    )
    assert len(backend.calls[-1][1]) == 2


async def test_submit_text_input_automatic_retrieval_timeout_telemetry():
    retrieval_candidate = HistoryRetrievalCandidate(
        reference=JournalEventRef("20260718-120000-ab12", 0),
        text="Реле не сработало.",
        timestamp="2026-07-18T12:00:00+00:00",
        role="assistant",
        source="text",
        source_mode=HistoryRetrievalSourceMode.LEXICAL,
        combined_rank=1,
        semantic_score=0.95,
    )
    retrieval_service = _FakeHistoryRetrievalService(
        HistoryRetrievalResult(
            HistoryRetrievalStatus.ACCEPTED,
            candidates=(retrieval_candidate,),
            lexical_count=1,
            semantic_count=0,
            returned_count=1,
            fallback_mode=HistoryRetrievalFallbackMode.LEXICAL_BY_TIMEOUT,
            elapsed_seconds=0.012,
        )
    )
    bus = EventBus()
    request_recorder = _RequestRecorder(bus)
    orchestrator, backend, sound_cues = _orchestrator(
        bus=bus,
        clock=lambda: 1700000300.0,
        history_retrieval_service=retrieval_service,
    )
    orchestrator._history.add("user", "раньше обсуждали датчики")
    orchestrator._history.add("assistant", "проверим реле")

    result = await orchestrator.submit_text_input("спасибо за отчёт")

    assert result.reason is TextSubmissionReason.ACCEPTED
    assert sound_cues.played == ["thinking"]
    assert retrieval_service.calls
    [query] = retrieval_service.calls
    assert "спасибо за отчёт" in query.query
    assert "раньше обсуждали датчики" in query.query
    [(messages, media)] = backend.calls
    assert media is None
    retrieved_index = next(
        index
        for index, message in enumerate(messages)
        if message["role"] == "system"
        and isinstance(message["content"], str)
        and "Retrieved history" in message["content"]
    )
    user_index = next(
        index
        for index, message in enumerate(messages)
        if message["role"] == "user" and message["content"] == "спасибо за отчёт"
    )
    assert retrieved_index < user_index
    assert "Реле не сработало." in str(messages[retrieved_index]["content"])
    assert all(
        "Retrieved history" not in str(message["content"])
        for message in orchestrator._history.as_messages()
    )
    assert len(request_recorder.events) == 1
    _assert_model_request_started(
        request_recorder.events[0],
        timestamp=1700000300.0,
        inputs=(ModelRequestInput.TEXT_INPUT,),
        audio_duration_seconds=None,
        recent_history_message_count=2,
        retrieval_message_count=1,
    )
    event = request_recorder.events[0]
    assert event.prompt_budget is not None
    assert event.prompt_budget["retrieval_candidate_count"] == 1
    assert event.prompt_budget["retrieval_accepted_passage_count"] == 1
    assert event.prompt_budget["retrieval_elapsed_ms"] >= 0
    assert event.prompt_budget["retrieval_lexical_by_timeout"] is True
    assert event.prompt_budget["retrieval_full_hybrid"] is False
    assert event.prompt_budget["retrieval_failed"] is False
    assert "retrieval_failed_status" not in event.prompt_budget


async def test_submit_text_input_automatic_retrieval_failure_telemetry_reports_status():
    retrieval_service = _FakeHistoryRetrievalService(
        HistoryRetrievalResult(
            HistoryRetrievalStatus.HYDRATION_FAILED,
        )
    )
    bus = EventBus()
    request_recorder = _RequestRecorder(bus)
    orchestrator, backend, sound_cues = _orchestrator(
        bus=bus,
        clock=lambda: 1700000400.0,
        history_retrieval_service=retrieval_service,
    )
    orchestrator._history.add("user", "раньше обсуждали датчики")
    orchestrator._history.add("assistant", "проверим реле")

    result = await orchestrator.submit_text_input("спасибо за отчёт")

    assert result.reason is TextSubmissionReason.ACCEPTED
    assert sound_cues.played == ["thinking"]
    assert retrieval_service.calls
    [(messages, media)] = backend.calls
    assert media is None
    assert all(
        "Retrieved history" not in str(message["content"])
        for message in orchestrator._history.as_messages()
    )
    assert len(request_recorder.events) == 1
    _assert_model_request_started(
        request_recorder.events[0],
        timestamp=1700000400.0,
        inputs=(ModelRequestInput.TEXT_INPUT,),
        audio_duration_seconds=None,
        recent_history_message_count=2,
        retrieval_message_count=0,
    )
    event = request_recorder.events[0]
    assert event.prompt_budget is not None
    assert event.prompt_budget["retrieval_candidate_count"] == 0
    assert event.prompt_budget["retrieval_accepted_passage_count"] == 0
    assert event.prompt_budget["retrieval_elapsed_ms"] >= 0
    assert event.prompt_budget["retrieval_failed"] is True
    assert event.prompt_budget["retrieval_failed_status"] == "hydration_failed"


async def test_voice_turn_does_not_invoke_automatic_retrieval():
    retrieval_service = _FakeHistoryRetrievalService(
        HistoryRetrievalResult(HistoryRetrievalStatus.ACCEPTED)
    )
    orchestrator, backend, sound_cues = _orchestrator(
        history_retrieval_service=retrieval_service
    )

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"wav", start_seconds=0, end_seconds=1)
    )

    assert retrieval_service.calls == []
    assert sound_cues.played == ["thinking"]
    [(messages, _media)] = backend.calls
    assert messages[-1]["content"] == "[голосовое сообщение]"


async def test_automatic_retrieval_scopes_to_current_session_while_solo():
    retrieval_service = _FakeHistoryRetrievalService(
        HistoryRetrievalResult(HistoryRetrievalStatus.ACCEPTED)
    )
    bus = EventBus()
    solo = SoloSessionState(bus, enabled=True)
    journal_recorder = _FakeJournalRecorder()
    orchestrator, _backend, _sound_cues = _orchestrator(
        bus=bus,
        history_retrieval_service=retrieval_service,
        journal_recorder=journal_recorder,
        solo_session_state=solo,
    )

    await orchestrator.submit_text_input("what did we discuss")

    [query] = retrieval_service.calls
    assert query.session_ids == (journal_recorder.session_id,)


async def test_automatic_retrieval_stays_unrestricted_when_solo_is_off():
    retrieval_service = _FakeHistoryRetrievalService(
        HistoryRetrievalResult(HistoryRetrievalStatus.ACCEPTED)
    )
    bus = EventBus()
    solo = SoloSessionState(bus, enabled=False)
    orchestrator, _backend, _sound_cues = _orchestrator(
        bus=bus,
        history_retrieval_service=retrieval_service,
        journal_recorder=_FakeJournalRecorder(),
        solo_session_state=solo,
    )

    await orchestrator.submit_text_input("what did we discuss")

    [query] = retrieval_service.calls
    assert query.session_ids == ()


async def test_automatic_retrieval_is_skipped_while_solo_with_no_session_yet():
    retrieval_service = _FakeHistoryRetrievalService(
        HistoryRetrievalResult(HistoryRetrievalStatus.ACCEPTED)
    )
    bus = EventBus()
    solo = SoloSessionState(bus, enabled=True)
    orchestrator, backend, _sound_cues = _orchestrator(
        bus=bus,
        history_retrieval_service=retrieval_service,
        journal_recorder=None,
        solo_session_state=solo,
    )

    await orchestrator.submit_text_input("what did we discuss")

    assert retrieval_service.calls == []
    [(messages, _media)] = backend.calls
    assert all(
        "Retrieved history" not in str(message["content"]) for message in messages
    )


async def test_submit_text_input_rejections_are_structured_and_do_not_start_turn():
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
    await asyncio.sleep(0)  # task-v1.7.0-2: chat() now runs one hop later

    busy = await orchestrator.submit_text_input("busy")
    empty = await orchestrator.submit_text_input(" \n\t ")

    assert busy.reason is TextSubmissionReason.BUSY
    assert empty.reason is TextSubmissionReason.EMPTY
    assert len(backend.calls) == 1
    assert sound_cues.played == ["thinking"]

    still_busy.set()
    await first


async def test_submit_text_input_rejects_over_limit_without_truncating():
    orchestrator, backend, _sound_cues = _orchestrator(text_input_max_chars=5)

    result = await orchestrator.submit_text_input("123456")

    assert result.reason is TextSubmissionReason.OVER_LIMIT
    assert result.max_chars == 5
    assert backend.calls == []


# --- Orchestrator: attachment turns (task-v1.6.0-6) ------------------------
#
# on_attachment_submission() goes through the same _start_turn() shared
# path as on_utterance()/on_clipboard() - busy-guard, thinking cue, and
# history recording are already covered above and are not re-tested from
# scratch here. These tests focus on what this task actually owns: turning
# an accepted AttachmentPlan into composed text/media, normalizing any
# pending audio (the one plan item planning could not fully resolve), and
# the attachment-specific source/input metadata.

_ATTACHMENT_SAMPLE_RATE = 16000


def _attachment_wav_bytes(duration_seconds: float) -> bytes:
    samples = np.zeros(
        int(_ATTACHMENT_SAMPLE_RATE * duration_seconds), dtype=np.float32
    )
    buffer = io.BytesIO()
    sf.write(buffer, samples, _ATTACHMENT_SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def _image_plan_item(filename: str = "photo.png") -> AttachmentPlanItem:
    return AttachmentPlanItem(
        filename=filename,
        attachment_class=AttachmentClass.IMAGE,
        accepted=True,
        image=PlannedImageMedia(base64_data=base64.b64encode(b"png-bytes").decode()),
    )


def _text_plan_item(
    filename: str = "notes.txt", content: str = "hello"
) -> AttachmentPlanItem:
    wrapped = f"[Attached file: {filename}]\n{content}\n[End of {filename}]"
    return AttachmentPlanItem(
        filename=filename,
        attachment_class=AttachmentClass.TEXT,
        accepted=True,
        text=PlannedTextPart(content=wrapped, truncated=False),
    )


def _audio_plan_item(
    filename: str = "memo.wav", duration_seconds: float = 2.0
) -> AttachmentPlanItem:
    return AttachmentPlanItem(
        filename=filename,
        attachment_class=AttachmentClass.AUDIO,
        accepted=True,
        pending_audio=PendingAudioMedia(
            data=_attachment_wav_bytes(duration_seconds),
            content_type="audio/wav",
            duration_seconds=duration_seconds,
        ),
    )


def _undecodable_audio_plan_item(filename: str = "broken.wav") -> AttachmentPlanItem:
    return AttachmentPlanItem(
        filename=filename,
        attachment_class=AttachmentClass.AUDIO,
        accepted=True,
        pending_audio=PendingAudioMedia(
            data=b"RIFF then garbage", content_type="audio/wav", duration_seconds=1.0
        ),
    )


class _TurnAcceptedRecorder:
    def __init__(self, bus: EventBus) -> None:
        self.events: list[TurnAccepted] = []
        bus.subscribe(TurnAccepted, self._on_event)

    async def _on_event(self, event: TurnAccepted) -> None:
        self.events.append(event)


async def test_on_attachment_submission_sends_composed_text_and_image_media():
    orchestrator, backend, sound_cues = _orchestrator()
    plan = AttachmentPlan(
        items=(_image_plan_item("photo.png"), _text_plan_item("notes.txt", "hello"))
    )

    result = await orchestrator.on_attachment_submission("check these", plan)

    assert result.reason is AttachmentSubmissionReason.ACCEPTED
    assert sound_cues.played == ["thinking"]
    [(messages, media)] = backend.calls
    assert messages[-1] == {
        "role": "user",
        "content": compose_turn_text("check these", plan),
        "images": list(compose_turn_images(plan)),
    }
    assert media == list(compose_turn_images(plan))


async def test_on_attachment_submission_normalizes_audio_and_appends_clip_and_cue():
    orchestrator, backend, _sound_cues = _orchestrator()
    plan = AttachmentPlan(items=(_audio_plan_item("memo.wav", duration_seconds=2.0),))

    await orchestrator.on_attachment_submission("", plan)

    [(messages, media)] = backend.calls
    assert len(media) == 1  # one <=30s clip for a 2s file
    assert messages[-1]["content"] == "[Attached audio: memo.wav, 2.0 s]"


async def test_on_attachment_submission_respects_configured_max_audio_clips():
    # 65 s of audio is 3 clips at the 30 s/clip window (30, 30, 5), which
    # the default cap (3) accepts but a configured cap of 2 must reject -
    # confirms build_app()'s settings.attachments.max_audio_clips actually
    # reaches normalize_audio_attachment(), not just its own default.
    bus = EventBus()
    events: list[SystemEvent] = []

    async def on_system_event(event: SystemEvent) -> None:
        events.append(event)

    bus.subscribe(SystemEvent, on_system_event)
    orchestrator, backend, _sound_cues = _orchestrator(
        bus=bus, max_audio_attachment_clips=2
    )
    plan = AttachmentPlan(
        items=(
            _text_plan_item("notes.txt", "hello"),
            _audio_plan_item("long.wav", duration_seconds=65.0),
        )
    )

    await orchestrator.on_attachment_submission("", plan)

    # the turn still went through with what was left (the text attachment)
    [(messages, _media)] = backend.calls
    assert "hello" in messages[-1]["content"]
    assert "[Attached audio" not in messages[-1]["content"]
    # ... and the audio-specific rejection was not silently dropped
    assert len(events) == 1
    assert events[0].level is EventLevel.WARN
    assert "exceeds" in events[0].message


async def test_on_attachment_submission_orders_media_images_then_audio():
    orchestrator, backend, _sound_cues = _orchestrator()
    plan = AttachmentPlan(
        items=(
            _image_plan_item("a.png"),
            _audio_plan_item("memo.wav", duration_seconds=1.0),
            _image_plan_item("b.png"),
        )
    )

    await orchestrator.on_attachment_submission("look and listen", plan)

    [(_messages, media)] = backend.calls
    image_b64 = base64.b64encode(b"png-bytes").decode()
    assert media[:2] == [image_b64, image_b64]  # images first, upload order
    assert len(media) == 3  # then the one audio clip


def _persisting_orchestrator(tmp_path, chat_impl=None):
    store = JournalStore(tmp_path)
    recorder = JournalRecorder(store, enabled=True)
    repository = SessionFileRepository(
        store.root,
        config=FilesSettings(),
        session_is_visible=lambda sid: bool(store.read_session(sid).records),
    )
    orchestrator, backend, sound_cues = _orchestrator(
        chat_impl=chat_impl,
        journal_recorder=recorder,
        session_file_repository=repository,
        session_file_scope=lambda: resolve_session_file_scope(
            store, recorder.session_id
        ),
    )
    return orchestrator, backend, store, recorder


def _upload(filename: str, data: bytes = b"payload") -> AttachmentUpload:
    return AttachmentUpload(filename=filename, content_type="", data=data)


async def test_persistent_upload_is_written_and_storage_name_surfaced(tmp_path):
    orchestrator, backend, store, recorder = _persisting_orchestrator(tmp_path)

    result = await orchestrator.on_attachment_submission(
        "keep this", AttachmentPlan(items=()), [_upload("plan.md", b"note body")]
    )

    assert result.reason is AttachmentSubmissionReason.ACCEPTED
    [outcome] = result.persisted_files
    assert outcome.persisted
    assert outcome.storage_name.startswith("plan-")
    assert outcome.storage_name.endswith(".md")
    assert outcome.bytes == len(b"note body")
    # The file is a loose file in the current session directory.
    session_dir = store.root / recorder.session_id
    assert (session_dir / outcome.storage_name).read_bytes() == b"note body"
    # Its storage name reaches the model in the same turn.
    [(messages, _media)] = backend.calls
    assert outcome.storage_name in messages[-1]["content"]


async def test_persistent_upload_works_on_first_turn_of_a_new_session(tmp_path):
    # No session exists before this turn: the hook flushes the just-recorded
    # user event so the write is not refused as no-active-session.
    orchestrator, _backend, store, recorder = _persisting_orchestrator(tmp_path)
    assert recorder.session_id is None

    result = await orchestrator.on_attachment_submission(
        "", AttachmentPlan(items=()), [_upload("note.txt", b"x")]
    )

    [outcome] = result.persisted_files
    assert outcome.persisted
    assert (store.root / recorder.session_id / outcome.storage_name).exists()


async def test_persistent_upload_preserves_current_turn_image_media(tmp_path):
    orchestrator, backend, _store, _recorder = _persisting_orchestrator(tmp_path)
    plan = AttachmentPlan(items=(_image_plan_item("photo.png"),))

    result = await orchestrator.on_attachment_submission(
        "look", plan, [_upload("photo.png", b"png-bytes")]
    )

    # Persisted AND still delivered as this turn's transient image media.
    assert result.persisted_files[0].persisted
    [(_messages, media)] = backend.calls
    assert media == list(compose_turn_images(plan))


async def test_persistent_upload_reports_repository_rejection(tmp_path):
    # A traversal filename is rejected by the repository and never becomes a
    # storage path; no turn-aborting exception escapes.
    orchestrator, _backend, store, recorder = _persisting_orchestrator(tmp_path)

    result = await orchestrator.on_attachment_submission(
        "hi", AttachmentPlan(items=()), [_upload("../escape.md", b"x")]
    )

    [outcome] = result.persisted_files
    assert not outcome.persisted
    assert outcome.error is not None
    assert list((store.root / recorder.session_id).glob("*.md")) == []


async def test_persistent_upload_reported_unavailable_without_repository(tmp_path):
    # Journal recorder present but no session-file repository wired: the
    # submission still proceeds and each marked file is reported unavailable.
    orchestrator, _backend, _sound_cues = _orchestrator(
        journal_recorder=JournalRecorder(JournalStore(tmp_path), enabled=True)
    )

    result = await orchestrator.on_attachment_submission(
        "hi", AttachmentPlan(items=()), [_upload("note.md", b"x")]
    )

    [outcome] = result.persisted_files
    assert not outcome.persisted
    assert outcome.error == "session files unavailable"


async def test_on_attachment_submission_reports_source_and_input_metadata():
    bus = EventBus()
    turn_recorder = _TurnAcceptedRecorder(bus)
    request_recorder = _RequestRecorder(bus)
    orchestrator, _backend, _sound_cues = _orchestrator(
        bus=bus, clock=lambda: 1700000200.0
    )
    plan = AttachmentPlan(
        items=(
            _image_plan_item("photo.png"),
            _text_plan_item("notes.txt"),
            _audio_plan_item("memo.wav", duration_seconds=3.0),
        )
    )

    await orchestrator.on_attachment_submission("hi", plan)

    assert turn_recorder.events == [TurnAccepted(source=TurnSource.ATTACHMENT)]
    assert len(request_recorder.events) == 1
    _assert_model_request_started(
        request_recorder.events[0],
        timestamp=1700000200.0,
        inputs=(
            ModelRequestInput.ATTACHMENT_IMAGE,
            ModelRequestInput.ATTACHMENT_TEXT,
            ModelRequestInput.ATTACHMENT_AUDIO,
        ),
        audio_duration_seconds=3.0,
    )


async def test_on_attachment_submission_undecodable_audio_warns_and_continues():
    bus = EventBus()
    orchestrator, backend, _sound_cues = _orchestrator(bus=bus)
    events: list[SystemEvent] = []

    async def on_system_event(event: SystemEvent) -> None:
        events.append(event)

    bus.subscribe(SystemEvent, on_system_event)
    plan = AttachmentPlan(
        items=(
            _text_plan_item("notes.txt", "hello"),
            _undecodable_audio_plan_item("broken.wav"),
        )
    )

    await orchestrator.on_attachment_submission("", plan)

    # the turn still went through with what was left (the text attachment)
    [(messages, media)] = backend.calls
    assert media is None
    assert "hello" in messages[-1]["content"]
    assert "[Attached audio" not in messages[-1]["content"]
    # ... and the audio-specific failure was not silently dropped
    assert len(events) == 1
    assert events[0].level is EventLevel.WARN
    assert "broken.wav" in events[0].message


async def test_attachment_media_is_not_stored_in_conversation_history():
    orchestrator, _backend, _sound_cues = _orchestrator()
    plan = AttachmentPlan(
        items=(_image_plan_item("photo.png"), _audio_plan_item("memo.wav")),
    )

    await orchestrator.on_attachment_submission("describe these", plan)
    await orchestrator.on_response_token(ResponseToken(text="Done."))
    await orchestrator.on_response_complete(_complete_event())

    messages = orchestrator._history.as_messages()
    assert all("images" not in message for message in messages)
    recorded_texts = " ".join(str(message["content"]) for message in messages)
    assert base64.b64encode(b"png-bytes").decode() not in recorded_texts


async def test_attachment_submission_is_ignored_while_busy():
    still_busy = asyncio.Event()

    async def slow_chat() -> None:
        await still_busy.wait()

    journal_recorder = _FakeJournalRecorder()
    orchestrator, backend, sound_cues = _orchestrator(
        chat_impl=slow_chat, journal_recorder=journal_recorder
    )
    first = asyncio.create_task(
        orchestrator.on_utterance(
            UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
        )
    )
    await asyncio.sleep(0)  # let the first call start and set _busy
    await asyncio.sleep(0)  # task-v1.7.0-2: chat() now runs one hop later

    await orchestrator.on_screenshot(
        ScreenshotCaptured(png_bytes=b"png", mode="full", width=1, height=1)
    )
    plan = AttachmentPlan(items=(_text_plan_item("notes.txt"),))
    result = await orchestrator.on_attachment_submission("ignored while busy", plan)

    assert result.reason is AttachmentSubmissionReason.BUSY
    assert len(backend.calls) == 1  # the attachment submission was ignored
    assert sound_cues.played == ["thinking"]  # only the in-flight turn's cue
    assert journal_recorder.user_texts == []  # no user event was journaled

    still_busy.set()
    await first
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()

    # the pending screenshot from before the rejected submission survived
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"c", start_seconds=0, end_seconds=1)
    )
    assert len(backend.calls[-1][1]) == 2  # audio + the surviving screenshot


async def test_attachment_submission_rejects_plan_with_no_turn_content():
    orchestrator, backend, sound_cues = _orchestrator()
    plan = AttachmentPlan(
        items=(
            AttachmentPlanItem(
                filename="manual.pdf",
                attachment_class=None,
                accepted=False,
                rejection_reason="manual.pdf: unsupported file type.",
            ),
        )
    )

    result = await orchestrator.on_attachment_submission("", plan)

    assert result.reason is AttachmentSubmissionReason.NO_ACCEPTED_CONTENT
    assert backend.calls == []
    assert sound_cues.played == []


async def test_attachment_submission_backend_failure_plays_error_and_clears_busy():
    async def failing_chat() -> None:
        raise ValueError("boom")

    orchestrator, backend, sound_cues = _orchestrator(chat_impl=failing_chat)
    plan = AttachmentPlan(items=(_text_plan_item("notes.txt"),))

    await orchestrator.on_attachment_submission("hi", plan)

    assert sound_cues.played == ["thinking", "error"]

    # busy was cleared, so a subsequent submission is not ignored
    await orchestrator.on_attachment_submission("hi again", plan)
    assert len(backend.calls) == 2


async def test_attachment_submission_records_journal_with_attachment_source():
    journal_recorder = _FakeJournalRecorder()
    orchestrator, _backend, _sound_cues = _orchestrator(
        journal_recorder=journal_recorder
    )
    plan = AttachmentPlan(items=(_text_plan_item("notes.txt", "hello"),))

    await orchestrator.on_attachment_submission("check this", plan)

    assert journal_recorder.user_text_sources == ["attachment"]
    assert journal_recorder.user_texts == [compose_turn_text("check this", plan)]


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


async def test_journal_recorder_receives_turn_inputs_and_final_response_only():
    journal_recorder = _FakeJournalRecorder()
    orchestrator, _backend, _sound_cues = _orchestrator(
        journal_recorder=journal_recorder
    )

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"voice clip", start_seconds=0, end_seconds=1)
    )
    await orchestrator.on_response_token(ResponseToken(text="final "))
    await orchestrator.on_response_token(ResponseToken(text="answer"))
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()
    await orchestrator.on_clipboard(
        ClipboardSubmitted(text="clipboard text", truncated=False, is_empty=False)
    )

    assert journal_recorder.voice_wavs == [b"voice clip"]
    assert journal_recorder.user_texts == ["clipboard text"]
    assert journal_recorder.assistant_texts == ["final answer"]


async def test_journal_recorder_ignores_completion_without_accepted_user_turn():
    journal_recorder = _FakeJournalRecorder()
    orchestrator, _backend, _sound_cues = _orchestrator(
        journal_recorder=journal_recorder
    )

    await orchestrator.on_response_complete(_complete_event())

    assert journal_recorder.voice_wavs == []
    assert journal_recorder.user_texts == []
    assert journal_recorder.assistant_texts == []


async def test_fork_from_journal_session_seeds_history_and_records_provenance(
    tmp_path,
):
    store = JournalStore(tmp_path)
    source_session_id = "20260718-150000-ab12"
    source_end_timestamp = "2026-07-18T15:01:00+01:00"
    store.append(
        JournalEvent(
            session_id=source_session_id,
            timestamp="2026-07-18T15:00:00+01:00",
            source="dock",
            role="user",
            text="remember the relay",
            media=[],
            transcript=None,
        )
    )
    store.append(
        JournalEvent(
            session_id=source_session_id,
            timestamp=source_end_timestamp,
            source="assistant",
            role="assistant",
            text="The relay is stable.",
            media=[],
            transcript=None,
        )
    )
    source_log = tmp_path / source_session_id / "events.jsonl"
    source_bytes_before = source_log.read_bytes()
    history = ConversationHistory()
    recorder = JournalRecorder(
        store, clock=lambda: datetime.fromisoformat("2026-07-19T10:00:00+01:00")
    )
    orchestrator = Orchestrator(
        _FakeBackend(), history, _FakeSoundCues(), journal_recorder=recorder
    )

    result = await orchestrator.fork_from_journal_session(
        source_session_id=source_session_id,
        replay=store.read_session(source_session_id),
        source_end_timestamp=source_end_timestamp,
        seed_budget_chars=1000,
    )
    await recorder.wait_for_pending()

    assert result.accepted
    assert result.new_session_id is not None
    assert source_log.read_bytes() == source_bytes_before
    expected_provenance = main_module._fork_provenance_seed_line(source_end_timestamp)
    assert history.as_messages() == [
        {"role": "system", "content": expected_provenance},
        {"role": "user", "content": "remember the relay"},
        {"role": "assistant", "content": "The relay is stable."},
    ]
    fork_events = store.read_session(result.new_session_id).events
    assert len(fork_events) == 1
    assert fork_events[0].role == "system"
    assert fork_events[0].source == "fork"
    assert fork_events[0].text == expected_provenance
    assert fork_events[0].metadata == {
        "continued_from": source_session_id,
        "seed": {
            "dropped_turns": 0,
            "skipped_events": 0,
            "excluded_events": 0,
            "truncated": False,
        },
    }


async def test_fork_from_journal_session_rejects_busy_without_changing_history():
    history = ConversationHistory()
    history.add("user", "existing")
    orchestrator = Orchestrator(_FakeBackend(), history, _FakeSoundCues())
    orchestrator._busy = True

    result = await orchestrator.fork_from_journal_session(
        source_session_id="20260718-150000-ab12",
        replay=main_module.JournalReplay(
            records=[
                JournalEventRecord(
                    JournalEventRef("20260718-150000-ab12", 0),
                    JournalEvent(
                        session_id="20260718-150000-ab12",
                        timestamp="2026-07-18T15:00:00+01:00",
                        source="dock",
                        role="user",
                        text="new seed",
                        media=[],
                        transcript=None,
                    ),
                )
            ],
            corrupt_lines=0,
        ),
        source_end_timestamp="2026-07-18T15:00:00+01:00",
        seed_budget_chars=1000,
    )

    assert result.reason is ForkSessionReason.BUSY
    assert history.as_messages() == [{"role": "user", "content": "existing"}]


async def test_fork_from_journal_session_reports_oversize_turn():
    orchestrator = Orchestrator(_FakeBackend(), ConversationHistory(), _FakeSoundCues())

    result = await orchestrator.fork_from_journal_session(
        source_session_id="20260718-150000-ab12",
        replay=main_module.JournalReplay(
            records=[
                JournalEventRecord(
                    JournalEventRef("20260718-150000-ab12", 0),
                    JournalEvent(
                        session_id="20260718-150000-ab12",
                        timestamp="2026-07-18T15:00:00+01:00",
                        source="dock",
                        role="user",
                        text="too long",
                        media=[],
                        transcript=None,
                    ),
                )
            ],
            corrupt_lines=0,
        ),
        source_end_timestamp="2026-07-18T15:00:00+01:00",
        seed_budget_chars=3,
    )

    assert result.reason is ForkSessionReason.OVERSIZE_TURN
    assert result.oversize_turn_chars == len("too long")
    assert result.max_chars == 3


async def test_start_new_context_clears_history_and_records_blank_session(
    tmp_path,
):
    prompts = ["base v1", "base v2"]

    def next_prompt(_solo: bool = False) -> str:
        return prompts.pop(0)

    store = JournalStore(tmp_path)
    recorder = JournalRecorder(
        store, clock=lambda: datetime.fromisoformat("2026-07-19T10:00:00+01:00")
    )
    history = ConversationHistory()
    history.add("user", "old context")
    backend = _FakeBackend()
    orchestrator = Orchestrator(
        backend,
        history,
        _FakeSoundCues(),
        journal_recorder=recorder,
        system_prompt_provider=next_prompt,
    )

    result = await orchestrator.start_new_context()

    assert result.accepted
    assert result.session_id == recorder.session_id
    assert history.as_messages() == []
    replay = store.read_session(result.session_id)
    [event] = replay.events
    assert event.role == "system"
    assert event.source == "context"
    assert event.text == main_module._new_context_provenance_line()
    assert event.metadata == {"kind": "new_context"}

    await orchestrator.submit_text_input("after reset")
    assert backend.calls[-1][0][0] == {"role": "system", "content": "base v2"}


async def test_start_new_context_rejects_busy_without_changing_history():
    history = ConversationHistory()
    history.add("user", "existing")
    orchestrator = Orchestrator(_FakeBackend(), history, _FakeSoundCues())
    orchestrator._busy = True

    result = await orchestrator.start_new_context()

    assert result.reason is NewContextReason.BUSY
    assert history.as_messages() == [{"role": "user", "content": "existing"}]


async def test_system_prompt_provider_is_sampled_on_session_start_only():
    prompts = ["base v1", "base v2", "base v3"]

    def next_prompt(_solo: bool = False) -> str:
        return prompts.pop(0)

    backend = _FakeBackend()
    history = ConversationHistory()
    orchestrator = Orchestrator(
        backend,
        history,
        _FakeSoundCues(),
        system_prompt_provider=next_prompt,
    )

    await orchestrator.submit_text_input("first")
    assert backend.calls[-1][0][0] == {"role": "system", "content": "base v1"}
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()

    await orchestrator.submit_text_input("second while same session")
    assert backend.calls[-1][0][0] == {"role": "system", "content": "base v1"}
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()

    orchestrator.clear()
    await orchestrator.submit_text_input("after reset")
    assert backend.calls[-1][0][0] == {"role": "system", "content": "base v2"}


async def test_system_prompt_provider_receives_solo_state_at_session_start():
    def prompt_for(solo: bool) -> str:
        return "solo prompt" if solo else "normal prompt"

    bus = EventBus()
    solo = SoloSessionState(bus, enabled=False)
    backend = _FakeBackend()
    orchestrator = Orchestrator(
        backend,
        ConversationHistory(),
        _FakeSoundCues(),
        system_prompt_provider=prompt_for,
        solo_session_state=solo,
    )

    await orchestrator.submit_text_input("first")
    assert backend.calls[-1][0][0] == {"role": "system", "content": "normal prompt"}
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()

    # Toggling solo mid-conversation must not retroactively change the
    # prompt already baked into this running session - only the next
    # session-start moment (clear()) re-samples it.
    await solo.set_enabled(True)
    await orchestrator.submit_text_input("still same session")
    assert backend.calls[-1][0][0] == {"role": "system", "content": "normal prompt"}
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()

    orchestrator.clear()
    await orchestrator.submit_text_input("after new context, solo still on")
    assert backend.calls[-1][0][0] == {"role": "system", "content": "solo prompt"}


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
    await asyncio.sleep(0)  # task-v1.7.0-2: chat() now runs one hop later
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


async def test_finish_turn_waits_for_pending_journal_writes():
    """Regression (task-v1.7.0-2 review): JournalRecorder schedules its
    actual disk write as a background task rather than blocking on it
    (JournalRecorder._schedule()), so finish_turn() returning - and the
    caller announcing the turn is over - used to race ahead of it. Masked
    for a normal turn's multi-second duration (generation + TTS gives the
    write plenty of time), but a turn ending very quickly - an interrupt
    during the "thinking" phase, confirmed live - could return before the
    write, and the live Journal panel's update, had happened at all.
    finish_turn() is the one place both a normal completion and an
    interrupt converge to end a turn, so the fix belongs here rather than
    duplicated in each caller."""
    write_finished = asyncio.Event()

    class _SlowJournalRecorder:
        def __init__(self) -> None:
            self.wait_calls = 0

        async def wait_for_pending(self) -> None:
            self.wait_calls += 1
            await write_finished.wait()

    journal_recorder = _SlowJournalRecorder()
    orchestrator, _backend, _sound_cues = _orchestrator(
        journal_recorder=journal_recorder
    )
    orchestrator._busy = True

    finish_task = asyncio.create_task(orchestrator.finish_turn())
    await asyncio.sleep(0)

    assert journal_recorder.wait_calls == 1
    assert orchestrator.is_busy is True  # finish_turn() has not returned yet

    write_finished.set()
    await finish_task

    assert orchestrator.is_busy is False


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


# --- cancel_active_turn() (task-v1.7.0-2 interrupt) -------------------------


async def test_cancel_active_turn_is_a_no_op_when_idle():
    orchestrator, _backend, _sound_cues = _orchestrator()

    orchestrator.cancel_active_turn()  # must not raise

    assert orchestrator.is_busy is False


async def test_cancel_active_turn_cancels_the_in_flight_backend_call():
    still_busy = asyncio.Event()

    async def hanging_chat() -> None:
        await still_busy.wait()
        raise AssertionError("should have been cancelled first")

    orchestrator, _backend, sound_cues = _orchestrator(chat_impl=hanging_chat)

    turn_task = asyncio.create_task(
        orchestrator.on_utterance(
            UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
        )
    )
    await asyncio.sleep(0)  # let _start_turn create the active chat task

    orchestrator.cancel_active_turn()
    await turn_task  # returns quietly - see _start_turn's CancelledError handling

    # _start_turn() deliberately does not clear busy or play a cue on
    # cancellation - that is the interrupt handler's job (app.py), so it
    # cannot race a concurrently-running normal completion path.
    assert orchestrator.is_busy is True
    assert sound_cues.played == ["thinking"]
    assert orchestrator._active_chat_task is None


def test_claim_turn_end_is_a_single_use_gate():
    """Review finding 1: exactly one caller may ever win claim_turn_end()
    per turn - the mechanism _on_full_response_complete() and
    _cancel_current_turn() both rely on to avoid double-finishing the
    same turn."""
    orchestrator, _backend, _sound_cues = _orchestrator()
    orchestrator._busy = True

    assert orchestrator.claim_turn_end() is True
    assert orchestrator.claim_turn_end() is False
    assert orchestrator.claim_turn_end() is False  # stays lost, not just once


def test_claim_turn_end_is_false_when_idle():
    orchestrator, _backend, _sound_cues = _orchestrator()

    assert orchestrator.claim_turn_end() is False


async def test_interrupt_racing_full_response_complete_only_finishes_once():
    """Regression for review finding 1 (both rounds). Round 1: a hotkey
    interrupt landing while _on_full_response_complete() is still
    awaiting trailing TTS (wait_for_pending()) used to independently
    clear busy, publish TurnCompleted, and play a cue - this proves the
    finish sequence itself still runs exactly once. Round 2: gating
    tts_output.cancel() itself on the same claim meant the hotkey did
    nothing at all once the normal path had already claimed - the single
    most common moment someone wants to interrupt (right after
    generation finishes, while Jarvis is still reading a long answer
    aloud) - so stopping playback must happen regardless of who wins."""
    orchestrator, backend, sound_cues = _orchestrator()
    orchestrator._busy = True
    still_playing = asyncio.Event()

    class _SlowTts:
        def __init__(self) -> None:
            self.cancel_calls = 0
            self._cancelled_while_waiting = False

        async def on_response_complete(self, event) -> None:
            pass

        async def wait_for_pending(self) -> None:
            await still_playing.wait()
            if self._cancelled_while_waiting:
                # Mirrors the real TtsOutput: cancel() cancels the same
                # pending tasks this is gathering, so the gather() call
                # raises CancelledError instead of returning cleanly.
                raise asyncio.CancelledError()

        def cancel(self) -> None:
            self.cancel_calls += 1
            self._cancelled_while_waiting = True
            still_playing.set()

    tts_output = _SlowTts()
    app = _app_for_interrupt_test(orchestrator, backend, sound_cues, tts_output)

    normal_path_task = asyncio.create_task(
        _on_full_response_complete(app, _complete_event())
    )
    await asyncio.sleep(0)  # let it claim and block on wait_for_pending()

    interrupted = await _cancel_current_turn(app)  # loses the finish-sequence claim

    # TTS stops immediately even though the claim was lost
    assert tts_output.cancel_calls == 1
    assert interrupted is True  # a turn *was* cancelled, even without claiming

    await normal_path_task  # its own finally still runs, exactly once

    assert orchestrator.is_busy is False
    assert sound_cues.played[-1] == "listening"


async def test_stale_response_complete_after_interrupt_is_a_no_op():
    """Reverse ordering of the same race: the interrupt claims first; a
    ResponseComplete for that now-ended turn arriving afterward (the
    backend task finishing just after cancellation was requested) must
    not record history, flush TTS, or run its own finish sequence."""
    orchestrator, backend, sound_cues = _orchestrator()
    orchestrator._busy = True

    class _RecordingTts:
        def __init__(self) -> None:
            self.on_response_complete_calls = 0

        async def on_response_complete(self, event) -> None:
            self.on_response_complete_calls += 1

        async def wait_for_pending(self) -> None:
            pass

        def cancel(self) -> None:
            pass

    tts_output = _RecordingTts()
    app = _app_for_interrupt_test(orchestrator, backend, sound_cues, tts_output)

    interrupted = await _cancel_current_turn(app)
    assert interrupted is True
    sound_cues.played.clear()  # isolate what the stale event does next

    await _on_full_response_complete(app, _complete_event())

    assert tts_output.on_response_complete_calls == 0
    assert sound_cues.played == []


async def test_interrupt_before_backend_dispatch_prevents_the_call_entirely():
    """Regression for review finding 2 (both rounds): an interrupt
    landing between _busy=True and _active_chat_task's creation (during
    journal/bus/cue work) used to be silently dropped -
    cancel_active_turn() had no task to cancel yet, so _start_turn() went
    on to dispatch the backend call anyway, right after the interrupt had
    already told the rest of the app the turn was over. Round 2: even
    with that fixed, _start_turn() still went on to publish TurnAccepted
    and play the "thinking" cue after the interrupt had already published
    TurnCompleted - a UI-visible TurnCompleted -> TurnAccepted with
    nothing to follow, since the backend call itself was correctly
    skipped. This proves _start_turn() stops producing *any* further
    visible side effect, not just the backend call."""
    journal_recorder = _FakeJournalRecorder()
    real_record_voice_user = journal_recorder.record_voice_user
    interrupt_landed = asyncio.Event()

    async def slow_record_voice_user(*args, **kwargs):
        await interrupt_landed.wait()  # the interrupt fires during this call
        return await real_record_voice_user(*args, **kwargs)

    journal_recorder.record_voice_user = slow_record_voice_user

    bus = EventBus()
    turn_accepted_events = []

    async def on_turn_accepted(event) -> None:
        turn_accepted_events.append(event)

    bus.subscribe(TurnAccepted, on_turn_accepted)

    orchestrator, backend, sound_cues = _orchestrator(
        journal_recorder=journal_recorder, bus=bus
    )
    tts_output = _RecordingTtsOutputForInterrupt()
    app = App(
        bus=bus,
        backend=backend,
        audio_input=None,
        tts_output=tts_output,
        capture_input=None,
        orchestrator=orchestrator,
        sound_cues=sound_cues,
        thinking_mode=None,
        response_mode=None,
        settings=Settings(vad=VadSettings(resume_cooldown_seconds=0.001)),
    )

    turn_task = asyncio.create_task(
        orchestrator.on_utterance(
            UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
        )
    )
    await asyncio.sleep(0)  # let _start_turn set busy and reach the journal call

    assert orchestrator.is_busy is True
    assert orchestrator._active_chat_task is None  # confirms the right window

    interrupted = await _cancel_current_turn(app)
    assert sound_cues.played == ["listening"]  # nothing from _start_turn yet

    interrupt_landed.set()
    await turn_task

    assert interrupted is True
    assert len(backend.calls) == 0  # the backend was never actually called
    assert orchestrator.is_busy is False
    assert turn_accepted_events == []  # TurnAccepted never published
    assert sound_cues.played == ["listening"]  # "thinking" never played either


# --- record_aborted_turn (task-v1.7.0-3 turn/journal handling) --------------
#
# Task-v1.7.0-2 deliberately left an interrupted turn out of
# ConversationHistory/the journal entirely (its own boundary called this an
# acceptable placeholder for task 3 to revisit). These tests cover the fix:
# a turn that ends without a normal ResponseComplete - cancelled by an
# interrupt, or ended by a hard dispatch failure - is recorded instead of
# silently dropped.


async def test_record_aborted_turn_records_partial_text_and_interrupted_outcome():
    journal_recorder = _FakeJournalRecorder()
    still_busy = asyncio.Event()

    async def hanging_chat() -> None:
        await still_busy.wait()

    orchestrator, backend, sound_cues = _orchestrator(
        chat_impl=hanging_chat, journal_recorder=journal_recorder
    )
    tts_output = _RecordingTtsOutputForInterrupt()
    app = _app_for_interrupt_test(orchestrator, backend, sound_cues, tts_output)

    turn_task = asyncio.create_task(
        orchestrator.on_clipboard(
            ClipboardSubmitted(
                text="what is the weather", truncated=False, is_empty=False
            )
        )
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)  # let chat() actually start
    await orchestrator.on_response_token(ResponseToken(text="It "))
    await orchestrator.on_response_token(ResponseToken(text="looks"))

    interrupted = await _cancel_current_turn(app)
    await turn_task

    assert interrupted is True
    assert orchestrator._history.as_messages() == [
        {"role": "user", "content": "what is the weather"},
        {"role": "assistant", "content": "It looks"},
        {"role": "system", "content": main_module._INTERRUPTED_HISTORY_NOTE},
    ]
    assert journal_recorder.assistant_texts == ["It looks"]
    assert journal_recorder.assistant_outcomes == [TurnOutcome.INTERRUPTED]


async def test_record_aborted_turn_with_no_streamed_text_skips_the_assistant_turn():
    """An interrupt during the "thinking" phase, before any token streamed:
    no empty assistant Turn is added (nothing was actually said), but the
    user's turn and the interruption note still are, and the journal still
    gets an explicit (empty-text) interrupted entry rather than nothing."""
    journal_recorder = _FakeJournalRecorder()
    still_busy = asyncio.Event()

    async def hanging_chat() -> None:
        await still_busy.wait()

    orchestrator, backend, sound_cues = _orchestrator(
        chat_impl=hanging_chat, journal_recorder=journal_recorder
    )
    tts_output = _RecordingTtsOutputForInterrupt()
    app = _app_for_interrupt_test(orchestrator, backend, sound_cues, tts_output)

    turn_task = asyncio.create_task(
        orchestrator.on_clipboard(
            ClipboardSubmitted(text="are you there", truncated=False, is_empty=False)
        )
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    interrupted = await _cancel_current_turn(app)
    await turn_task

    assert interrupted is True
    assert orchestrator._history.as_messages() == [
        {"role": "user", "content": "are you there"},
        {"role": "system", "content": main_module._INTERRUPTED_HISTORY_NOTE},
    ]
    assert journal_recorder.assistant_texts == [""]
    assert journal_recorder.assistant_outcomes == [TurnOutcome.INTERRUPTED]


async def test_interrupt_during_journal_recording_await_records_this_turns_text():
    """Regression, three bugs found across two review rounds, all in the
    same window: an interrupt landing while _start_turn() is still awaiting
    record_text_user()/record_voice_user() for *this* turn.

    (1) History: _current_turn_history_text/_response_tokens used to be
    assigned only after the journal-recording await and both
    _interrupt_requested checks in _start_turn() - reachable from the
    second turn onward, record_aborted_turn() would describe the *previous*
    turn's leftover text/tokens.
    (2) Journal presence: _journal_turn_started used to be set True only
    *after* the same await, so a concurrent record_aborted_turn() running
    while the write was still in flight saw it as still False and silently
    skipped the journal side entirely - this test originally only asserted
    history and missed that defect.
    (3) Journal order: fixing (2) by setting the flag *before* the await
    then let record_aborted_turn() call record_assistant() before
    record_text_user() had actually reached the recorder - reversing the
    append-only journal's order for this turn (assistant outcome appended
    before the user message it answers). record_aborted_turn() now checks
    _journal_recording_done: not yet set here (this test's slow mock is the
    only way to reach that branch - the real JournalRecorder never
    suspends before scheduling its own write), so the outcome write is
    deferred to run after record_text_user() rather than racing it."""
    journal_recorder = _FakeJournalRecorder()
    orchestrator, backend, sound_cues = _orchestrator(journal_recorder=journal_recorder)
    tts_output = _RecordingTtsOutputForInterrupt()
    app = _app_for_interrupt_test(orchestrator, backend, sound_cues, tts_output)

    # First turn completes normally, leaving stale text/tokens behind.
    await orchestrator.on_clipboard(
        ClipboardSubmitted(text="first question", truncated=False, is_empty=False)
    )
    await orchestrator.on_response_token(ResponseToken(text="first answer"))
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()

    # Second turn's journal write is slow enough for an interrupt to land
    # while _start_turn() is still awaiting it.
    interrupt_landed = asyncio.Event()
    real_record_text_user = journal_recorder.record_text_user

    async def slow_record_text_user(*args, **kwargs):
        await interrupt_landed.wait()
        return await real_record_text_user(*args, **kwargs)

    journal_recorder.record_text_user = slow_record_text_user

    turn_task = asyncio.create_task(
        orchestrator.on_clipboard(
            ClipboardSubmitted(text="second question", truncated=False, is_empty=False)
        )
    )
    await asyncio.sleep(0)  # let _start_turn set busy and reach the journal call

    interrupted = await _cancel_current_turn(app)
    # record_aborted_turn() must not have written the outcome yet - the
    # user's own entry for this turn has not reached the recorder at all.
    assert journal_recorder.call_order == [
        "text_user:first question",
        "assistant:'first answer':None",
    ]
    assert orchestrator._pending_aborted_journal_write is not None

    interrupt_landed.set()
    await turn_task
    await orchestrator._pending_aborted_journal_write

    assert interrupted is True
    assert orchestrator._history.as_messages() == [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second question"},
        {"role": "system", "content": main_module._INTERRUPTED_HISTORY_NOTE},
    ]
    # The journal side of the same fix: the first (normal) turn's own
    # record_assistant() call carries no outcome; the second (interrupted)
    # turn's must still land, tagged, even though the interrupt raced the
    # still-in-flight journal-recording call for *this* turn - and, per
    # finding (3), strictly *after* that turn's own user entry, never before.
    assert journal_recorder.call_order == [
        "text_user:first question",
        "assistant:'first answer':None",
        "text_user:second question",
        "assistant:'':TurnOutcome.INTERRUPTED",
    ]
    assert journal_recorder.assistant_texts == ["first answer", ""]
    assert journal_recorder.assistant_outcomes == [None, TurnOutcome.INTERRUPTED]


async def test_backend_failure_records_aborted_turn_as_failed():
    journal_recorder = _FakeJournalRecorder()

    async def failing_chat() -> None:
        raise ValueError("boom")

    orchestrator, backend, sound_cues = _orchestrator(
        chat_impl=failing_chat, journal_recorder=journal_recorder
    )

    await orchestrator.on_clipboard(
        ClipboardSubmitted(text="will this work", truncated=False, is_empty=False)
    )

    assert orchestrator._history.as_messages() == [
        {"role": "user", "content": "will this work"},
        {"role": "system", "content": main_module._FAILED_HISTORY_NOTE},
    ]
    assert journal_recorder.assistant_texts == [""]
    assert journal_recorder.assistant_outcomes == [TurnOutcome.FAILED]
    assert orchestrator.is_busy is False  # unchanged existing behavior


async def test_backend_failure_does_not_double_record_when_interrupt_already_claimed():
    """If a hotkey interrupt wins claim_turn_end() first (e.g. landing in
    the same window as a hard dispatch failure), the failure path's own new
    recording call must be a no-op rather than double-recording the turn -
    mirrors the same guard _cancel_current_turn() relies on."""
    journal_recorder = _FakeJournalRecorder()

    async def failing_chat() -> None:
        raise ValueError("boom")

    orchestrator, _backend, _sound_cues = _orchestrator(
        chat_impl=failing_chat, journal_recorder=journal_recorder
    )
    orchestrator._busy = True
    assert orchestrator.claim_turn_end() is True  # a concurrent interrupt won first

    await orchestrator._dispatch_backend_request(
        [{"role": "user", "content": "x"}],
        None,
        ReasoningLevel.OFF,
        (),
        None,
        asyncio.Event(),
    )

    assert orchestrator._history.as_messages() == []
    assert journal_recorder.assistant_texts == []


async def test_stale_interrupted_turn_does_not_dispatch_after_a_later_turn_starts():
    """Regression (task-v1.7.0-3 review, third round): _cancel_current_turn()
    clears busy without waiting for the interrupted turn's own _start_turn()
    to actually exit. If that coroutine (turn A) is still suspended - here,
    a slow journal-recording call - when a genuinely new turn B is accepted
    and runs its own _start_turn(), B replaces self._interrupt_requested and
    self._journal_recording_done with its own fresh Events. When A's
    suspended call finally resumes, it must still recognize *it* was
    interrupted (not read B's fresh, unset Event) and must still signal
    *its own* deferred journal write (not B's) - otherwise A's deferred
    assistant write hangs forever, and A goes on to dispatch a stale,
    unwanted second backend request into whatever state B has since set up."""
    journal_recorder = _FakeJournalRecorder()
    turn_a_landed = asyncio.Event()
    real_record_text_user = journal_recorder.record_text_user
    delay_next_call = True

    async def maybe_slow_record_text_user(*args, **kwargs):
        nonlocal delay_next_call
        if delay_next_call:
            delay_next_call = False
            await turn_a_landed.wait()
        return await real_record_text_user(*args, **kwargs)

    journal_recorder.record_text_user = maybe_slow_record_text_user

    orchestrator, backend, sound_cues = _orchestrator(journal_recorder=journal_recorder)
    tts_output = _RecordingTtsOutputForInterrupt()
    app = _app_for_interrupt_test(orchestrator, backend, sound_cues, tts_output)

    turn_a_task = asyncio.create_task(
        orchestrator.on_clipboard(
            ClipboardSubmitted(text="turn A", truncated=False, is_empty=False)
        )
    )
    await asyncio.sleep(0)  # let _start_turn (A) set busy and reach the journal call

    interrupted = await _cancel_current_turn(app)
    assert interrupted is True
    assert orchestrator.is_busy is False  # A's own cleanup already cleared busy

    # Turn B is accepted and runs to its own (fake-backend) completion while
    # A's _start_turn() is still suspended in the journal call above.
    await orchestrator.on_clipboard(
        ClipboardSubmitted(text="turn B", truncated=False, is_empty=False)
    )
    assert len(backend.calls) == 1  # only B's - A must not have dispatched yet

    # A's slow call finally resolves.
    turn_a_landed.set()
    await turn_a_task
    await orchestrator._pending_aborted_journal_write  # A's deferred write, not lost

    assert len(backend.calls) == 1  # still just B's - A never dispatched
    assert journal_recorder.call_order == [
        "text_user:turn B",
        "text_user:turn A",
        "assistant:'':TurnOutcome.INTERRUPTED",
    ]


async def test_interrupt_during_model_request_started_publish_does_not_dispatch():
    """Regression (task-v1.7.0-3 review, fourth round):
    _dispatch_backend_request() only checked interrupt_requested once, right
    before publishing ModelRequestStarted - EventBus.publish() awaits every
    subscriber, a real suspension point, and an interrupt landing during it
    finds no _active_chat_task yet to cancel (only created after the publish
    returns), so cancel_active_turn() has nothing to act on. Without a
    second check right after the publish, resuming here would still go on
    to create the backend task and dispatch a stale request, even though
    _cancel_current_turn() had already run its full cleanup for this turn."""
    bus = EventBus()
    subscriber_entered = asyncio.Event()
    subscriber_may_return = asyncio.Event()

    async def slow_model_request_started_subscriber(event) -> None:
        subscriber_entered.set()
        await subscriber_may_return.wait()

    bus.subscribe(ModelRequestStarted, slow_model_request_started_subscriber)

    orchestrator, backend, sound_cues = _orchestrator(bus=bus)
    tts_output = _RecordingTtsOutputForInterrupt()
    app = App(
        bus=bus,
        backend=backend,
        audio_input=None,
        tts_output=tts_output,
        capture_input=None,
        orchestrator=orchestrator,
        sound_cues=sound_cues,
        thinking_mode=None,
        response_mode=None,
        settings=Settings(vad=VadSettings(resume_cooldown_seconds=0.001)),
    )

    turn_task = asyncio.create_task(
        orchestrator.on_clipboard(
            ClipboardSubmitted(text="turn A", truncated=False, is_empty=False)
        )
    )
    await subscriber_entered.wait()  # deterministically inside the publish

    assert orchestrator._active_chat_task is None  # confirms the right window

    interrupted = await _cancel_current_turn(app)
    assert interrupted is True
    assert tts_output.cancel_calls == 1

    subscriber_may_return.set()
    await turn_task

    assert len(backend.calls) == 0  # the stale request must never dispatch
    assert orchestrator._active_chat_task is None


async def test_stale_dispatch_cleanup_does_not_erase_a_later_turns_active_task():
    """Regression (task-v1.7.0-3 review, fifth round): the round-4 fix
    returns from *inside* _dispatch_backend_request()'s `try`, so its
    `finally` still ran an unconditional `self._active_chat_task = None`.
    If turn B had already started - and stored its own backend task there -
    while turn A's ModelRequestStarted publish was still blocked, A's late
    return erased B's reference. B's backend request kept running, but a
    subsequent interrupt found _active_chat_task None and could not cancel
    it. The finally now clears the attribute only if it still holds the
    task this same dispatch created."""
    bus = EventBus()
    subscriber_entered = asyncio.Event()
    subscriber_may_return = asyncio.Event()
    release_b_chat = asyncio.Event()
    first_publish = True

    async def slow_first_model_request_started_subscriber(event) -> None:
        nonlocal first_publish
        if first_publish:
            first_publish = False
            subscriber_entered.set()
            await subscriber_may_return.wait()

    bus.subscribe(ModelRequestStarted, slow_first_model_request_started_subscriber)

    async def hanging_chat() -> None:
        # Only turn B's chat() ever runs (A's dispatch is skipped): it
        # hangs until cancelled by the second interrupt below.
        await release_b_chat.wait()

    orchestrator, backend, sound_cues = _orchestrator(bus=bus, chat_impl=hanging_chat)
    tts_output = _RecordingTtsOutputForInterrupt()
    app = App(
        bus=bus,
        backend=backend,
        audio_input=None,
        tts_output=tts_output,
        capture_input=None,
        orchestrator=orchestrator,
        sound_cues=sound_cues,
        thinking_mode=None,
        response_mode=None,
        settings=Settings(vad=VadSettings(resume_cooldown_seconds=0.001)),
    )

    turn_a_task = asyncio.create_task(
        orchestrator.on_clipboard(
            ClipboardSubmitted(text="turn A", truncated=False, is_empty=False)
        )
    )
    await subscriber_entered.wait()  # A is now inside its blocked publish

    interrupted = await _cancel_current_turn(app)
    assert interrupted is True

    # Turn B starts while A's publish is still blocked, and reaches its own
    # backend dispatch (its ModelRequestStarted publish is not delayed - the
    # subscriber only blocks the first one).
    turn_b_task = asyncio.create_task(
        orchestrator.on_clipboard(
            ClipboardSubmitted(text="turn B", truncated=False, is_empty=False)
        )
    )
    for _ in range(20):  # let B's dispatch reach its task creation
        if orchestrator._active_chat_task is not None:
            break
        await asyncio.sleep(0)
    b_chat_task = orchestrator._active_chat_task
    assert b_chat_task is not None  # B's backend request is in flight

    # A's blocked publish finally resolves; A's dispatch returns via the
    # round-4 check - its finally must NOT erase B's task reference.
    subscriber_may_return.set()
    await turn_a_task

    assert len(backend.calls) == 1  # only B's call - A never dispatched
    assert orchestrator._active_chat_task is b_chat_task  # B's task survived

    # And the interrupt still works against B - the whole point of keeping
    # the reference alive.
    interrupted_b = await _cancel_current_turn(app)
    assert interrupted_b is True
    await turn_b_task
    assert b_chat_task.cancelled()
    assert orchestrator.is_busy is False


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
    assert messages[-1] == {
        "role": "user",
        "content": VOICE_PLACEHOLDER_TEXT,
        "images": [base64.b64encode(b"a").decode()],
    }


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


@pytest.mark.parametrize(
    ("level", "field_name", "section"),
    [
        (ReasoningLevel.LOW, "reasoning_low", "reason briefly"),
        (ReasoningLevel.MEDIUM, "reasoning_medium", "compare alternatives"),
        (ReasoningLevel.HIGH, "reasoning_high", "verify conclusions"),
    ],
)
async def test_reasoning_turn_appends_the_active_section_after_memory_material(
    level, field_name, section
):
    thinking_mode = ReasoningLevelState(bus=EventBus())
    await thinking_mode.set_level(level, source="TEST")
    prompts = PromptSettings(**{field_name: section})
    orchestrator, backend, _sound_cues = _orchestrator(
        thinking_mode=thinking_mode,
        reasoning_prompt_settings=prompts,
    )
    orchestrator._system_prompt = "base prompt\n\nmemory material"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert backend.calls[-1][0][0] == {
        "role": "system",
        "content": f"base prompt\n\nmemory material\n\n{section}",
    }
    assert backend.reasoning_level_calls == [level]


async def test_off_turn_does_not_append_any_reasoning_prompt_section():
    prompts = PromptSettings(
        reasoning_low="low section",
        reasoning_medium="medium section",
        reasoning_high="high section",
    )
    thinking_mode = ReasoningLevelState(bus=EventBus())
    orchestrator, backend, _sound_cues = _orchestrator(
        thinking_mode=thinking_mode,
        reasoning_prompt_settings=prompts,
    )
    orchestrator._system_prompt = "base prompt\n\nmemory material"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert backend.calls[-1][0][0] == {
        "role": "system",
        "content": "base prompt\n\nmemory material",
    }


async def test_level_with_no_configured_section_uses_base_and_memory_only():
    thinking_mode = ReasoningLevelState(bus=EventBus())
    await thinking_mode.set_level(ReasoningLevel.MEDIUM, source="TEST")
    orchestrator, backend, _sound_cues = _orchestrator(
        thinking_mode=thinking_mode,
        reasoning_prompt_settings=PromptSettings(reasoning_low="low section"),
    )
    orchestrator._system_prompt = "base prompt\n\nmemory material"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert backend.calls[-1][0][0] == {
        "role": "system",
        "content": "base prompt\n\nmemory material",
    }
    assert backend.reasoning_level_calls == [ReasoningLevel.MEDIUM]


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
        chat_impl=slow_chat,
        thinking_mode=thinking_mode,
        reasoning_prompt_settings=PromptSettings(reasoning_low="low section"),
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
    assert backend.calls[0][0][0]["content"] == SYSTEM_PROMPT

    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1)
    )

    assert backend.reasoning_level_calls == [
        ReasoningLevel.OFF,
        ReasoningLevel.LOW,
    ]  # next accepted turn sees the new value
    assert backend.calls[1][0][0]["content"] == f"{SYSTEM_PROMPT}\n\nlow section"


async def test_start_turn_with_no_thinking_mode_defaults_to_off():
    """Orchestrator can be constructed without a thinking_mode (e.g. older
    tests/callers) - must not crash, and must behave as if reasoning is
    permanently off."""
    orchestrator, backend, _sound_cues = _orchestrator()

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert backend.reasoning_level_calls == [ReasoningLevel.OFF]


# --- response mode (story-v1.9.0, task 1) -----------------------------------
#
# Orchestrator samples ResponseModeState.mode at turn start - same seam and
# same "next accepted turn only" rule as ReasoningLevelState above. Mode 1
# (text) appends nothing, so the first pass stays byte-identical to today.
# Mode 2 (voice) selects the self-contained voice contract on its single
# pass. Mode 3 (text_voice)'s first pass is the canonical rich text, so it
# selects no field here at all, matching mode 1 - its own contract
# (response_text_voice) belongs to the second pass instead (story-v1.9.0
# task 3, see run_derivative_pass()'s own tests below, and app.py's
# _RESPONSE_MODE_PROMPT_FIELD_BY_MODE).


async def test_text_mode_turn_does_not_append_any_response_mode_contract():
    response_mode = ResponseModeState(bus=EventBus())
    orchestrator, backend, _sound_cues = _orchestrator(response_mode=response_mode)
    orchestrator._system_prompt = "base prompt"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert backend.calls[-1][0][0] == {"role": "system", "content": "base prompt"}


async def test_voice_mode_appends_the_voice_contract():
    response_mode = ResponseModeState(bus=EventBus(), initial_mode=ResponseMode.VOICE)
    prompts = PromptSettings(response_voice="speak plainly")
    orchestrator, backend, _sound_cues = _orchestrator(
        response_mode=response_mode, reasoning_prompt_settings=prompts
    )
    orchestrator._system_prompt = "base prompt"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert backend.calls[-1][0][0] == {
        "role": "system",
        "content": "base prompt\n\nspeak plainly",
    }


async def test_text_voice_modes_first_pass_uses_the_base_prompt_only():
    """Mode 3's first pass is the canonical rich text (story-v1.9.0 task 3):
    it composes exactly like mode 1, never the voice contract - the
    response_text_voice field is reserved for the second pass, dispatched
    separately from _compose_response_mode_contract() entirely (see the
    mode-3 second-pass tests below)."""
    response_mode = ResponseModeState(
        bus=EventBus(), initial_mode=ResponseMode.TEXT_VOICE
    )
    prompts = PromptSettings(
        response_voice="voice contract", response_text_voice="derivative contract"
    )
    orchestrator, backend, _sound_cues = _orchestrator(
        response_mode=response_mode, reasoning_prompt_settings=prompts
    )
    orchestrator._system_prompt = "base prompt"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert backend.calls[-1][0][0] == {"role": "system", "content": "base prompt"}


async def test_reasoning_section_and_response_mode_contract_compose_together():
    thinking_mode = ReasoningLevelState(bus=EventBus())
    await thinking_mode.set_level(ReasoningLevel.LOW, source="TEST")
    response_mode = ResponseModeState(bus=EventBus(), initial_mode=ResponseMode.VOICE)
    prompts = PromptSettings(
        reasoning_low="reason briefly", response_voice="speak plainly"
    )
    orchestrator, backend, _sound_cues = _orchestrator(
        thinking_mode=thinking_mode,
        response_mode=response_mode,
        reasoning_prompt_settings=prompts,
    )
    orchestrator._system_prompt = "base prompt"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert backend.calls[-1][0][0] == {
        "role": "system",
        "content": "base prompt\n\nreason briefly\n\nspeak plainly",
    }


async def test_start_turn_with_no_response_mode_defaults_to_text():
    """Orchestrator can be constructed without a response_mode (e.g. older
    tests/callers) - must not crash, and must behave as text mode (append
    nothing)."""
    orchestrator, backend, _sound_cues = _orchestrator()
    orchestrator._system_prompt = "base prompt"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert backend.calls[-1][0][0] == {"role": "system", "content": "base prompt"}


# --- mode 3 second pass (story-v1.9.0 task 3) -------------------------------


def _text_voice_orchestrator(*, chat_impl, journal_recorder=None, response_mode=None):
    prompts = PromptSettings(response_text_voice="derivative contract")
    mode_state = response_mode or ResponseModeState(
        bus=EventBus(), initial_mode=ResponseMode.TEXT_VOICE
    )
    orchestrator, backend, sound_cues = _orchestrator(
        chat_impl=chat_impl,
        response_mode=mode_state,
        reasoning_prompt_settings=prompts,
        journal_recorder=journal_recorder,
    )
    orchestrator._system_prompt = "base prompt"
    return orchestrator, backend, sound_cues


async def test_first_pass_defers_the_journal_write_and_flags_a_pending_derivative():
    """Orchestrator.on_response_complete() (mode 3): the derivative does not
    exist yet at this point, so the journal write must wait - see
    run_derivative_pass()'s own tests below for the actual write."""

    async def chat_impl() -> None:
        await orchestrator.on_response_token(ResponseToken(text="canonical reply"))

    journal_recorder = _FakeJournalRecorder()
    orchestrator, _backend, _sound_cues = _text_voice_orchestrator(
        chat_impl=chat_impl, journal_recorder=journal_recorder
    )

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    # not set until on_response_complete
    assert orchestrator.needs_derivative_pass() is False
    await orchestrator.on_response_complete(_complete_event())

    assert orchestrator.needs_derivative_pass() is True
    assert journal_recorder.assistant_texts == []  # deferred, not skipped


async def test_modes_1_and_2_never_defer_the_journal_write():
    async def chat_impl() -> None:
        await orchestrator.on_response_token(ResponseToken(text="reply"))

    journal_recorder = _FakeJournalRecorder()
    voice_mode = ResponseModeState(bus=EventBus(), initial_mode=ResponseMode.VOICE)
    orchestrator, _backend, _sound_cues = _orchestrator(
        chat_impl=chat_impl,
        response_mode=voice_mode,
        journal_recorder=journal_recorder,
    )
    orchestrator._system_prompt = "base prompt"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    await orchestrator.on_response_complete(_complete_event())

    assert orchestrator.needs_derivative_pass() is False
    assert journal_recorder.assistant_texts == ["reply"]


async def test_derivative_pass_dispatches_reasoning_off_over_the_exact_shown_text():
    async def chat_impl() -> None:
        if len(backend.calls) == 1:
            await orchestrator.on_response_token(ResponseToken(text="canonical reply"))
        else:
            await orchestrator.on_response_token(ResponseToken(text="derivative reply"))

    orchestrator, backend, _sound_cues = _text_voice_orchestrator(chat_impl=chat_impl)

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.run_derivative_pass()

    assert len(backend.calls) == 2
    messages, images = backend.calls[1]
    assert messages == [
        {"role": "system", "content": "derivative contract"},
        {"role": "user", "content": "canonical reply"},
    ]
    assert images is None
    assert backend.reasoning_level_calls[1] is ReasoningLevel.OFF
    assert orchestrator.needs_derivative_pass() is False


async def test_derivative_pass_records_both_texts_in_the_same_journal_event():
    """Additive, one event, not a second turn (story-v1.9.0 task 3's own
    append-only requirement)."""

    async def chat_impl() -> None:
        if len(backend.calls) == 1:
            await orchestrator.on_response_token(ResponseToken(text="canonical reply"))
        else:
            await orchestrator.on_response_token(ResponseToken(text="derivative reply"))

    journal_recorder = _FakeJournalRecorder()
    orchestrator, backend, _sound_cues = _text_voice_orchestrator(
        chat_impl=chat_impl, journal_recorder=journal_recorder
    )

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.run_derivative_pass()

    assert journal_recorder.assistant_texts == ["canonical reply"]
    assert journal_recorder.assistant_spoken_derivatives == ["derivative reply"]


async def test_derivative_pass_speaks_even_though_the_first_pass_was_muted():
    async def chat_impl() -> None:
        if len(backend.calls) == 1:
            await orchestrator.on_response_token(ResponseToken(text="canonical"))
        else:
            await orchestrator.on_response_token(ResponseToken(text="derivative"))

    orchestrator, backend, sound_cues = _text_voice_orchestrator(chat_impl=chat_impl)

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    # Mode 3's muted first pass: no speaking cue, matching TtsOutput's own
    # mute of this pass - neither should announce audio that never plays.
    assert sound_cues.played == ["thinking"]
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.run_derivative_pass()

    assert "speaking" in sound_cues.played


async def test_derivative_pass_with_no_response_text_voice_uses_an_empty_prompt():
    """response_text_voice is None means "not configured" (same optional-
    field shape as response_voice) - the dispatch must not crash, and must
    still send the exact shown text as the user message."""

    async def chat_impl() -> None:
        if len(backend.calls) == 1:
            await orchestrator.on_response_token(ResponseToken(text="canonical reply"))

    mode_state = ResponseModeState(bus=EventBus(), initial_mode=ResponseMode.TEXT_VOICE)
    orchestrator, backend, _sound_cues = _orchestrator(
        chat_impl=chat_impl,
        response_mode=mode_state,
        reasoning_prompt_settings=PromptSettings(response_text_voice=None),
    )
    orchestrator._system_prompt = "base prompt"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.run_derivative_pass()

    messages, _images = backend.calls[1]
    assert messages == [
        {"role": "system", "content": ""},
        {"role": "user", "content": "canonical reply"},
    ]


async def test_interrupted_derivative_pass_flags_only_the_derivative_as_cut_short():
    """Bug report tasks/bug_reports/2026-08-30-mode3-derivative-pass-
    backend-failure-races-turn-teardown.md: _dispatch_backend_request()
    swallows the derivative dispatch's CancelledError and returns quietly
    (its own "this turn is over" contract, written for a single-pass turn
    where cancellation cleanup is someone else's job), so run_derivative_
    pass() must check interrupt_requested itself afterwards.

    The journaled outcome must NOT reuse TurnOutcome.INTERRUPTED here: that
    field describes `text` (the turn's own answer), which is complete -
    only the derivative rendering was cut short. A dedicated flag next to
    spoken_derivative keeps that distinction instead of making every
    consumer that does not know to check a second field misreport a
    complete answer as unfinished."""
    still_busy = asyncio.Event()

    async def chat_impl() -> None:
        if len(backend.calls) == 1:
            await orchestrator.on_response_token(ResponseToken(text="canonical reply"))
            return
        await orchestrator.on_response_token(ResponseToken(text="half deriv"))
        await still_busy.wait()

    journal_recorder = _FakeJournalRecorder()
    orchestrator, backend, _sound_cues = _text_voice_orchestrator(
        chat_impl=chat_impl, journal_recorder=journal_recorder
    )

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    await orchestrator.on_response_complete(_complete_event())

    derivative_task = asyncio.create_task(orchestrator.run_derivative_pass())
    await asyncio.sleep(0)
    await asyncio.sleep(0)  # let the derivative pass's own chat() start

    orchestrator.cancel_active_turn()
    await derivative_task

    assert journal_recorder.assistant_texts == ["canonical reply"]
    assert journal_recorder.assistant_spoken_derivatives == ["half deriv"]
    assert journal_recorder.assistant_spoken_derivative_interrupted == [True]
    # The canonical reply is complete - only the derivative was cut short.
    assert journal_recorder.assistant_outcomes == [None]


async def test_uninterrupted_derivative_pass_does_not_set_the_interrupted_flag():
    async def chat_impl() -> None:
        if len(backend.calls) == 1:
            await orchestrator.on_response_token(ResponseToken(text="canonical reply"))
        else:
            await orchestrator.on_response_token(ResponseToken(text="derivative reply"))

    journal_recorder = _FakeJournalRecorder()
    orchestrator, backend, _sound_cues = _text_voice_orchestrator(
        chat_impl=chat_impl, journal_recorder=journal_recorder
    )

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.run_derivative_pass()

    assert journal_recorder.assistant_spoken_derivative_interrupted == [False]
    assert journal_recorder.assistant_outcomes == [None]


async def test_derivative_pass_backend_failure_does_not_clear_busy_early():
    """Bug report tasks/bug_reports/2026-08-30-mode3-derivative-pass-
    backend-failure-races-turn-teardown.md: _dispatch_backend_request()'s
    except-Exception branch used to clear self._busy unconditionally, even
    when claim_turn_end() had already been lost - which it always is here,
    since _on_full_response_complete() (app.py) claims the turn once, before
    ever calling run_derivative_pass(). Only the winner of that claim may
    clear busy (claim_turn_end()'s own contract - see finish_turn()); a real
    (non-cancellation) exception on the derivative dispatch must leave it
    alone and let the outer call's own finally/finish_turn() do it once
    teardown actually finishes."""

    async def chat_impl() -> None:
        if len(backend.calls) == 1:
            await orchestrator.on_response_token(ResponseToken(text="canonical reply"))
            return
        raise RuntimeError("derivative backend call failed")

    orchestrator, backend, sound_cues = _text_voice_orchestrator(chat_impl=chat_impl)

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    await orchestrator.on_response_complete(_complete_event())
    # Mirrors _on_full_response_complete()'s own claim, taken before it ever
    # calls run_derivative_pass() - the turn's one claim is already spent by
    # the time the derivative dispatch below fails.
    assert orchestrator.claim_turn_end() is True

    await orchestrator.run_derivative_pass()

    assert orchestrator.is_busy is True
    assert sound_cues.played[-1] == "error"


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
    capture_failed = False

    async def stop(self) -> None:
        return None


class _FakeTtsOutput:
    def __init__(self) -> None:
        self.cancel_calls = 0

    async def on_request_started(self, event) -> None:
        pass

    async def on_token(self, event) -> None:
        pass

    async def on_response_complete(self, event) -> None:
        pass

    async def wait_for_pending(self) -> None:
        return None

    def cancel(self) -> None:
        self.cancel_calls += 1


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

    def set_mcp_state(self, state: dict) -> None:
        self.calls.append(("mcp", state))

    def set_thinking_mode(self, level: ReasoningLevel) -> None:
        self.calls.append(("thinking", level))

    def set_response_mode(self, mode: ResponseMode) -> None:
        self.calls.append(("response_mode", mode))

    def set_visibility_mode(self, mode: VisibilityMode) -> None:
        self.calls.append(("visibility", mode))

    def set_module_health(self, health: ModuleHealth) -> None:
        self.calls.append(("module", health))

    def set_runtime_state(
        self, state: RuntimeState, substatus: str | None = None
    ) -> None:
        self.calls.append(("runtime", (state, substatus)))


def _settings() -> Settings:
    return Settings(journal=JournalSettings(enabled=False))


def _collecting_subscriber(items: list) -> Callable:
    """bus.py awaits every handler, so a plain list.append cannot be
    subscribed directly (it isn't a coroutine function) - wrap it."""

    async def on_event(event) -> None:
        items.append(event)

    return on_event


def _fake_app(bus: EventBus | None = None) -> App:
    """build_app() with fakes for every hardware-touching module, plus a
    fake backend so a bug in unwire()/shutdown can never trigger a real
    network call - not just "shouldn't happen if the code is correct"."""
    return build_app(
        _settings(),
        bus=bus,
        backend=_FakeBackend(),
        audio_input=_FakeAudioInput(),
        tts_output=_FakeTtsOutput(),
        capture_input=_FakeCaptureInput(),
    )


def test_wire_registers_expected_subscriptions():
    app = _fake_app()

    subscriptions = wire(app)
    event_types = [event_type for event_type, _handler in subscriptions]

    # Two: the orchestrator's own turn handling, plus the debug-transcript
    # metrics bridge (on_utterance_captured), which is unconditional and
    # a no-op unless debug is on.
    assert event_types.count(UtteranceChunk) == 2
    assert event_types.count(ScreenshotCaptured) == 1
    assert event_types.count(ClipboardSubmitted) == 1
    assert event_types.count(ResponseToken) == 2  # tts_output + orchestrator
    # A single coordinating handler, not three concurrent subscribers -
    # see _on_full_response_complete's docstring for why that mattered.
    assert event_types.count(ResponseComplete) == 1
    assert event_types.count(MicSleepToggled) == 1
    assert event_types.count(ReasoningLevelChanged) == 1
    assert event_types.count(ResponseModeChanged) == 1
    assert event_types.count(InterruptRequested) == 1
    assert event_types.count(TtsSpeechEnabledChanged) == 1

    handlers = [handler for _event_type, handler in subscriptions]
    assert app.orchestrator.on_utterance in handlers
    assert on_utterance_captured in handlers
    assert app.orchestrator.on_screenshot in handlers
    assert app.orchestrator.on_clipboard in handlers


async def test_muting_tts_cancels_in_flight_speech_but_unmuting_does_not():
    app = _fake_app()
    wire(app)

    await app.bus.publish(
        TtsSpeechEnabledChanged, TtsSpeechEnabledChanged(enabled=False)
    )
    await app.bus.publish(
        TtsSpeechEnabledChanged, TtsSpeechEnabledChanged(enabled=True)
    )

    assert app.tts_output.cancel_calls == 1


def test_build_app_seeds_tts_mute_state_from_settings():
    settings = Settings(
        journal=JournalSettings(enabled=False), tts=TtsSettings(enabled=False)
    )

    app = build_app(settings, backend=_FakeBackend(), tts_output=_FakeTtsOutput())

    assert app.tts_mute_state is not None
    assert app.tts_mute_state.enabled is False


def test_build_app_wires_one_shared_solo_session_state():
    settings = Settings(journal=JournalSettings(enabled=False))

    app = build_app(settings, backend=_FakeBackend(), tts_output=_FakeTtsOutput())

    assert app.solo_session_state is not None
    assert app.solo_session_state.enabled is False
    # Same object reaches the Orchestrator - toggling app.solo_session_state
    # actually changes what the running orchestrator sees, not a copy.
    assert app.orchestrator._solo_session_state is app.solo_session_state


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


def _builtin_tool_payloads(app: App) -> list[dict[str, object]]:
    """Descriptions are read from the app's own registry rather than
    pinned here: the tooltip shows whatever the model-facing text happens
    to be, and pinning the prose would turn an assertion about plumbing
    into an assertion about wording (task-tool-rows-name-capabilities)."""

    def description(name: str) -> str:
        assert app.mcp_host is not None
        tool = app.mcp_host.registry.get(name)
        assert tool is not None
        return tool.description

    return [
        {
            "name": "capture_camera_image",
            "provider": "builtin",
            "provider_kind": "builtin",
            "enabled": False,
            "available": True,
            "description": description("capture_camera_image"),
        },
        {
            "name": "list_session_files",
            "provider": "builtin",
            "provider_kind": "builtin",
            "enabled": True,
            "available": True,
            "description": description("list_session_files"),
        },
        {
            "name": "read_history",
            "provider": "history",
            "provider_kind": "builtin",
            "enabled": True,
            "available": True,
            "description": description("read_history"),
        },
        {
            "name": "read_history_ranges",
            "provider": "history",
            "provider_kind": "builtin",
            "enabled": True,
            "available": True,
            "description": description("read_history_ranges"),
        },
        {
            "name": "read_session_text",
            "provider": "builtin",
            "provider_kind": "builtin",
            "enabled": True,
            "available": True,
            "description": description("read_session_text"),
        },
        {
            "name": "remember",
            "provider": "builtin",
            "provider_kind": "builtin",
            "enabled": True,
            "available": True,
            "description": description("remember"),
        },
        {
            "name": "search_history",
            "provider": "history",
            "provider_kind": "builtin",
            "enabled": True,
            "available": True,
            "description": description("search_history"),
        },
        {
            "name": "set_reasoning_level",
            "provider": "builtin",
            "provider_kind": "builtin",
            "enabled": True,
            "available": True,
            "description": description("set_reasoning_level"),
        },
        {
            "name": "stat_session_file",
            "provider": "builtin",
            "provider_kind": "builtin",
            "enabled": True,
            "available": True,
            "description": description("stat_session_file"),
        },
        {
            "name": "view_session_image",
            "provider": "builtin",
            "provider_kind": "builtin",
            "enabled": True,
            "available": True,
            "description": description("view_session_image"),
        },
        {
            "name": "write_session_file",
            "provider": "builtin",
            "provider_kind": "builtin",
            "enabled": True,
            "available": True,
            "description": description("write_session_file"),
        },
    ]


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
        (
            "mcp",
            {
                "status": "off",
                "enabled": False,
                "tools": [],
                "local_tools": _builtin_tool_payloads(app),
            },
        ),
        ("thinking", ReasoningLevel.OFF),
        ("response_mode", ResponseMode.TEXT),
        ("visibility", VisibilityMode.OPEN),
        (
            "module",
            ModuleHealth(
                module=ModuleId.MICROPHONE, status=HealthStatus.OK, detail="listening"
            ),
        ),
        (
            "module",
            ModuleHealth(
                module=ModuleId.CAMERA,
                status=HealthStatus.UNAVAILABLE,
                detail="privacy off",
            ),
        ),
        (
            "module",
            ModuleHealth(
                module=ModuleId.TTS, status=HealthStatus.OK, detail="speaking"
            ),
        ),
    ]

    unwire(app, subscriptions)


@pytest.mark.asyncio
async def test_wire_status_console_projects_authoritative_mcp_status_changes():
    app = _fake_app()
    live_console = create_live_status_console(app, include_touchstrip=False)
    transport = _FakeTransport()
    live_console.transport = transport
    subscriptions = wire_status_console(app, live_console, asyncio.get_running_loop())

    await app.bus.publish(
        McpModuleStatusChanged,
        McpModuleStatusChanged(status=McpModuleStatus.CONNECTING),
    )

    assert transport.calls[-1] == (
        "mcp",
        {
            "status": "connecting",
            "enabled": False,
            "tools": [],
            "local_tools": _builtin_tool_payloads(app),
        },
    )
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

    # Only the nine snapshot seeds: mic-toggle projection belongs to the
    # real transport server's own bus subscription, not to this wiring.
    assert len(transport.calls) == 9
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

    # A real ResponseComplete only ever fires for a turn that set busy
    # (task-v1.7.0-2's claim_turn_end() requires it - see review finding
    # 1); publishing it without one is not a scenario this handler needs
    # to support. Setting busy directly, not via on_utterance(): this
    # test's _FakeBackend has no iter_chat() (build_app() wraps it in
    # ToolAwareDialog, which needs it), so a real turn would just fail.
    app.orchestrator._busy = True
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


def test_status_console_creates_windows_before_starting_pywebview(monkeypatch):
    journal_store = object()
    journal_search_index = object()
    journal_history_service = object()
    fake_app = types.SimpleNamespace(
        bus=EventBus(),
        thinking_mode=types.SimpleNamespace(level=ReasoningLevel.OFF),
        response_mode=types.SimpleNamespace(mode=ResponseMode.TEXT),
        visibility_mode=types.SimpleNamespace(mode=VisibilityMode.OPEN),
        tts_mute_state=None,
        solo_session_state=None,
        orchestrator=types.SimpleNamespace(
            submit_text_input=object(),
            on_attachment_submission=object(),
            start_new_context=object(),
            fork_from_journal_session=object(),
        ),
        journal_recorder=types.SimpleNamespace(session_id=None),
        journal_store=journal_store,
        journal_search_index=journal_search_index,
        history_projection_lifecycle=None,
        journal_history_service=journal_history_service,
        transcript_overlay_repository=object(),
        transcription_service=object(),
        annotation_overlay_repository=object(),
        annotation_generation_service=object(),
        consolidation_planner=object(),
        consolidation_executor=object(),
        memory_file_repository=object(),
    )

    class _FakeTransportServer:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def start(self) -> object:
            return object()

    fake_live_console = types.SimpleNamespace(
        api=object(),
        transport=None,
        windows_created=False,
        load_transport_urls=lambda info: None,
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
    monkeypatch.setattr(main_module, "UiTransportServer", _FakeTransportServer)

    async def fake_run(settings=None, app=None, live_console=None, debug=False) -> None:
        del settings, app, live_console

    monkeypatch.setattr(main_module, "run", fake_run)

    def start(callback) -> None:
        assert fake_live_console.windows_created is True
        # The real pywebview always runs its func argument; a fake that
        # never does would deadlock the engine-completion future
        # run_with_status_console() now blocks on.
        callback()

    monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace(start=start))

    main_module.run_with_status_console(settings=Settings(), include_touchstrip=False)


def test_status_console_transport_receives_journal_read_services(monkeypatch):
    app = _fake_app()
    captured_kwargs = {}

    class _FakeUiTransportServer:
        def __init__(self, *args, **kwargs) -> None:
            del args
            captured_kwargs.update(kwargs)

        async def start(self) -> object:
            return object()

    fake_live_console = types.SimpleNamespace(
        api=object(),
        transport=None,
        create_windows=lambda: None,
        load_transport_urls=lambda info: None,
    )
    monkeypatch.setattr(main_module, "build_app", lambda settings: app)
    monkeypatch.setattr(
        main_module,
        "create_live_status_console",
        lambda app, include_touchstrip: fake_live_console,
    )
    monkeypatch.setattr(main_module, "UiTransportServer", _FakeUiTransportServer)

    async def fake_run(settings=None, app=None, live_console=None, debug=False) -> None:
        del settings, app, live_console

    monkeypatch.setattr(main_module, "run", fake_run)
    # The real pywebview always runs its func argument; a fake that never
    # does would deadlock the engine-completion future.
    monkeypatch.setitem(
        sys.modules,
        "webview",
        types.SimpleNamespace(start=lambda callback: callback()),
    )

    main_module.run_with_status_console(settings=Settings(), include_touchstrip=False)

    assert captured_kwargs["journal_history_service"] is app.journal_history_service


def test_status_console_starts_history_lifecycle_before_transport(monkeypatch):
    app = _fake_app()
    calls: list[str] = []

    class _FakeLifecycle:
        def __init__(self) -> None:
            self.start_calls = 0
            self.started = False

        async def start(self) -> None:
            self.start_calls += 1
            if self.started:
                return
            self.started = True
            calls.append("lifecycle")

    class _FakeUiTransportServer:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def start(self) -> object:
            calls.append("transport")
            return object()

    lifecycle = _FakeLifecycle()
    app.history_projection_lifecycle = lifecycle
    fake_live_console = types.SimpleNamespace(
        api=object(),
        transport=None,
        create_windows=lambda: None,
        load_transport_urls=lambda info: None,
    )
    monkeypatch.setattr(main_module, "build_app", lambda settings: app)
    monkeypatch.setattr(
        main_module,
        "create_live_status_console",
        lambda app, include_touchstrip: fake_live_console,
    )
    monkeypatch.setattr(main_module, "UiTransportServer", _FakeUiTransportServer)

    async def fake_run(settings=None, app=None, live_console=None, debug=False) -> None:
        del settings, live_console
        await main_module._start_history_projection_lifecycle(app)
        calls.append("run")

    monkeypatch.setattr(main_module, "run", fake_run)
    monkeypatch.setitem(
        sys.modules,
        "webview",
        types.SimpleNamespace(start=lambda callback: callback()),
    )

    main_module.run_with_status_console(settings=Settings(), include_touchstrip=False)

    assert calls == ["lifecycle", "transport", "run"]
    assert lifecycle.start_calls == 2


def _patch_status_console_composition(monkeypatch, app, fake_run) -> None:
    """Shared fixture shape for run_with_status_console() lifecycle tests:
    fake every collaborator except the engine-completion contract under
    test."""

    class _FakeTransportServer:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def start(self) -> object:
            return object()

    fake_live_console = types.SimpleNamespace(
        api=object(),
        transport=None,
        create_windows=lambda: None,
        load_transport_urls=lambda info: None,
    )
    monkeypatch.setattr(main_module, "build_app", lambda settings: app)
    monkeypatch.setattr(
        main_module,
        "create_live_status_console",
        lambda app, include_touchstrip: fake_live_console,
    )
    monkeypatch.setattr(main_module, "UiTransportServer", _FakeTransportServer)
    monkeypatch.setattr(main_module, "run", fake_run)


def test_run_with_status_console_waits_for_a_delayed_engine_callback(monkeypatch):
    """pywebview's start() runs its func in a plain thread it never joins
    (verified against pywebview 6.2.1 source), and can return - GUI loop
    over - before that thread has even been scheduled. Returning to
    main() at that point starts interpreter shutdown that races the
    engine teardown (the shutdown executor-race bug report's root cause).
    run_with_status_console() must block on the engine's own completion,
    not on thread bookkeeping."""
    app = _fake_app()
    engine_finished = threading.Event()

    async def fake_run(settings=None, app=None, live_console=None, debug=False) -> None:
        del settings, app, live_console
        await asyncio.sleep(0.05)
        engine_finished.set()

    _patch_status_console_composition(monkeypatch, app, fake_run)

    def gui_start_without_join(callback) -> None:
        def delayed_callback() -> None:
            # The callback has not even started when start() returns.
            time.sleep(0.15)
            callback()

        threading.Thread(target=delayed_callback).start()

    monkeypatch.setitem(
        sys.modules, "webview", types.SimpleNamespace(start=gui_start_without_join)
    )

    main_module.run_with_status_console(settings=Settings(), include_touchstrip=False)

    assert engine_finished.is_set()


def test_run_with_status_console_reraises_an_engine_callback_failure(monkeypatch):
    """An exception that kills the engine must reach
    run_with_status_console()'s caller, not die silently in pywebview's
    unjoined thread."""
    app = _fake_app()

    async def failing_run(
        settings=None, app=None, live_console=None, debug=False
    ) -> None:
        del settings, app, live_console
        raise RuntimeError("engine exploded")

    _patch_status_console_composition(monkeypatch, app, failing_run)

    def gui_start_without_join(callback) -> None:
        threading.Thread(target=callback).start()

    monkeypatch.setitem(
        sys.modules, "webview", types.SimpleNamespace(start=gui_start_without_join)
    )

    with pytest.raises(RuntimeError, match="engine exploded"):
        main_module.run_with_status_console(
            settings=Settings(), include_touchstrip=False
        )


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


async def test_run_until_shutdown_with_a_real_microphone_loop_exits_cleanly(caplog):
    """The reported failure shape at the pure level: a real AudioInput
    parked in a blocked executor read enters the standard shutdown
    sequence. stop() must see the loop (and its read worker) actually
    finish, and the shutdown gather must log no task failure."""

    class _NoSpeechChunker:
        settings = types.SimpleNamespace(request_end_pause_seconds=2.0)

        def chunk(self, samples):
            return []

    class _BlockedDrainingStream:
        def __init__(self) -> None:
            self._stopped = threading.Event()
            self._waiting = threading.Event()

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def read(self, block_samples):
            self._waiting.set()
            self._stopped.wait()
            time.sleep(0.05)  # slow drain after the stream stop
            return np.zeros((block_samples, 1), dtype=np.float32), False

        def stop(self) -> None:
            self._stopped.set()

        def start(self) -> None:
            raise AssertionError("shutdown must not restart the stream")

    stream = _BlockedDrainingStream()
    audio_input = AudioInput(
        bus=EventBus(), chunker=_NoSpeechChunker(), stream_factory=lambda bs: stream
    )
    app = build_app(
        _settings(),
        backend=_FakeBackend(),
        audio_input=audio_input,
        tts_output=_FakeTtsOutput(),
        capture_input=_FakeCaptureInput(),
    )
    subscriptions = wire(app)
    shutdown_event = asyncio.Event()
    mic_task = asyncio.create_task(audio_input.run_microphone_loop())
    await asyncio.to_thread(stream._waiting.wait, 2.0)

    shutdown_event.set()
    with caplog.at_level(logging.ERROR):
        await asyncio.wait_for(
            run_until_shutdown(app, subscriptions, shutdown_event, [mic_task]),
            timeout=5,
        )

    assert mic_task.done()
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


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
    task-13's thinking-mode, task-v1.7.0-2's interrupt) instead of
    arbitrary fake tasks - confirms run()'s pattern of handing these to
    run_until_shutdown actually cancels them and stops each provider
    during cleanup."""
    app = _fake_app()
    subscriptions = wire(app)
    shutdown_event = asyncio.Event()

    fake_kb_clipboard = _FakeKeyboardModuleForShutdownTest()
    fake_kb_mic_sleep = _FakeKeyboardModuleForShutdownTest()
    fake_kb_thinking = _FakeKeyboardModuleForShutdownTest()
    fake_kb_interrupt = _FakeKeyboardModuleForShutdownTest()
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
        asyncio.create_task(
            run_interrupt_hotkey_listener(
                app.bus, app.settings.hotkeys, provider=fake_kb_interrupt
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
    assert len(fake_kb_interrupt.removed_handles) == 1
    assert len(fake_kb_thinking.removed_handles) == 1


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


# --- ResponseComplete ordering (review finding) -----------------------------


class _OrderingTts:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self._task: asyncio.Task | None = None

    async def on_response_complete(self, event) -> None:
        self._events.append("trailing_sentence_scheduled")
        self._task = asyncio.create_task(self._delayed_finish())

    async def _delayed_finish(self) -> None:
        await asyncio.sleep(0)  # yield once, like real synthesis would
        self._events.append("trailing_speech_finished")

    async def wait_for_pending(self) -> None:
        if self._task is not None:
            await self._task


class _OrderingOrchestrator:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def claim_turn_end(self) -> bool:
        return True

    async def on_response_complete(self, event) -> None:
        self._events.append("history_recorded")

    def needs_derivative_pass(self) -> bool:
        return False

    async def finish_turn(self, cooldown_seconds: float = 0.0) -> None:
        self._events.append("busy_cleared")


class _OrderingSoundCues:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def play(self, cue: str) -> None:
        self._events.append(f"cue:{cue}")


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

    app = App(
        bus=EventBus(),
        backend=None,
        audio_input=None,
        tts_output=_OrderingTts(events),
        capture_input=None,
        orchestrator=_OrderingOrchestrator(events),
        sound_cues=_OrderingSoundCues(events),
        thinking_mode=None,
        response_mode=None,
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


async def test_on_full_response_complete_runs_the_derivative_pass_before_finishing():
    """Mode 3 (story-v1.9.0 task 3): when the orchestrator flags a pending
    derivative pass, _on_full_response_complete() must run it - and flush
    its own trailing sentence - before wait_for_pending()/finish_turn()/
    TurnCompleted, not after. The claim is still held from the top of this
    same call, so nothing else can race finishing this turn in the gap."""
    events: list[str] = []

    class _FakeTtsForDerivative:
        async def on_response_complete(self, event) -> None:
            events.append("tts_flush")

        async def wait_for_pending(self) -> None:
            events.append("tts_wait_for_pending")

    class _FakeOrchestratorForDerivative:
        def claim_turn_end(self) -> bool:
            return True

        async def on_response_complete(self, event) -> None:
            events.append("history_recorded")

        def needs_derivative_pass(self) -> bool:
            # Only True the first time - run_derivative_pass() itself
            # clears the flag once it has run, mirroring the real
            # Orchestrator's own contract.
            return not events.count("derivative_pass_run")

        async def run_derivative_pass(self) -> None:
            events.append("derivative_pass_run")

        async def finish_turn(self, cooldown_seconds: float = 0.0) -> None:
            events.append("busy_cleared")

    class _FakeSoundCuesForDerivative:
        async def play(self, cue: str) -> None:
            events.append(f"cue:{cue}")

    app = App(
        bus=EventBus(),
        backend=None,
        audio_input=None,
        tts_output=_FakeTtsForDerivative(),
        capture_input=None,
        orchestrator=_FakeOrchestratorForDerivative(),
        sound_cues=_FakeSoundCuesForDerivative(),
        thinking_mode=None,
        response_mode=None,
        settings=_settings(),
    )

    await _on_full_response_complete(app, _complete_event())

    assert events == [
        "tts_flush",  # pass 1's own (muted) trailing sentence
        "history_recorded",
        "derivative_pass_run",
        "tts_flush",  # pass 2's trailing sentence
        "tts_wait_for_pending",
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
        response_mode=None,
        # negligible cooldown - keeps this test fast; the real default
        # (1.0 s) is exercised by design, not by this test's timing
        settings=Settings(vad=VadSettings(resume_cooldown_seconds=0.001)),
    )

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    await _on_full_response_complete(app, _complete_event())

    assert sound_cues.played[-1] == "error"
    # task-v1.7.0-3 review guard: on_response_complete() already recorded
    # this turn normally (inside the try block) before wait_for_pending()
    # failed - record_aborted_turn() must NOT also run here, or this turn
    # would be recorded twice.
    assert orchestrator._history.as_messages() == [
        {"role": "user", "content": VOICE_PLACEHOLDER_TEXT},
        {"role": "assistant", "content": ""},
    ]

    # busy was cleared despite the failure - a subsequent utterance is not ignored
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1)
    )
    assert len(backend.calls) == 2


# --- _on_interrupt_requested (task-v1.7.0-2 interrupt hotkey) ---------------


class _RecordingTtsOutputForInterrupt:
    def __init__(self) -> None:
        self.cancel_calls = 0

    def cancel(self) -> None:
        self.cancel_calls += 1


def _app_for_interrupt_test(orchestrator, backend, sound_cues, tts_output) -> App:
    return App(
        bus=EventBus(),
        backend=backend,
        audio_input=None,
        tts_output=tts_output,
        capture_input=None,
        orchestrator=orchestrator,
        sound_cues=sound_cues,
        thinking_mode=None,
        response_mode=None,
        settings=Settings(vad=VadSettings(resume_cooldown_seconds=0.001)),
    )


async def test_interrupt_while_idle_is_a_no_op():
    orchestrator, backend, sound_cues = _orchestrator()
    tts_output = _RecordingTtsOutputForInterrupt()
    app = _app_for_interrupt_test(orchestrator, backend, sound_cues, tts_output)

    await _on_interrupt_requested(app, InterruptRequested())

    assert tts_output.cancel_calls == 0
    assert sound_cues.played == []
    assert orchestrator.is_busy is False


async def test_interrupt_while_busy_cancels_tts_and_backend_and_resumes_listening():
    still_busy = asyncio.Event()

    async def hanging_chat() -> None:
        # Only the first (interrupted) call should ever actually wait
        # here - by the second call below, still_busy is already set, so
        # this returns immediately like a normal, uneventful turn.
        await still_busy.wait()

    orchestrator, backend, sound_cues = _orchestrator(chat_impl=hanging_chat)
    tts_output = _RecordingTtsOutputForInterrupt()
    app = _app_for_interrupt_test(orchestrator, backend, sound_cues, tts_output)

    turn_task = asyncio.create_task(
        orchestrator.on_utterance(
            UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
        )
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)  # let chat() actually start (task-v1.7.0-2 timing)

    await _on_interrupt_requested(app, InterruptRequested())
    await turn_task  # _start_turn() returns quietly on cancellation

    assert tts_output.cancel_calls == 1
    assert orchestrator.is_busy is False
    assert sound_cues.played[-1] == "listening"

    # a following turn is accepted normally, not silently swallowed by a
    # stuck busy flag
    still_busy.set()
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1)
    )
    assert len(backend.calls) == 2


# --- shared playback lock (prevents device-contention crackling) -----------


def test_build_app_shares_one_playback_lock_between_tts_and_sound_cues():
    app = build_app(_settings(), backend=_FakeBackend())

    assert app.tts_output._playback_lock is app.sound_cues._playback_lock


def test_build_app_wires_the_configured_system_prompt_into_the_orchestrator(tmp_path):
    """task-v1.2.12: build_app() must bind settings.prompts.system, not the
    built-in default, so a config-file prompt actually reaches every turn."""
    settings = Settings(
        prompts=PromptSettings(system="You are Jarvis.", warmup="Hi"),
        memory=MemorySettings(root=str(tmp_path / "memory")),
    )

    app = build_app(settings, backend=_FakeBackend())

    assert app.orchestrator._system_prompt == "You are Jarvis."


async def test_build_app_appends_reasoning_section_after_loaded_memory(tmp_path):
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    (memory_root / "self.md").write_text("persona", encoding="utf-8")
    (memory_root / "memory.md").write_text("durable facts", encoding="utf-8")
    settings = Settings(
        prompts=PromptSettings(
            system="base prompt",
            warmup="Hi",
            reasoning_low="reason briefly",
        ),
        memory=MemorySettings(root=str(memory_root)),
        journal=JournalSettings(enabled=False),
    )
    backend = _FakeStreamingBackend()
    app = build_app(settings, backend=backend)
    await app.thinking_mode.set_level(ReasoningLevel.LOW, source="TEST")

    await app.orchestrator.submit_text_input("hello")

    assert backend.calls[-1][0][0] == {
        "role": "system",
        "content": (
            "base prompt\n\n"
            "[Jarvis curated self.md]\n"
            "persona\n"
            "[/Jarvis curated self.md]\n\n"
            "[Jarvis curated memory.md]\n"
            "durable facts\n"
            "[/Jarvis curated memory.md]\n\n"
            "reason briefly"
        ),
    }
    assert [reasoning_level for _messages, reasoning_level in backend.calls] == [
        ReasoningLevel.LOW
    ]


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
    settings = Settings(
        microphone=MicrophoneSettings(device="USB Headset", host_api="MME")
    )

    app = build_app(settings, backend=_FakeBackend())

    assert app.audio_input._stream_factory.keywords == {
        "device": "USB Headset",
        "host_api": "MME",
    }


def test_build_app_always_constructs_an_inert_mcp_host_when_mcp_is_disabled():
    """story-v1.4.0 task 3's own acceptance criterion: "off equals the
    capability does not exist" must be a structural fact, not just
    McpHost's own runtime behavior. Per the code-review revision, McpHost
    is now always constructed (so a later live toggle has something to
    call enable() on) - the structural guarantee lives in McpHost itself
    being side-effect-free until enable() runs, asserted here as status
    OFF; builtin tools are local in-process registrations and do not
    weaken the MCP-off invariant."""
    app = build_app(_settings(), backend=_FakeBackend())

    assert app.mcp_host is not None
    assert app.mcp_host.status == McpModuleStatus.OFF
    assert app.mcp_host.enabled is False
    tools = {tool.name: tool for tool in app.mcp_host.registry.all()}
    assert set(tools) == {
        "capture_camera_image",
        "list_session_files",
        "read_history",
        "read_history_ranges",
        "read_session_text",
        "remember",
        "search_history",
        "set_reasoning_level",
        "stat_session_file",
        "view_session_image",
        "write_session_file",
    }
    assert {tool.provider_kind for tool in tools.values()} == {"builtin"}


async def test_build_app_wires_session_files_without_forcing_session_creation(
    tmp_path,
):
    """The session-file scope provider reads the live journal session on each
    call; with no accepted turn yet there is no current session, so the tools
    report no-active-session and no loose session directory is created."""
    journal_root = tmp_path / "journal"
    settings = Settings(
        journal=JournalSettings(enabled=True, root=str(journal_root)),
        memory=MemorySettings(root=str(tmp_path / "memory")),
    )
    app = build_app(settings, backend=_FakeBackend())

    result = await app.mcp_host.dispatcher.dispatch("list_session_files", {})

    assert result.ok is False
    assert "active session" in str(result.content).lower()
    assert not journal_root.exists() or list(journal_root.iterdir()) == []


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


def test_build_app_constructs_annotation_generation_service_with_settings():
    settings = Settings(
        journal=JournalSettings(enabled=False),
        history=HistorySettings(
            annotation=HistoryAnnotationSettings(
                instruction="Summarize only the cited excerpt.",
                reasoning="high",
                max_concurrency=2,
                max_source_events=42,
                max_source_chars=15000,
                max_annotation_chars=3000,
            )
        ),
    )

    app = build_app(settings, backend=_FakeBackend())

    service = app.annotation_generation_service
    assert service is not None
    assert service.reasoning is ReasoningLevel.HIGH
    assert service.max_source_events == 42
    assert service.max_source_chars == 15000
    assert service._max_annotation_chars == 3000
    assert service._instruction == "Summarize only the cited excerpt."


def test_build_app_always_constructs_consolidation_planner_and_executor():
    """Unlike transcription/annotation generation, consolidation planning and
    execution have no separate enable flag - task v1.8.0-24/25 provide no
    background/automatic behavior to gate, only explicit, user-triggered
    reads and the one destructive action, so there is nothing unsafe about
    always constructing them."""
    settings = Settings(journal=JournalSettings(enabled=False))

    app = build_app(settings, backend=_FakeBackend())

    assert app.archive_overlay_repository is not None
    assert app.consolidation_planner is not None
    assert app.consolidation_executor is not None


def test_build_app_omits_annotation_generation_service_when_disabled():
    settings = Settings(
        journal=JournalSettings(enabled=False),
        history=HistorySettings(annotation=HistoryAnnotationSettings(enabled=False)),
    )

    app = build_app(settings, backend=_FakeBackend())

    assert app.annotation_generation_service is None


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

    async def on_request_started(self, event) -> None:
        pass

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


async def test_thinking_chunks_never_reach_journal_through_real_bus_wiring(tmp_path):
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
    settings = Settings(journal=JournalSettings(root=str(tmp_path)))

    app = build_app(
        settings,
        bus=bus,
        backend=backend,
        audio_input=_FakeAudioInput(),
        tts_output=tts_output,
        capture_input=_FakeCaptureInput(),
    )
    wire(app)

    await app.bus.publish(
        UtteranceChunk,
        UtteranceChunk(wav_bytes=b"voice clip", start_seconds=0, end_seconds=1),
    )
    assert app.journal_recorder is not None
    await app.journal_recorder.wait_for_pending()

    session_id = app.journal_recorder.session_id
    assert session_id is not None
    replay = JournalStore(tmp_path).read_session(session_id)

    assert [(event.role, event.source, event.text) for event in replay.events] == [
        ("user", "voice", ""),
        ("assistant", "assistant", "Hello"),
    ]
    assert all("reasoning" not in event.text for event in replay.events)
    assert tts_output.received_texts == ["Hello"]


def _client_with_sequential_ndjson_bodies(
    bodies: list[list[dict]],
) -> httpx.AsyncClient:
    """Like _client_with_ndjson_body, but a different canned response per
    call - mode 3's second pass (story-v1.9.0 task 3) is a real second
    POST to the same backend, not a re-read of the first."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        lines = bodies[min(call_count, len(bodies) - 1)]
        call_count += 1
        body = "\n".join(json.dumps(line) for line in lines).encode() + b"\n"
        return httpx.Response(200, content=body)

    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://localhost:11434"
    )


async def test_mode_3_derivative_reaches_tts_while_first_pass_stays_silent(tmp_path):
    """The full mode-3 flow (story-v1.9.0 task 3) through the real bus/wire()
    wiring AND the real TtsOutput (not a fake that skips its own gating
    logic): the canonical first pass streams to history/journal but never
    reaches synthesis, and the derivative second pass - a real second POST
    to the backend - is what actually gets spoken."""

    class _FakeTtsEngine:
        async def synthesize(self, text: str, language: str = "ru") -> bytes:
            return text.encode()

    played: list[str] = []

    async def fake_play(audio: bytes) -> None:
        played.append(audio.decode())

    canonical_lines = [
        {"message": {"content": "Canonical text."}, "done": False},
        {"message": {"content": ""}, "done": True, "eval_count": 1},
    ]
    derivative_lines = [
        {"message": {"content": "Derivative speech."}, "done": False},
        {"message": {"content": ""}, "done": True, "eval_count": 1},
    ]
    bus = EventBus()
    backend = OllamaBackend(
        bus=bus,
        settings=BackendSettings(),
        client=_client_with_sequential_ndjson_bodies(
            [canonical_lines, derivative_lines]
        ),
    )
    tts_output = TtsOutput(
        TtsSettings(), engine=_FakeTtsEngine(), play=fake_play, bus=bus
    )
    settings = Settings(
        journal=JournalSettings(root=str(tmp_path)),
        response=ResponseSettings(mode="text_voice"),
        prompts=PromptSettings(response_text_voice="derivative contract"),
    )

    app = build_app(
        settings,
        bus=bus,
        backend=backend,
        audio_input=_FakeAudioInput(),
        tts_output=tts_output,
        capture_input=_FakeCaptureInput(),
    )
    wire(app)

    await app.bus.publish(
        UtteranceChunk,
        UtteranceChunk(wav_bytes=b"voice clip", start_seconds=0, end_seconds=1),
    )
    assert app.journal_recorder is not None
    await app.journal_recorder.wait_for_pending()

    assert played == ["Derivative speech."]

    session_id = app.journal_recorder.session_id
    assert session_id is not None
    replay = JournalStore(tmp_path).read_session(session_id)
    [assistant_event] = [e for e in replay.events if e.role == "assistant"]
    assert assistant_event.text == "Canonical text."
    assert assistant_event.metadata["spoken_derivative"] == "Derivative speech."


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


async def test_wire_status_console_repaints_tool_rows_after_a_toggle():
    """A toggle already moved the checkbox in the browser, so the engine
    republishes the whole tool state - the row must never keep a label
    the engine no longer holds."""
    app = _fake_app()
    live_console = create_live_status_console(app, include_touchstrip=False)
    transport = _FakeTransport()
    live_console.transport = transport
    subscriptions = wire_status_console(app, live_console, asyncio.get_running_loop())

    await app.bus.publish(ToolEnablementChanged, ToolEnablementChanged())

    kind, payload = transport.calls[-1]
    assert kind == "mcp"
    assert [tool["name"] for tool in payload["local_tools"]] == [
        "capture_camera_image",
        "list_session_files",
        "read_history",
        "read_history_ranges",
        "read_session_text",
        "remember",
        "search_history",
        "set_reasoning_level",
        "stat_session_file",
        "view_session_image",
        "write_session_file",
    ]
    unwire(app, subscriptions)
