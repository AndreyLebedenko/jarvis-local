import asyncio

from _support_from_test_main import (
    _app_for_interrupt_test,
    _complete_event,
    _FakeJournalRecorder,
    _orchestrator,
    _RecordingTtsOutputForInterrupt,
)

import jarvis.app as main_module
from jarvis.app import (
    App,
    _cancel_current_turn,
)
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    Settings,
    VadSettings,
)
from jarvis.core.lifecycle import (
    ModelRequestStarted,
)
from jarvis.dialog.backend import (
    ResponseToken,
)
from jarvis.dialog.thinking_mode import (
    ReasoningLevel,
)
from jarvis.inputs.clipboard import ClipboardSubmitted
from jarvis.journal import (
    TurnOutcome,
)

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
