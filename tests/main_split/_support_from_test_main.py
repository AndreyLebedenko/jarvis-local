"""Shared fixtures and fakes for the former tests/test_main.py suite (task-v1.9.0-5
file-layout split; story-v1.9.0 task 5).

Content moved verbatim from the original import block; every split test

module imports from here."""

from collections.abc import Callable

import jarvis.app as main_module
from jarvis.app import (
    App,
    ConversationHistory,
    Orchestrator,
    build_app,
)
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    JournalSettings,
    Settings,
    VadSettings,
)
from jarvis.core.lifecycle import (
    ModelRequestInput,
    ModelRequestStarted,
)
from jarvis.dialog.backend import (
    LatencyMetrics,
    ResponseComplete,
)
from jarvis.dialog.response_mode import (
    ResponseMode,
)
from jarvis.dialog.thinking_mode import (
    ReasoningLevel,
)
from jarvis.journal import (
    HistoryRetrievalQuery,
    HistoryRetrievalResult,
    TurnOutcome,
)
from jarvis.ui.contract import (
    DataLocality,
    ModuleHealth,
    RuntimeState,
    VisibilityMode,
)


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
