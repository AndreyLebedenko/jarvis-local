import asyncio

from jarvis.app import (
    _on_interrupt_requested,
)
from jarvis.audio.input import (
    UtteranceChunk,
)
from jarvis.inputs.interrupt import InterruptRequested
from tests.main_split._support_from_test_main import (
    _app_for_interrupt_test,
    _orchestrator,
    _RecordingTtsOutputForInterrupt,
)

# --- _on_interrupt_requested (task-v1.7.0-2 interrupt hotkey) ---------------


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
