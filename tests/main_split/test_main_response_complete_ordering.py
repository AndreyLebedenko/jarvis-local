import asyncio

from _support_from_test_main import (
    _complete_event,
    _orchestrator,
    _settings,
)

from jarvis.app import (
    VOICE_PLACEHOLDER_TEXT,
    App,
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
