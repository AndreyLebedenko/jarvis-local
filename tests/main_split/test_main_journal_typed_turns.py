import asyncio

from _support_from_test_main import (
    _assert_model_request_started,
    _complete_event,
    _FakeHistoryRetrievalService,
    _FakeJournalRecorder,
    _orchestrator,
    _RequestRecorder,
)

from jarvis.audio.input import (
    UtteranceChunk,
)
from jarvis.core.bus import EventBus
from jarvis.core.lifecycle import (
    VOICE_PLACEHOLDER_TEXT,
    ModelRequestInput,
    TextSubmissionReason,
)
from jarvis.core.solo_session import SoloSessionState
from jarvis.inputs.capture import ScreenshotCaptured
from jarvis.journal import (
    HistoryRetrievalCandidate,
    HistoryRetrievalFallbackMode,
    HistoryRetrievalResult,
    HistoryRetrievalSourceMode,
    HistoryRetrievalStatus,
    JournalEventRef,
)

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
    assert messages[-1]["content"] == VOICE_PLACEHOLDER_TEXT


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
