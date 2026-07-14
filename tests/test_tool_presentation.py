import json
from collections.abc import AsyncIterator, Sequence

import pytest

from jarvis.core.bus import EventBus
from jarvis.dialog.backend import LatencyMetrics, ResponseComplete, ResponseToken
from jarvis.dialog.thinking_mode import ReasoningLevel
from jarvis.dialog.tool_presentation import (
    NativeToolPresentation,
    PromptToolPresentation,
    ToolAwareDialog,
    build_tool_presentation,
)
from jarvis.tools.interception import ToolDispatchResult
from jarvis.tools.registry import RegisteredTool, ToolRegistry


def _tool(name: str = "search_web", *, enabled: bool = True) -> RegisteredTool:
    return RegisteredTool(
        name=name,
        description="Search for current information",
        schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        provider="search",
        enabled=enabled,
    )


def _registry(*tools: RegisteredTool) -> ToolRegistry:
    registry = ToolRegistry()
    registry.set_provider_tools("search", list(tools))
    return registry


class FakeBackend:
    def __init__(self, responses: Sequence[Sequence[dict[str, object]]]) -> None:
        self.responses = list(responses)
        self.legacy_calls: list[dict[str, object]] = []
        self.raw_calls: list[dict[str, object]] = []

    async def chat(
        self,
        messages: Sequence[dict[str, object]],
        images_b64: Sequence[str] | None = None,
        reasoning_level: ReasoningLevel = ReasoningLevel.OFF,
    ) -> None:
        self.legacy_calls.append(
            {
                "messages": list(messages),
                "images_b64": images_b64,
                "reasoning_level": reasoning_level,
            }
        )

    async def iter_chat(
        self,
        messages: Sequence[dict[str, object]],
        images_b64: Sequence[str] | None = None,
        reasoning_level: ReasoningLevel = ReasoningLevel.OFF,
        tools: Sequence[dict[str, object]] | None = None,
    ) -> AsyncIterator[dict[str, object]]:
        self.raw_calls.append(
            {
                "messages": list(messages),
                "images_b64": images_b64,
                "reasoning_level": reasoning_level,
                "tools": tools,
            }
        )
        for chunk in self.responses.pop(0):
            yield chunk


class StreamingAssertionBackend(FakeBackend):
    def __init__(self, observed_tokens: list[str]) -> None:
        super().__init__([])
        self.observed_tokens = observed_tokens

    async def iter_chat(
        self,
        messages: Sequence[dict[str, object]],
        images_b64: Sequence[str] | None = None,
        reasoning_level: ReasoningLevel = ReasoningLevel.OFF,
        tools: Sequence[dict[str, object]] | None = None,
    ) -> AsyncIterator[dict[str, object]]:
        yield {"message": {"content": "first sentence. "}}
        assert self.observed_tokens == ["first sentence. "]
        yield {"message": {"content": "second sentence."}}
        yield {"message": {"content": ""}, "done": True}


class FakeDispatcher:
    def __init__(self, results: Sequence[ToolDispatchResult]) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def dispatch(
        self, tool_name: str, arguments: dict[str, object]
    ) -> ToolDispatchResult:
        self.calls.append((tool_name, arguments))
        return self.results.pop(0)


def _done(content: str = "") -> list[dict[str, object]]:
    return [
        {"message": {"content": content}},
        {"message": {"content": ""}, "done": True, "eval_count": 4},
    ]


def _native_calls(*calls: tuple[str, object]) -> list[dict[str, object]]:
    return [
        {
            "message": {
                "content": "",
                "tool_calls": [
                    {"function": {"name": name, "arguments": arguments}}
                    for name, arguments in calls
                ],
            }
        },
        {"message": {"content": ""}, "done": True},
    ]


def _append_token(target: list[str]):
    async def append(event: ResponseToken) -> None:
        target.append(event.text)

    return append


def _append_completion(target: list[ResponseComplete]):
    async def append(event: ResponseComplete) -> None:
        target.append(event)

    return append


def test_native_declaration_uses_registry_schema_verbatim():
    presentation = NativeToolPresentation()

    request = presentation.prepare([_tool()])

    assert request.tools == [
        {
            "type": "function",
            "function": {
                "name": "search_web",
                "description": "Search for current information",
                "parameters": _tool().schema,
            },
        }
    ]
    assert request.prompt_suffix is None


def test_prompt_declaration_contains_schema_and_exact_reply_contract():
    presentation = PromptToolPresentation()

    request = presentation.prepare([_tool()])

    assert request.tools is None
    assert "search_web" in request.prompt_suffix
    assert (
        json.dumps(_tool().schema, ensure_ascii=False, separators=(",", ":"))
        in request.prompt_suffix
    )
    assert '"tool_call"' in request.prompt_suffix
    assert '"final_answer"' in request.prompt_suffix


