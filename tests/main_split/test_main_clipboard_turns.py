import asyncio

from jarvis.audio.input import (
    UtteranceChunk,
)
from jarvis.dialog.backend import (
    ResponseToken,
)
from jarvis.inputs.capture import ScreenshotCaptured
from jarvis.inputs.clipboard import ClipboardSubmitted
from tests.main_split._support_from_test_main import _complete_event, _orchestrator

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
