"""A dialog turn that stops at the generation length cap is recorded as
truncated (task-generation-num-predict-cap.md, "Truncated dialog turn"):
journal outcome `truncated`, and a history note after the assistant text so
a later turn's model does not read the cut answer as finished."""

from collections.abc import AsyncIterator

import pytest
from _support_from_test_main import (
    _complete_event,
    _FakeJournalRecorder,
    _FakeSoundCues,
    _orchestrator,
)

import jarvis.app as main_module
from jarvis.app import ConversationHistory, Orchestrator
from jarvis.core.bus import EventBus
from jarvis.dialog.backend import ResponseComplete, ResponseToken
from jarvis.dialog.tool_presentation import NativeToolPresentation, ToolAwareDialog
from jarvis.inputs.clipboard import ClipboardSubmitted
from jarvis.journal import TurnOutcome
from jarvis.tools.interception import ToolDispatchResult
from jarvis.tools.registry import RegisteredTool, ToolRegistry


def _clipboard(text: str) -> ClipboardSubmitted:
    return ClipboardSubmitted(text=text, truncated=False, is_empty=False)


async def test_a_turn_stopped_at_the_length_cap_is_journaled_as_truncated():
    async def chat_impl() -> None:
        await orchestrator.on_response_token(ResponseToken(text="The first half"))

    journal_recorder = _FakeJournalRecorder()
    orchestrator, _backend, _sound_cues = _orchestrator(
        chat_impl=chat_impl, journal_recorder=journal_recorder
    )

    await orchestrator.on_clipboard(_clipboard("explain everything"))
    await orchestrator.on_response_complete(_complete_event(done_reason="length"))

    assert journal_recorder.assistant_texts == ["The first half"]
    assert journal_recorder.assistant_outcomes == [TurnOutcome.TRUNCATED]


async def test_a_truncated_turn_leaves_a_history_note_after_the_assistant_text():
    async def chat_impl() -> None:
        await orchestrator.on_response_token(ResponseToken(text="The first half"))

    orchestrator, _backend, _sound_cues = _orchestrator(chat_impl=chat_impl)

    await orchestrator.on_clipboard(_clipboard("explain everything"))
    await orchestrator.on_response_complete(_complete_event(done_reason="length"))

    assert orchestrator._history.as_messages() == [
        {"role": "user", "content": "explain everything"},
        {"role": "assistant", "content": "The first half"},
        {"role": "system", "content": main_module._TRUNCATED_HISTORY_NOTE},
    ]


async def test_a_truncated_turn_with_no_answer_text_is_still_journaled_as_truncated():
    """Reasoning can consume the whole cap: the answer is empty, and the
    journal must still say why."""
    journal_recorder = _FakeJournalRecorder()
    orchestrator, _backend, _sound_cues = _orchestrator(
        journal_recorder=journal_recorder
    )

    await orchestrator.on_clipboard(_clipboard("write a sonnet"))
    await orchestrator.on_response_complete(_complete_event(done_reason="length"))

    assert journal_recorder.assistant_texts == [""]
    assert journal_recorder.assistant_outcomes == [TurnOutcome.TRUNCATED]


@pytest.mark.parametrize("done_reason", ["stop", None])
async def test_a_turn_not_stopped_by_the_length_cap_has_no_truncation_marker(
    done_reason,
):
    async def chat_impl() -> None:
        await orchestrator.on_response_token(ResponseToken(text="Full answer."))

    journal_recorder = _FakeJournalRecorder()
    orchestrator, _backend, _sound_cues = _orchestrator(
        chat_impl=chat_impl, journal_recorder=journal_recorder
    )

    await orchestrator.on_clipboard(_clipboard("hello"))
    await orchestrator.on_response_complete(_complete_event(done_reason=done_reason))

    assert journal_recorder.assistant_outcomes == [None]
    assert orchestrator._history.as_messages() == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Full answer."},
    ]


class _ScriptedTransport:
    """One scripted chunk list per request of the tool loop."""

    def __init__(self, responses: list[list[dict[str, object]]]) -> None:
        self._responses = responses

    async def chat(self, messages, images_b64=None, reasoning_level=None, *, options):
        raise AssertionError("the tool loop must stream through iter_chat")

    async def iter_chat(
        self,
        messages,
        images_b64=None,
        reasoning_level=None,
        tools=None,
        *,
        options,
    ) -> AsyncIterator[dict[str, object]]:
        for chunk in self._responses.pop(0):
            yield chunk


class _OkDispatcher:
    async def dispatch(self, tool_name, arguments) -> ToolDispatchResult:
        return ToolDispatchResult(ok=True, correlation_id="1", content={"sunny": True})


def _search_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.set_provider_tools(
        "search",
        [
            RegisteredTool(
                name="search_web",
                description="Search for current information",
                schema={"type": "object", "properties": {}},
                provider="search",
                enabled=True,
            )
        ],
    )
    return registry


async def test_a_tool_loop_turn_is_truncated_by_its_final_requests_done_reason():
    """The tool call request ended normally; only the final answer request
    hit the cap - that one decides the turn's outcome."""
    bus = EventBus()
    transport = _ScriptedTransport(
        [
            [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {"function": {"name": "search_web", "arguments": {}}}
                        ],
                    }
                },
                {"message": {"content": ""}, "done": True, "done_reason": "stop"},
            ],
            [
                {"message": {"content": "It is sun"}},
                {"message": {"content": ""}, "done": True, "done_reason": "length"},
            ],
        ]
    )
    dialog = ToolAwareDialog(
        transport,
        bus,
        _search_tool_registry(),
        _OkDispatcher(),
        NativeToolPresentation(),
        max_tool_calls_per_turn=3,
    )
    journal_recorder = _FakeJournalRecorder()
    orchestrator = Orchestrator(
        dialog,
        ConversationHistory(),
        _FakeSoundCues(),
        bus=bus,
        journal_recorder=journal_recorder,
    )
    bus.subscribe(ResponseToken, orchestrator.on_response_token)
    bus.subscribe(ResponseComplete, orchestrator.on_response_complete)

    await orchestrator.on_clipboard(_clipboard("weather?"))

    assert journal_recorder.assistant_texts == ["It is sun"]
    assert journal_recorder.assistant_outcomes == [TurnOutcome.TRUNCATED]
    assert orchestrator._history.as_messages()[-1] == {
        "role": "system",
        "content": main_module._TRUNCATED_HISTORY_NOTE,
    }
