"""Model-facing tool declarations and bounded current-turn tool loop."""

import json
import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol

from jarvis.core.bus import EventBus
from jarvis.dialog.backend import (
    LatencyMetrics,
    ResponseComplete,
    ResponseToken,
    parse_metrics,
)
from jarvis.dialog.thinking_mode import ReasoningLevel
from jarvis.tools.interception import ToolDispatchResult
from jarvis.tools.json_types import JSONObject
from jarvis.tools.registry import RegisteredTool, ToolRegistry

logger = logging.getLogger(__name__)

_FALLBACK_FINAL_TEXT = "Не удалось завершить ответ после вызова инструмента."
_SKIPPED_AFTER_FAILURE = (
    "Skipped because an earlier tool call failed; this call was not executed."
)

Message = dict[str, object]
ToolPayload = dict[str, object]


class DialogTransport(Protocol):
    async def chat(
        self,
        messages: Sequence[Message],
        images_b64: Sequence[str] | None = None,
        reasoning_level: ReasoningLevel = ReasoningLevel.OFF,
    ) -> None: ...

    def iter_chat(
        self,
        messages: Sequence[Message],
        images_b64: Sequence[str] | None = None,
        reasoning_level: ReasoningLevel = ReasoningLevel.OFF,
        tools: Sequence[ToolPayload] | None = None,
    ) -> AsyncIterator[dict[str, object]]: ...


class ToolCallDispatcher(Protocol):
    async def dispatch(
        self, tool_name: str, arguments: JSONObject
    ) -> ToolDispatchResult: ...


@dataclass(frozen=True)
class PreparedPresentation:
    tools: list[ToolPayload] | None
    prompt_suffix: str | None


@dataclass(frozen=True)
class ParsedToolCall:
    name: str
    arguments: JSONObject | None
    error: str | None = None


@dataclass(frozen=True)
class ParsedResponse:
    assistant_message: Message
    content_chunks: tuple[str, ...]
    metrics: LatencyMetrics
    content_published: bool


class ToolPresentation(Protocol):
    streams_plain_text: bool

    def prepare(self, tools: Sequence[RegisteredTool]) -> PreparedPresentation: ...

    def parse(
        self, assistant_message: Message, content_chunks: Sequence[str]
    ) -> tuple[tuple[ParsedToolCall, ...], str | None, str | None]: ...

    def result_message(self, result: ToolDispatchResult) -> Message: ...

    def error_message(self, error: str) -> Message: ...


class NativeToolPresentation:
    streams_plain_text = True

    def prepare(self, tools: Sequence[RegisteredTool]) -> PreparedPresentation:
        return PreparedPresentation(
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.schema,
                    },
                }
                for tool in tools
            ],
            prompt_suffix=None,
        )

    def parse(
        self, assistant_message: Message, content_chunks: Sequence[str]
    ) -> tuple[tuple[ParsedToolCall, ...], str | None, str | None]:
        raw_calls = assistant_message.get("tool_calls")
        if raw_calls is None:
            return (), "".join(content_chunks), None
        if not isinstance(raw_calls, list) or not raw_calls:
            return (), None, "malformed native tool_calls value"
        return tuple(_parse_native_call(raw_call) for raw_call in raw_calls), None, None

    def result_message(self, result: ToolDispatchResult) -> Message:
        return {"role": "tool", "content": _serialize_result(result)}

    def error_message(self, error: str) -> Message:
        return {"role": "tool", "content": _serialize_error(error)}


class PromptToolPresentation:
    streams_plain_text = False

    def prepare(self, tools: Sequence[RegisteredTool]) -> PreparedPresentation:
        declarations = [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.schema,
            }
            for tool in tools
        ]
        prompt = (
            "Available tools:\n"
            + json.dumps(declarations, ensure_ascii=False, separators=(",", ":"))
            + "\nReply with exactly one JSON object and no Markdown. "
            'Use {"tool_call":{"name":"<tool>","arguments":{...}}} to call '
            'one tool, or {"final_answer":"<answer>"} to answer.'
        )
        return PreparedPresentation(tools=None, prompt_suffix=prompt)

    def parse(
        self, assistant_message: Message, content_chunks: Sequence[str]
    ) -> tuple[tuple[ParsedToolCall, ...], str | None, str | None]:
        raw_text = "".join(content_chunks).strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.strip("`")
            if raw_text.lower().startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()
        try:
            value = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            return (), None, f"malformed prompt tool response: {exc}"
        if not isinstance(value, dict):
            return (), None, "malformed prompt tool response: expected an object"
        if "tool_call" in value:
            return (_parse_prompt_call(value["tool_call"]),), None, None
        answer = value.get("final_answer")
        if isinstance(answer, str):
            return (), answer, None
        return (), None, "malformed prompt tool response: missing final_answer"

    def result_message(self, result: ToolDispatchResult) -> Message:
        return {
            "role": "user",
            "content": (
                f"Tool result: {_serialize_result(result)}\n"
                "Respond again following the exact same JSON contract."
            ),
        }

    def error_message(self, error: str) -> Message:
        return {
            "role": "user",
            "content": (
                f"Tool error: {_serialize_error(error)}\n"
                "Respond again following the exact same JSON contract."
            ),
        }


