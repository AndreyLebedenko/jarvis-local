import asyncio
from dataclasses import replace

import pytest
from _support_from_test_main import (
    _collecting_subscriber,
    _complete_event,
    _FakeJournalRecorder,
    _FakeTtsOutput,
    _generation_with,
    _orchestrator,
)

import jarvis.app as main_module
from jarvis.app import App, _on_full_response_complete
from jarvis.audio.input import (
    UtteranceChunk,
)
from jarvis.core.bus import EventBus
from jarvis.core.config import GenerationOptions, Settings, VadSettings
from jarvis.core.lifecycle import TurnCompleted
from jarvis.dialog.backend import (
    ResponseComplete,
    ResponseToken,
)
from jarvis.dialog.response_mode import (
    ResponseMode,
    ResponseModeState,
)
from jarvis.dialog.thinking_mode import (
    ReasoningLevel,
)
from jarvis.inputs.clipboard import ClipboardSubmitted
from jarvis.journal import TurnOutcome

# --- mode 3 second pass (story-v1.9.0 task 3) -------------------------------


def _text_voice_orchestrator(
    *, chat_impl, journal_recorder=None, response_mode=None, generation=None
):
    generation = generation or _generation_with(
        {"spoken_derivative": "derivative contract"}
    )
    mode_state = response_mode or ResponseModeState(
        bus=EventBus(), initial_mode=ResponseMode.TEXT_VOICE
    )
    orchestrator, backend, sound_cues = _orchestrator(
        chat_impl=chat_impl,
        response_mode=mode_state,
        generation_settings=generation,
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


async def test_derivative_pass_uses_its_own_profiles_options_and_reasoning():
    async def chat_impl() -> None:
        if len(backend.calls) == 1:
            await orchestrator.on_response_token(ResponseToken(text="canonical reply"))

    generation = _generation_with(
        {"spoken_derivative": "derivative contract"},
        options={
            "dialog.off": GenerationOptions(num_predict=4096),
            "spoken_derivative": GenerationOptions(temperature=0.2, num_predict=512),
        },
    )
    generation.profiles["spoken_derivative"] = replace(
        generation.profiles["spoken_derivative"], reasoning="medium"
    )
    orchestrator, backend, _sound_cues = _text_voice_orchestrator(
        chat_impl=chat_impl, generation=generation
    )

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.run_derivative_pass()

    assert backend.options_calls == [
        GenerationOptions(num_predict=4096),
        GenerationOptions(temperature=0.2, num_predict=512),
    ]
    assert backend.reasoning_level_calls == [ReasoningLevel.OFF, ReasoningLevel.MEDIUM]


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


async def test_derivative_pass_with_no_profile_prompt_uses_an_empty_prompt():
    """A spoken_derivative profile without a prompt must not crash the
    dispatch, and must still send the exact shown text as the user
    message."""

    async def chat_impl() -> None:
        if len(backend.calls) == 1:
            await orchestrator.on_response_token(ResponseToken(text="canonical reply"))

    mode_state = ResponseModeState(bus=EventBus(), initial_mode=ResponseMode.TEXT_VOICE)
    orchestrator, backend, _sound_cues = _orchestrator(
        chat_impl=chat_impl,
        response_mode=mode_state,
        generation_settings=_generation_with({"spoken_derivative": None}),
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


# --- length cap in mode 3 (task-generation-num-predict-cap.md) ---------------


async def test_truncated_first_pass_journals_the_turn_as_truncated_after_pass_2():
    async def chat_impl() -> None:
        if len(backend.calls) == 1:
            await orchestrator.on_response_token(ResponseToken(text="cut canonical"))
        else:
            await orchestrator.on_response_token(ResponseToken(text="derivative"))

    journal_recorder = _FakeJournalRecorder()
    orchestrator, backend, _sound_cues = _text_voice_orchestrator(
        chat_impl=chat_impl, journal_recorder=journal_recorder
    )

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    await orchestrator.on_response_complete(_complete_event(done_reason="length"))
    await orchestrator.run_derivative_pass()

    assert len(backend.calls) == 2
    assert journal_recorder.assistant_texts == ["cut canonical"]
    assert journal_recorder.assistant_outcomes == [TurnOutcome.TRUNCATED]
    assert journal_recorder.assistant_spoken_derivatives == ["derivative"]
    assert journal_recorder.assistant_spoken_derivative_truncated == [False]
    assert orchestrator._history.as_messages()[-2:] == [
        {"role": "assistant", "content": "cut canonical"},
        {"role": "system", "content": main_module._TRUNCATED_HISTORY_NOTE},
    ]


async def test_truncated_first_pass_with_blank_text_skips_the_derivative_pass():
    """Nothing to render aloud: the turn is journaled right away, like a
    single-pass one, with no spoken derivative."""

    async def chat_impl() -> None:
        await orchestrator.on_response_token(ResponseToken(text=" \n"))

    journal_recorder = _FakeJournalRecorder()
    orchestrator, backend, _sound_cues = _text_voice_orchestrator(
        chat_impl=chat_impl, journal_recorder=journal_recorder
    )

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    await orchestrator.on_response_complete(_complete_event(done_reason="length"))

    assert orchestrator.needs_derivative_pass() is False
    assert len(backend.calls) == 1
    assert journal_recorder.assistant_outcomes == [TurnOutcome.TRUNCATED]
    assert journal_recorder.assistant_spoken_derivatives == [None]


async def test_truncated_derivative_pass_flags_only_the_derivative_as_truncated():
    """The canonical text is complete, so the outcome stays empty and the
    history gets no truncation note - same reasoning as an interrupted
    derivative pass."""

    async def chat_impl() -> None:
        if len(backend.calls) == 1:
            await orchestrator.on_response_token(ResponseToken(text="canonical"))
            return
        await orchestrator.on_response_token(ResponseToken(text="cut deriv"))
        orchestrator.observe_response_complete(_complete_event(done_reason="length"))

    journal_recorder = _FakeJournalRecorder()
    orchestrator, backend, _sound_cues = _text_voice_orchestrator(
        chat_impl=chat_impl, journal_recorder=journal_recorder
    )

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.run_derivative_pass()

    assert journal_recorder.assistant_outcomes == [None]
    assert journal_recorder.assistant_spoken_derivatives == ["cut deriv"]
    assert journal_recorder.assistant_spoken_derivative_truncated == [True]
    assert journal_recorder.assistant_spoken_derivative_interrupted == [False]
    assert main_module._TRUNCATED_HISTORY_NOTE not in [
        message["content"] for message in orchestrator._history.as_messages()
    ]


async def test_both_passes_truncated_record_both_markers():
    async def chat_impl() -> None:
        if len(backend.calls) == 1:
            await orchestrator.on_response_token(ResponseToken(text="cut canonical"))
            return
        await orchestrator.on_response_token(ResponseToken(text="cut deriv"))
        orchestrator.observe_response_complete(_complete_event(done_reason="length"))

    journal_recorder = _FakeJournalRecorder()
    orchestrator, backend, _sound_cues = _text_voice_orchestrator(
        chat_impl=chat_impl, journal_recorder=journal_recorder
    )

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    await orchestrator.on_response_complete(_complete_event(done_reason="length"))
    await orchestrator.run_derivative_pass()

    assert journal_recorder.assistant_outcomes == [TurnOutcome.TRUNCATED]
    assert journal_recorder.assistant_spoken_derivative_truncated == [True]


@pytest.mark.parametrize("done_reason", ["stop", None])
async def test_derivative_pass_not_stopped_by_the_length_cap_is_not_flagged(
    done_reason,
):
    async def chat_impl() -> None:
        if len(backend.calls) == 1:
            await orchestrator.on_response_token(ResponseToken(text="canonical"))
            return
        await orchestrator.on_response_token(ResponseToken(text="derivative"))
        orchestrator.observe_response_complete(_complete_event(done_reason=done_reason))

    journal_recorder = _FakeJournalRecorder()
    orchestrator, backend, _sound_cues = _text_voice_orchestrator(
        chat_impl=chat_impl, journal_recorder=journal_recorder
    )

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.run_derivative_pass()

    assert journal_recorder.assistant_outcomes == [None]
    assert journal_recorder.assistant_spoken_derivative_truncated == [False]


async def test_first_pass_cap_is_not_attributed_to_a_derivative_that_never_completed():
    """The first pass's own ResponseComplete is observed too; a derivative
    pass that publishes none (here: interrupted) must not inherit it."""
    still_busy = asyncio.Event()

    async def chat_impl() -> None:
        if len(backend.calls) == 1:
            await orchestrator.on_response_token(ResponseToken(text="cut canonical"))
            return
        await still_busy.wait()

    journal_recorder = _FakeJournalRecorder()
    orchestrator, backend, _sound_cues = _text_voice_orchestrator(
        chat_impl=chat_impl, journal_recorder=journal_recorder
    )

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    first_pass_complete = _complete_event(done_reason="length")
    orchestrator.observe_response_complete(first_pass_complete)
    await orchestrator.on_response_complete(first_pass_complete)
    derivative_task = asyncio.create_task(orchestrator.run_derivative_pass())
    await asyncio.sleep(0)
    await asyncio.sleep(0)  # let the derivative pass's own chat() start
    orchestrator.cancel_active_turn()
    await derivative_task

    assert journal_recorder.assistant_spoken_derivative_interrupted == [True]
    assert journal_recorder.assistant_spoken_derivative_truncated == [False]


def _text_voice_app(orchestrator, backend, sound_cues, bus: EventBus) -> App:
    app = App(
        bus=bus,
        backend=backend,
        audio_input=None,
        tts_output=_FakeTtsOutput(),
        capture_input=None,
        orchestrator=orchestrator,
        sound_cues=sound_cues,
        thinking_mode=None,
        response_mode=None,
        settings=Settings(vad=VadSettings(resume_cooldown_seconds=0.001)),
    )

    async def on_response_complete(event: ResponseComplete) -> None:
        await _on_full_response_complete(app, event)

    bus.subscribe(ResponseComplete, on_response_complete)
    return app


async def test_derivative_cap_reaches_the_journal_through_the_reentrant_bus_event():
    """The derivative's ResponseComplete re-enters _on_full_response_complete()
    after the turn's one claim is spent; that call must still hand its
    done_reason to run_derivative_pass()."""
    bus = EventBus()

    async def chat_impl() -> None:
        if len(backend.calls) == 1:
            await orchestrator.on_response_token(ResponseToken(text="canonical"))
            await bus.publish(ResponseComplete, _complete_event())
            return
        await orchestrator.on_response_token(ResponseToken(text="cut deriv"))
        await bus.publish(ResponseComplete, _complete_event(done_reason="length"))

    journal_recorder = _FakeJournalRecorder()
    orchestrator, backend, sound_cues = _orchestrator(
        chat_impl=chat_impl,
        response_mode=ResponseModeState(bus=bus, initial_mode=ResponseMode.TEXT_VOICE),
        generation_settings=_generation_with({"spoken_derivative": "contract"}),
        journal_recorder=journal_recorder,
        bus=bus,
    )
    _text_voice_app(orchestrator, backend, sound_cues, bus)

    await orchestrator.on_clipboard(
        ClipboardSubmitted(text="question", truncated=False, is_empty=False)
    )

    assert journal_recorder.assistant_outcomes == [None]
    assert journal_recorder.assistant_spoken_derivative_truncated == [True]


async def test_blank_truncated_first_pass_still_ends_the_turn_without_pass_2():
    bus = EventBus()
    turns_completed: list[TurnCompleted] = []
    bus.subscribe(TurnCompleted, _collecting_subscriber(turns_completed))

    async def chat_impl() -> None:
        await bus.publish(ResponseComplete, _complete_event(done_reason="length"))

    journal_recorder = _FakeJournalRecorder()
    orchestrator, backend, sound_cues = _orchestrator(
        chat_impl=chat_impl,
        response_mode=ResponseModeState(bus=bus, initial_mode=ResponseMode.TEXT_VOICE),
        generation_settings=_generation_with({"spoken_derivative": "contract"}),
        journal_recorder=journal_recorder,
        bus=bus,
    )
    _text_voice_app(orchestrator, backend, sound_cues, bus)

    await orchestrator.on_clipboard(
        ClipboardSubmitted(text="write a sonnet", truncated=False, is_empty=False)
    )

    assert len(backend.calls) == 1
    assert orchestrator.is_busy is False
    assert len(turns_completed) == 1
    assert sound_cues.played[-1] == "listening"
    assert journal_recorder.assistant_outcomes == [TurnOutcome.TRUNCATED]
    assert journal_recorder.assistant_spoken_derivatives == [None]