@pytest.mark.parametrize(
    ("name", "expected_type"),
    [("native", NativeToolPresentation), ("prompt", PromptToolPresentation)],
)
def test_presentation_factory_selects_configured_strategy(name, expected_type):
    assert isinstance(build_tool_presentation(name), expected_type)


@pytest.mark.asyncio
async def test_empty_registry_uses_byte_identical_legacy_dialog_path():
    bus = EventBus()
    backend = FakeBackend([])
    dialog = ToolAwareDialog(
        backend,
        bus,
        _registry(),
        FakeDispatcher([]),
        NativeToolPresentation(),
        max_tool_calls_per_turn=3,
    )
    messages = [{"role": "user", "content": "hello"}]

    await dialog.chat(
        messages, images_b64=["image"], reasoning_level=ReasoningLevel.HIGH
    )

    assert backend.legacy_calls == [
        {
            "messages": messages,
            "images_b64": ["image"],
            "reasoning_level": ReasoningLevel.HIGH,
        }
    ]
    assert backend.raw_calls == []


@pytest.mark.asyncio
async def test_registry_with_only_disabled_tools_uses_legacy_path():
    backend = FakeBackend([])
    dialog = ToolAwareDialog(
        backend,
        EventBus(),
        _registry(_tool(enabled=False)),
        FakeDispatcher([]),
        NativeToolPresentation(),
        max_tool_calls_per_turn=3,
    )

    await dialog.chat([{"role": "user", "content": "hello"}])

    assert len(backend.legacy_calls) == 1
    assert backend.raw_calls == []


@pytest.mark.asyncio
async def test_native_tool_artifacts_do_not_reach_response_events():
    bus = EventBus()
    tokens: list[str] = []
    completions: list[ResponseComplete] = []
    bus.subscribe(ResponseToken, _append_token(tokens))
    bus.subscribe(ResponseComplete, _append_completion(completions))
    backend = FakeBackend(
        [
            _native_calls(("search_web", {"query": "weather"})),
            _done("It is sunny."),
        ]
    )
    dispatcher = FakeDispatcher(
        [ToolDispatchResult(ok=True, correlation_id="1", content={"sunny": True})]
    )
    dialog = ToolAwareDialog(
        backend,
        bus,
        _registry(_tool()),
        dispatcher,
        NativeToolPresentation(),
        max_tool_calls_per_turn=3,
    )

    await dialog.chat([{"role": "user", "content": "weather?"}])

    assert tokens == ["It is sunny."]
    assert len(completions) == 1
    assert completions[0].metrics.eval_count == 4
    assert dispatcher.calls == [("search_web", {"query": "weather"})]
    follow_up_messages = backend.raw_calls[1]["messages"]
    assert follow_up_messages[-2]["role"] == "assistant"
    assert follow_up_messages[-1]["role"] == "tool"
    assert "sunny" in follow_up_messages[-1]["content"]


@pytest.mark.asyncio
async def test_native_final_answer_tokens_publish_while_stream_is_open():
    bus = EventBus()
    tokens: list[str] = []
    bus.subscribe(ResponseToken, _append_token(tokens))
    backend = StreamingAssertionBackend(tokens)
    dialog = ToolAwareDialog(
        backend,
        bus,
        _registry(_tool()),
        FakeDispatcher([]),
        NativeToolPresentation(),
        max_tool_calls_per_turn=3,
    )

    await dialog.chat([{"role": "user", "content": "hello"}])

    assert tokens == ["first sentence. ", "second sentence."]


@pytest.mark.asyncio
async def test_native_call_metadata_after_answer_text_is_ignored():
    bus = EventBus()
    tokens: list[str] = []
    bus.subscribe(ResponseToken, _append_token(tokens))
    backend = FakeBackend(
        [
            [
                {"message": {"content": "Final answer."}},
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "search_web",
                                    "arguments": {"query": "must not run"},
                                }
                            }
                        ],
                    }
                },
                {"message": {"content": ""}, "done": True},
            ]
        ]
    )
    dispatcher = FakeDispatcher([])
    dialog = ToolAwareDialog(
        backend,
        bus,
        _registry(_tool()),
        dispatcher,
        NativeToolPresentation(),
        max_tool_calls_per_turn=3,
    )

    await dialog.chat([{"role": "user", "content": "hello"}])

    assert tokens == ["Final answer."]
    assert dispatcher.calls == []
    assert len(backend.raw_calls) == 1


