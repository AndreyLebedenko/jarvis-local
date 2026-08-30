import asyncio

from jarvis.app import (
    App,
    _cancel_current_turn,
    _on_full_response_complete,
)
from jarvis.audio.input import (
    UtteranceChunk,
)
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    Settings,
    VadSettings,
)
from jarvis.core.lifecycle import (
    TurnAccepted,
)
from tests.main_split._support_from_test_main import (
    _app_for_interrupt_test,
    _complete_event,
    _FakeJournalRecorder,
    _orchestrator,
    _RecordingTtsOutputForInterrupt,
)

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