def build_tool_presentation(name: str) -> ToolPresentation:
    if name == "native":
        return NativeToolPresentation()
    if name == "prompt":
        return PromptToolPresentation()
    raise ValueError(f"Unsupported tool presentation strategy: {name!r}")


class ToolAwareDialog:
    """Decorates the transport with model presentation and bounded dispatch."""

    def __init__(
        self,
        backend: DialogTransport,
        bus: EventBus,
        registry: ToolRegistry,
        dispatcher: ToolCallDispatcher,
        presentation: ToolPresentation,
        max_tool_calls_per_turn: int,
    ) -> None:
        self._backend = backend
        self._bus = bus
        self._registry = registry
        self._dispatcher = dispatcher
        self._presentation = presentation
        self._max_tool_calls = max_tool_calls_per_turn

    async def chat(
        self,
        messages: Sequence[Message],
        images_b64: Sequence[str] | None = None,
        reasoning_level: ReasoningLevel = ReasoningLevel.OFF,
    ) -> None:
        tools = tuple(tool for tool in self._registry.all() if tool.enabled)
        if not tools:
            await self._backend.chat(messages, images_b64, reasoning_level)
            return

        prepared = self._presentation.prepare(tools)
        current_messages = [dict(message) for message in messages]
        if images_b64:
            # Ollama's /api/chat is stateless. Keep current-turn media on
            # the original user message so every tool-result/forced-final
            # follow-up retains the request that caused the tool call.
            # This list is local to the loop and never reaches
            # ConversationHistory.
            current_messages[-1]["images"] = list(images_b64)
        if prepared.prompt_suffix is not None:
            current_messages.insert(
                max(0, len(current_messages) - 1),
                {"role": "system", "content": prepared.prompt_suffix},
            )

        calls_used = 0
        force_text = False
        while True:
            response = await self._read_response(
                current_messages,
                None,
                reasoning_level,
                None if force_text else prepared.tools,
            )
            calls, final_text, format_error = self._presentation.parse(
                response.assistant_message, response.content_chunks
            )
            if force_text:
                answer = (
                    final_text
                    if format_error is None and not calls and final_text
                    else _FALLBACK_FINAL_TEXT
                )
                await self._publish_final(response, answer)
                return
            if format_error is not None:
                current_messages.extend(
                    _forced_answer_context(response.assistant_message, format_error)
                )
                force_text = True
                continue
            if not calls:
                await self._publish_final(response, final_text)
                return

            current_messages.append(response.assistant_message)
            calls_used, stop_reason = await self._dispatch_calls(
                calls, calls_used, current_messages
            )

            if calls_used >= self._max_tool_calls:
                stop_reason = stop_reason or "Tool call budget exhausted."
            if stop_reason is not None:
                current_messages.append(
                    {
                        "role": "system",
                        "content": (
                            f"{stop_reason} Produce a final text answer now. "
                            "Do not request another tool."
                        ),
                    }
                )
                force_text = True

    async def _dispatch_calls(
        self,
        calls: Sequence[ParsedToolCall],
        calls_used: int,
        messages: list[Message],
    ) -> tuple[int, str | None]:
        stop_reason: str | None = None
        for index, call in enumerate(calls):
            if calls_used >= self._max_tool_calls:
                stop_reason = "Tool call budget exhausted; no further calls ran."
                messages.append(self._presentation.error_message(stop_reason))
                continue
            if call.error is not None or call.arguments is None:
                stop_reason = call.error or "Malformed tool arguments."
                messages.append(self._presentation.error_message(stop_reason))
                continue
            result = await self._dispatcher.dispatch(call.name, call.arguments)
            calls_used += 1
            messages.append(self._presentation.result_message(result))
            if result.images_b64:
                current_user_message = next(
                    (
                        message
                        for message in reversed(messages)
                        if message.get("role") == "user"
                    ),
                    None,
                )
                if current_user_message is not None:
                    current_images = current_user_message.setdefault("images", [])
                    if isinstance(current_images, list):
                        current_images.extend(result.images_b64)
            if not result.ok:
                stop_reason = result.error or "Tool call failed."
                for _ in calls[index + 1 :]:
                    messages.append(
                        self._presentation.error_message(_SKIPPED_AFTER_FAILURE)
                    )
                break
        return calls_used, stop_reason

    async def _read_response(
        self,
        messages: Sequence[Message],
        images_b64: Sequence[str] | None,
        reasoning_level: ReasoningLevel,
        tools: Sequence[ToolPayload] | None,
    ) -> ParsedResponse:
        content_chunks: list[str] = []
        assistant_message: Message = {"role": "assistant", "content": ""}
        response_mode = "buffered" if not self._presentation.streams_plain_text else ""
        content_published = False
        saw_done = False
        metrics = LatencyMetrics(0.0, 0.0, 0.0, 0)
        async for chunk in self._backend.iter_chat(
            messages, images_b64, reasoning_level, tools
        ):
            message = chunk.get("message")
            if isinstance(message, dict):
                response_mode, published = await _consume_message(
                    message,
                    assistant_message,
                    content_chunks,
                    response_mode,
                    self._bus,
                )
                content_published = content_published or published
            if chunk.get("done") is True:
                saw_done = True
                metrics = parse_metrics(chunk)
        assistant_message["content"] = "".join(content_chunks)
        if not saw_done:
            logger.warning("Ollama stream ended without a done:true chunk")
        return ParsedResponse(
            assistant_message, tuple(content_chunks), metrics, content_published
        )

    async def _publish_final(
        self, response: ParsedResponse, final_text: str | None
    ) -> None:
        if final_text and not response.content_published:
            chunks = (
                response.content_chunks
                if self._presentation.streams_plain_text
                and "".join(response.content_chunks) == final_text
                else (final_text,)
            )
            for chunk in chunks:
                await self._bus.publish(ResponseToken, ResponseToken(text=chunk))
        await self._bus.publish(
            ResponseComplete, ResponseComplete(metrics=response.metrics)
        )