@pytest.mark.asyncio
async def test_multiple_native_calls_run_sequentially_within_shared_budget():
    backend = FakeBackend(
        [
            _native_calls(
                ("search_web", {"query": "one"}),
                ("search_web", {"query": "two"}),
            ),
            _done("Combined answer."),
        ]
    )
    dispatcher = FakeDispatcher(
        [
            ToolDispatchResult(ok=True, correlation_id="1", content="first"),
            ToolDispatchResult(ok=True, correlation_id="2", content="second"),
        ]
    )
    dialog = ToolAwareDialog(
        backend,
        EventBus(),
        _registry(_tool()),
        dispatcher,
        NativeToolPresentation(),
        max_tool_calls_per_turn=2,
    )

    await dialog.chat([{"role": "user", "content": "compare"}])

    assert dispatcher.calls == [
        ("search_web", {"query": "one"}),
        ("search_web", {"query": "two"}),
    ]
    assert backend.raw_calls[1]["tools"] is None


@pytest.mark.asyncio
async def test_calls_beyond_budget_are_not_dispatched_and_model_gets_honest_error():
    backend = FakeBackend(
        [
            _native_calls(
                ("search_web", {"query": "one"}),
                ("search_web", {"query": "two"}),
            ),
            _done("Budget-limited answer."),
        ]
    )
    dispatcher = FakeDispatcher(
        [ToolDispatchResult(ok=True, correlation_id="1", content="first")]
    )
    dialog = ToolAwareDialog(
        backend,
        EventBus(),
        _registry(_tool()),
        dispatcher,
        NativeToolPresentation(),
        max_tool_calls_per_turn=1,
    )

    await dialog.chat([{"role": "user", "content": "compare"}])

    assert dispatcher.calls == [("search_web", {"query": "one"})]
    final_messages = backend.raw_calls[1]["messages"]
    assert backend.raw_calls[1]["tools"] is None
    assert "budget" in final_messages[-1]["content"].lower()


@pytest.mark.asyncio
async def test_malformed_native_arguments_force_a_final_text_request():
    backend = FakeBackend(
        [
            _native_calls(("search_web", "{not-json")),
            _done("I could not run the search."),
        ]
    )
    dispatcher = FakeDispatcher([])
    dialog = ToolAwareDialog(
        backend,
        EventBus(),
        _registry(_tool()),
        dispatcher,
        NativeToolPresentation(),
        max_tool_calls_per_turn=3,
    )

    await dialog.chat(
        [{"role": "user", "content": "search"}], images_b64=["current-image"]
    )

    assert dispatcher.calls == []
    assert backend.raw_calls[1]["tools"] is None
    assert backend.raw_calls[0]["images_b64"] == ["current-image"]
    assert backend.raw_calls[1]["images_b64"] is None
    assert "malformed" in backend.raw_calls[1]["messages"][-1]["content"].lower()


@pytest.mark.asyncio
async def test_native_json_encoded_arguments_are_decoded_before_dispatch():
    backend = FakeBackend(
        [
            _native_calls(("search_web", '{"query":"weather"}')),
            _done("Result."),
        ]
    )
    dispatcher = FakeDispatcher(
        [ToolDispatchResult(ok=True, correlation_id="1", content="sunny")]
    )
    dialog = ToolAwareDialog(
        backend,
        EventBus(),
        _registry(_tool()),
        dispatcher,
        NativeToolPresentation(),
        max_tool_calls_per_turn=3,
    )

    await dialog.chat([{"role": "user", "content": "search"}])

    assert dispatcher.calls == [("search_web", {"query": "weather"})]


@pytest.mark.asyncio
async def test_tool_failure_forces_final_answer_without_more_tools():
    backend = FakeBackend(
        [
            _native_calls(("search_web", {"query": "weather"})),
            _done("Search failed, so I cannot confirm."),
        ]
    )
    dispatcher = FakeDispatcher(
        [ToolDispatchResult(ok=False, correlation_id="1", error="provider down")]
    )
    dialog = ToolAwareDialog(
        backend,
        EventBus(),
        _registry(_tool()),
        dispatcher,
        NativeToolPresentation(),
        max_tool_calls_per_turn=3,
    )

    await dialog.chat([{"role": "user", "content": "weather?"}])

    assert len(dispatcher.calls) == 1
    assert backend.raw_calls[1]["tools"] is None
    assert "provider down" in backend.raw_calls[1]["messages"][-2]["content"]


