"""The confirmation exchange: show what was heard, speak what to check, wait for
a clear yes.

One exchange at a time, with its own small state instead of an Orchestrator
turn. A typed answer counts from the moment the heard block is posted; a spoken
answer only once the window is open, that is after the question was spoken and
the microphone is live again. Only `CONFIRMED` may lead to a send. Nothing the
user said or was heard is kept, logged, or put into an exception.

Every wait on a port is bounded, so that a hung port cannot strand the exchange:
a hung speaker is stopped and the window opens anyway; a hung sink, microphone
or transcriber ends the exchange as `FAILED`, and `last_failure` names the stage
(and nothing else about it)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Collection
from typing import TypeVar

from jarvis.personal_proxy.check_result import CheckedTranscript, Doubt
from jarvis.personal_proxy.confirmation_blocks import HeardDecision, heard_block_of
from jarvis.personal_proxy.confirmation_outcome import (
    Delivery,
    ExchangeOutcome,
    ExchangeState,
    FailureStage,
)
from jarvis.personal_proxy.confirmation_ports import (
    AnswerTranscriber,
    ChatSink,
    ExchangeSpeaker,
    MicrophoneGate,
    Sleep,
)
from jarvis.personal_proxy.confirmation_texts import spoken_question
from jarvis.personal_proxy.confirmation_vocabulary import AnswerKind, classify_answer

SPEECH_PHASE_TIMEOUT_SECONDS = 30

_OUTCOME_OF_ANSWER = {
    AnswerKind.YES: ExchangeOutcome.CONFIRMED,
    AnswerKind.NO: ExchangeOutcome.DECLINED,
    AnswerKind.UNCLEAR: ExchangeOutcome.UNCLEAR,
}

_T = TypeVar("_T")


class ExchangeBusyError(Exception):
    def __init__(self) -> None:
        super().__init__("a confirmation exchange is already pending")


class WrongLoopError(Exception):
    """`submit_typed`, `submit_spoken` or `cancel` was called from outside the
    event loop that runs the pending exchange."""

    def __init__(self) -> None:
        super().__init__("the confirmation exchange must be used on its event loop")


class _StageFailure(Exception):
    def __init__(self, stage: FailureStage) -> None:
        super().__init__("a confirmation exchange stage failed")
        self.stage = stage


async def _staged(stage: FailureStage, awaitable: Awaitable[_T]) -> _T:
    try:
        return await awaitable
    except _StageFailure:
        raise
    except Exception:
        raise _StageFailure(stage) from None


async def _discard(futures: Collection[asyncio.Future]) -> None:
    for future in futures:
        future.cancel()
    await asyncio.wait(futures)
    for future in futures:
        if not future.cancelled():
            future.exception()


def _running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


class ConfirmationExchange:
    """Not thread-safe. `run`, `submit_typed`, `submit_spoken` and `cancel` must
    all be used on the one event loop that runs the exchange. A caller on another
    thread (the Status Console transport, a hotkey) marshals onto that loop with
    `asyncio.run_coroutine_threadsafe` or `loop.call_soon_threadsafe`; while an
    exchange is pending, a call from anywhere else raises `WrongLoopError`."""

    def __init__(
        self,
        *,
        sink: ChatSink,
        speaker: ExchangeSpeaker,
        microphone: MicrophoneGate,
        transcriber: AnswerTranscriber,
        language: str | None,
        timeout_seconds: float,
        sleep: Sleep = asyncio.sleep,
        speech_phase_timeout_seconds: float = SPEECH_PHASE_TIMEOUT_SECONDS,
    ) -> None:
        self._sink = sink
        self._speaker = speaker
        self._microphone = microphone
        self._transcriber = transcriber
        self._language = language
        self._timeout_seconds = timeout_seconds
        self._sleep = sleep
        self._phase_limit = speech_phase_timeout_seconds
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._state = ExchangeState.DONE
        self._last_failure: FailureStage | None = None
        self._block_posted = False
        self._window_open = False
        self._resume_failed = False
        self._cancelled = False
        self._typed: str | None = None
        self._spoken: bytes | None = None
        self._decided = asyncio.Event()
        self._cancel_signal = asyncio.Event()

    def __repr__(self) -> str:
        return f"ConfirmationExchange(state={self._state.value})"

    @property
    def state(self) -> ExchangeState:
        return self._state

    @property
    def last_failure(self) -> FailureStage | None:
        """The stage the last run failed in; None if it did not fail."""
        return self._last_failure

    async def run(self, checked: CheckedTranscript) -> ExchangeOutcome:
        if self._running:
            raise ExchangeBusyError
        self._begin()
        try:
            return await self._conduct(checked)
        except _StageFailure as failure:
            return self._failed(failure.stage)
        except Exception:
            return self._failed(FailureStage.INTERNAL)
        finally:
            self._end()

    def submit_typed(self, text: str) -> Delivery:
        if not self._accepting() or not self._block_posted or self._decided.is_set():
            return Delivery.REJECTED
        if not isinstance(text, str):
            return Delivery.REJECTED
        self._typed = text
        self._decided.set()
        return Delivery.ACCEPTED

    def submit_spoken(self, utterance: bytes) -> Delivery:
        if not self._accepting() or not self._window_open or self._decided.is_set():
            return Delivery.REJECTED
        if not isinstance(utterance, bytes):
            return Delivery.REJECTED
        self._spoken = utterance
        self._decided.set()
        return Delivery.ACCEPTED

    def cancel(self) -> None:
        if not self._accepting():
            return
        self._cancelled = True
        self._cancel_signal.set()
        self._decided.set()

    def _accepting(self) -> bool:
        if not self._running:
            return False
        if _running_loop() is not self._loop:
            raise WrongLoopError
        return True

    def _failed(self, stage: FailureStage) -> ExchangeOutcome:
        self._last_failure = stage
        return ExchangeOutcome.FAILED

    def _begin(self) -> None:
        self._running = True
        self._loop = asyncio.get_running_loop()
        self._state = ExchangeState.ASKING
        self._last_failure = None
        self._block_posted = False
        self._window_open = False
        self._resume_failed = False
        self._cancelled = False
        self._typed = None
        self._spoken = None
        self._decided = asyncio.Event()
        self._cancel_signal = asyncio.Event()

    def _end(self) -> None:
        self._running = False
        self._state = ExchangeState.DONE
        self._block_posted = False
        self._window_open = False
        self._typed = None
        self._spoken = None

    async def _bounded(self, stage: FailureStage, awaitable: Awaitable[object]) -> bool:
        """True if the awaitable finished within the phase limit, False if the
        limit came first (the awaitable is then cancelled). A failure of the
        awaitable raises as a failure of `stage`."""
        work = asyncio.ensure_future(_staged(stage, awaitable))
        timer = asyncio.ensure_future(self._sleep(self._phase_limit))
        try:
            await asyncio.wait({work, timer}, return_when=asyncio.FIRST_COMPLETED)
            if work.done():
                work.result()
                return True
            timer.result()
            return False
        finally:
            await _discard({work, timer})

    async def _conduct(self, checked: CheckedTranscript) -> ExchangeOutcome:
        block = heard_block_of(checked, HeardDecision.ASK_CONFIRMATION)
        if not await self._bounded(FailureStage.SINK, self._sink.post(block)):
            raise _StageFailure(FailureStage.SINK)
        self._block_posted = True
        if not self._decided.is_set():
            await self._ask(checked.doubts)
        if not self._decided.is_set():
            await self._wait_in_window()
        return await self._outcome()

    async def _ask(self, doubts: tuple[Doubt, ...]) -> None:
        question = spoken_question(self._language, doubts)
        try:
            paused = await self._bounded(
                FailureStage.MICROPHONE, self._microphone.pause()
            )
            if not paused:
                raise _StageFailure(FailureStage.MICROPHONE)
            spoken = await self._bounded(
                FailureStage.SPEAKER, self._speak_until_decided(question)
            )
            if not spoken:
                self._stop_speaker()
        finally:
            await self._resume_microphone()
        if self._resume_failed:
            raise _StageFailure(FailureStage.MICROPHONE)

    async def _resume_microphone(self) -> None:
        # Swallowed here so it cannot replace a CancelledError or the failure
        # already in flight; _ask raises it afterwards when nothing else is.
        # The resume itself runs to its end even if this task is cancelled
        # meanwhile (a half-done resume can leave the microphone off); the
        # cancellation is raised again afterwards.
        resume = asyncio.ensure_future(self._microphone.resume())
        resume.add_done_callback(lambda done: done.cancelled() or done.exception())
        cancellation: asyncio.CancelledError | None = None
        while True:
            try:
                resumed = await self._resumed_within_limit(resume)
                break
            except asyncio.CancelledError as error:
                cancellation = cancellation or error
        if not resumed:
            self._resume_failed = True
        if cancellation is not None:
            raise cancellation

    async def _resumed_within_limit(self, resume: asyncio.Future) -> bool:
        try:
            return await self._bounded(FailureStage.MICROPHONE, asyncio.shield(resume))
        except Exception:
            return False

    def _stop_speaker(self) -> None:
        try:
            self._speaker.stop()
        except Exception:
            raise _StageFailure(FailureStage.SPEAKER) from None

    async def _speak_until_decided(self, question: str) -> None:
        speaking = asyncio.ensure_future(
            _staged(FailureStage.SPEAKER, self._speaker.speak(question, self._language))
        )
        decided = asyncio.ensure_future(self._decided.wait())
        try:
            await asyncio.wait({speaking, decided}, return_when=asyncio.FIRST_COMPLETED)
            if speaking.done():
                speaking.result()
            else:
                self._stop_speaker()
        finally:
            await _discard({speaking, decided})

    async def _wait_in_window(self) -> None:
        self._state = ExchangeState.AWAITING
        self._window_open = True
        answered = asyncio.ensure_future(self._decided.wait())
        timer = asyncio.ensure_future(self._sleep(self._timeout_seconds))
        try:
            await asyncio.wait({answered, timer}, return_when=asyncio.FIRST_COMPLETED)
            if timer.done() and not self._decided.is_set():
                timer.result()
        finally:
            await _discard({answered, timer})

    async def _outcome(self) -> ExchangeOutcome:
        if self._cancelled:
            return ExchangeOutcome.CANCELLED
        if not self._decided.is_set():
            return ExchangeOutcome.TIMED_OUT
        answer = await self._answer_text()
        if self._cancelled:
            return ExchangeOutcome.CANCELLED
        if answer is None:
            return ExchangeOutcome.UNCLEAR
        return _OUTCOME_OF_ANSWER[classify_answer(answer)]

    async def _answer_text(self) -> str | None:
        """The text of the answer; None if it held no speech or the exchange was
        cancelled meanwhile (cancel wins over a transcriber that is slow or hung)."""
        if self._typed is not None:
            return self._typed
        assert self._spoken is not None
        transcribing = asyncio.ensure_future(
            _staged(
                FailureStage.TRANSCRIBER, self._transcriber.transcribe(self._spoken)
            )
        )
        cancelled = asyncio.ensure_future(self._cancel_signal.wait())
        timer = asyncio.ensure_future(self._sleep(self._phase_limit))
        try:
            await asyncio.wait(
                {transcribing, cancelled, timer},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancelled.done():
                return None
            if transcribing.done():
                return transcribing.result()
            timer.result()
            raise _StageFailure(FailureStage.TRANSCRIBER)
        finally:
            await _discard({transcribing, cancelled, timer})