async def _consume_message(
    message: dict[object, object],
    assistant_message: Message,
    content_chunks: list[str],
    response_mode: str,
    bus: EventBus,
) -> tuple[str, bool]:
    raw_calls = message.get("tool_calls")
    has_calls = isinstance(raw_calls, list) and bool(raw_calls)
    if response_mode == "" and has_calls:
        response_mode = "tool"
    content = message.get("content")
    published = False
    if isinstance(content, str) and content:
        content_chunks.append(content)
        if response_mode == "":
            response_mode = "text"
        if response_mode == "text":
            await bus.publish(ResponseToken, ResponseToken(text=content))
            published = True
    if isinstance(raw_calls, list) and raw_calls and response_mode != "text":
        accumulated = assistant_message.setdefault("tool_calls", [])
        if isinstance(accumulated, list):
            accumulated.extend(raw_calls)
    elif has_calls:
        logger.warning("Ignoring native tool calls that arrived after answer text")
    return response_mode, published


def _parse_native_call(value: object) -> ParsedToolCall:
    if not isinstance(value, dict):
        return ParsedToolCall("", None, "Malformed native tool call.")
    function = value.get("function")
    if not isinstance(function, dict):
        return ParsedToolCall("", None, "Malformed native tool function.")
    name = function.get("name")
    if not isinstance(name, str) or not name:
        return ParsedToolCall("", None, "Malformed native tool name.")
    return _call_with_arguments(name, function.get("arguments", {}), "native")


def _parse_prompt_call(value: object) -> ParsedToolCall:
    if not isinstance(value, dict):
        return ParsedToolCall("", None, "Malformed prompt tool call.")
    name = value.get("name")
    if not isinstance(name, str) or not name:
        return ParsedToolCall("", None, "Malformed prompt tool name.")
    return _call_with_arguments(name, value.get("arguments", {}), "prompt")


def _call_with_arguments(name: str, value: object, source: str) -> ParsedToolCall:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return ParsedToolCall(name, None, f"Malformed {source} tool arguments.")
    if not isinstance(value, dict):
        return ParsedToolCall(name, None, f"Malformed {source} tool arguments.")
    return ParsedToolCall(name, value)


def _serialize_result(result: ToolDispatchResult) -> str:
    payload = {
        "ok": result.ok,
        "content": result.content,
        "structured_content": result.structured_content,
        "error": result.error,
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def _serialize_error(error: str) -> str:
    return json.dumps({"ok": False, "error": error}, ensure_ascii=False)


def _forced_answer_context(assistant_message: Message, error: str) -> list[Message]:
    return [
        assistant_message,
        {
            "role": "system",
            "content": (
                f"{error}. Produce a final text answer now. "
                "Do not request another tool."
            ),
        },
    ]
