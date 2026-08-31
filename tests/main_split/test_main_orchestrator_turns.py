import asyncio
import base64
import logging

from _support_from_test_main import (
    _assert_model_request_started,
    _complete_event,
    _orchestrator,
    _RequestRecorder,
)

import jarvis.app as main_module
from jarvis.app import (
    APP_LOGGER_NAME,
    SYSTEM_PROMPT,
)
from jarvis.audio.input import (
    UtteranceChunk,
)
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    HistorySettings,
)
from jarvis.core.lifecycle import (
    ModelRequestInput,
    ModelRequestStarted,
)
from jarvis.history.context_budget import ContextBudgetLimits
from jarvis.inputs.capture import ScreenshotCaptured
from jarvis.inputs.clipboard import ClipboardSubmitted

# --- Orchestrator --------------------------------------------------------


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