@pytest.mark.asyncio
async def test_tool_failure_skips_later_calls_from_the_same_model_response():
    backend = FakeBackend(
        [
            _native_calls(
                ("search_web", {"query": "first"}),
                ("search_web", {"query": "must not run"}),
            ),
            _done("The first call failed; the second was not executed."),
        ]
    )
    dispatcher = FakeDispatcher(
        [ToolDispatchResult(ok=False, correlation_id="1", error="provider down")]
    )
    dialog = ToolAwareDialog(
        backend,
        EventBus(),
        _registry(_tool()),
        dispatcher,
        NativeToolPresentation(),
        max_tool_calls_per_turn=3,
    )

    await dialog.chat([{"role": "user", "content": "run both"}])

    assert dispatcher.calls == [("search_web", {"query": "first"})]
    final_messages = backend.raw_calls[1]["messages"]
    assert "provider down" in final_messages[-3]["content"]
    assert "not executed" in final_messages[-2]["content"]
    assert backend.raw_calls[1]["tools"] is None


@pytest.mark.asyncio
async def test_prompt_strategy_parses_tool_call_then_only_publishes_final_answer():
    bus = EventBus()
    tokens: list[str] = []
    bus.subscribe(ResponseToken, _append_token(tokens))
    backend = FakeBackend(
        [
            _done(
                '{"tool_call":{"name":"search_web","arguments":{"query":"weather"}}}'
            ),
            _done('{"final_answer":"It is sunny."}'),
        ]
    )
    dispatcher = FakeDispatcher(
        [ToolDispatchResult(ok=True, correlation_id="1", content="sunny")]
    )
    dialog = ToolAwareDialog(
        backend,
        bus,
        _registry(_tool()),
        dispatcher,
        PromptToolPresentation(),
        max_tool_calls_per_turn=3,
    )

    await dialog.chat([{"role": "user", "content": "weather?"}])

    assert tokens == ["It is sunny."]
    assert dispatcher.calls == [("search_web", {"query": "weather"})]
    assert backend.raw_calls[0]["tools"] is None
    assert "Available tools" in backend.raw_calls[0]["messages"][-2]["content"]
    assert backend.raw_calls[1]["messages"][-1]["role"] == "user"


@pytest.mark.asyncio
async def test_malformed_prompt_output_gets_one_forced_final_request():
    bus = EventBus()
    tokens: list[str] = []
    bus.subscribe(ResponseToken, _append_token(tokens))
    backend = FakeBackend(
        [_done("not json"), _done('{"final_answer":"I cannot call the tool."}')]
    )
    dialog = ToolAwareDialog(
        backend,
        bus,
        _registry(_tool()),
        FakeDispatcher([]),
        PromptToolPresentation(),
        max_tool_calls_per_turn=3,
    )

    await dialog.chat([{"role": "user", "content": "search"}])

    assert len(backend.raw_calls) == 2
    assert "malformed" in backend.raw_calls[1]["messages"][-1]["content"].lower()
    assert tokens == ["I cannot call the tool."]


@pytest.mark.asyncio
async def test_model_cannot_extend_loop_by_ignoring_forced_final_request():
    bus = EventBus()
    tokens: list[str] = []
    bus.subscribe(ResponseToken, _append_token(tokens))
    backend = FakeBackend(
        [
            _native_calls(("search_web", {"query": "one"})),
            _native_calls(("search_web", {"query": "ignored"})),
        ]
    )
    dispatcher = FakeDispatcher(
        [ToolDispatchResult(ok=True, correlation_id="1", content="first")]
    )
    dialog = ToolAwareDialog(
        backend,
        bus,
        _registry(_tool()),
        dispatcher,
        NativeToolPresentation(),
        max_tool_calls_per_turn=1,
    )

    await dialog.chat([{"role": "user", "content": "search"}])

    assert len(backend.raw_calls) == 2
    assert len(dispatcher.calls) == 1
    assert tokens == ["Не удалось завершить ответ после вызова инструмента."]


@pytest.mark.asyncio
async def test_stream_without_done_still_completes_final_turn_once():
    bus = EventBus()
    completions: list[ResponseComplete] = []
    bus.subscribe(ResponseComplete, _append_completion(completions))
    backend = FakeBackend([[{"message": {"content": "answer"}}]])
    dialog = ToolAwareDialog(
        backend,
        bus,
        _registry(_tool()),
        FakeDispatcher([]),
        NativeToolPresentation(),
        max_tool_calls_per_turn=3,
    )

    await dialog.chat([{"role": "user", "content": "hello"}])

    assert completions == [ResponseComplete(metrics=LatencyMetrics(0.0, 0.0, 0.0, 0))]
