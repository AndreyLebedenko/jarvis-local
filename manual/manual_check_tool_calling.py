#!/usr/bin/env python3
"""Manual handoff for story-v1.4.0 task 1: tool-calling reliability spike.

Measures how reliably the configured local model calls tools through two
presentation strategies on a fixed task set:

  - native: Ollama's `tools` field in `/api/chat` (OpenAI-style function
    schema), reusing OllamaBackend.build_payload() for the model/messages/
    options shape - the same payload production turns send, plus `tools`.
  - prompt: tool declarations in the system prompt, a strict single-JSON-
    object reply contract (`{"tool_call": {...}}` or `{"final_answer":
    ...}`), parsed and validated by hand.

This is not an automated test: it talks to the live local Ollama endpoint,
so the human runs it and reports the output. No MCP dependency and no
engine integration - hardcoded fake tool schemas only. See
tasks/story-v1.4.0-task-1-tool-calling-spike.md.

Spike-only simplification: every request uses `stream: false` so a
tool_calls/JSON reply can be read from one response object instead of
reassembled from streamed deltas. Production streaming behavior during a
tool-calling turn is out of scope here - task 4's job.

Usage:
  python -m manual.manual_check_tool_calling
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Literal

import httpx

from jarvis.core.bus import EventBus
from jarvis.core.config import load_settings
from jarvis.dialog.backend import OllamaBackend
from jarvis.dialog.thinking_mode import ReasoningLevel

Strategy = Literal["native", "prompt"]
ParamType = Literal["string", "integer", "boolean"]

STRATEGIES: tuple[Strategy, ...] = ("native", "prompt")
RUNS_PER_SCENARIO = 3


@dataclass(frozen=True)
class ToolParam:
    name: str
    type: ParamType
    required: bool = True
    enum: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    params: tuple[ToolParam, ...]


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="get_weather",
        description="Get current weather conditions for a city.",
        params=(
            ToolParam("city", "string"),
            ToolParam("units", "string", enum=("metric", "imperial")),
        ),
    ),
    ToolSpec(
        name="search_web",
        description="Search the web for a query and return the top results.",
        params=(
            ToolParam("query", "string"),
            ToolParam("max_results", "integer", required=False),
        ),
    ),
)
TOOLS_BY_NAME: dict[str, ToolSpec] = {tool.name: tool for tool in TOOLS}


@dataclass(frozen=True)
class Scenario:
    key: str
    prompt: str
    expected_tool: str | None
    two_step: bool = False


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "single_call_ru",
        "Какая погода в Берлине? Хочу в метрических единицах.",
        "get_weather",
    ),
    Scenario(
        "single_call_en",
        "What's the weather like in Berlin? I want it in metric units.",
        "get_weather",
    ),
    Scenario(
        "no_tool_needed",
        "In one sentence, explain what a recursive function is.",
        None,
    ),
    Scenario(
        "tool_choice",
        "Find the latest news about the James Webb Space Telescope.",
        "search_web",
    ),
    Scenario(
        # get_weather has no date/forecast field - this pressures the model
        # to either answer the extra part in prose or invent a schema-
        # violating argument, which is the malformed-output signal this
        # scenario exists to measure.
        "ambiguous_args",
        "What will the weather be like in Tokyo three days from now, and "
        "is it likely to rain?",
        "get_weather",
    ),
    Scenario(
        "two_step_final_answer",
        "What's the weather in Berlin? I want it in metric units.",
        "get_weather",
        two_step=True,
    ),
)


# --- Native strategy: schema + parsing -------------------------------------


def native_tool_schema(spec: ToolSpec) -> dict[str, object]:
    properties: dict[str, object] = {}
    required: list[str] = []
    for param in spec.params:
        prop: dict[str, object] = {"type": param.type}
        if param.enum:
            prop["enum"] = list(param.enum)
        properties[param.name] = prop
        if param.required:
            required.append(param.name)
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


NATIVE_TOOLS: list[dict[str, object]] = [native_tool_schema(spec) for spec in TOOLS]


@dataclass
class ParsedCall:
    name: str
    arguments: dict[str, object]


def parse_native_tool_calls(message: dict[str, object]) -> list[ParsedCall]:
    calls = message.get("tool_calls")
    if not isinstance(calls, list):
        return []
    parsed: list[ParsedCall] = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        if isinstance(name, str):
            parsed.append(ParsedCall(name=name, arguments=arguments))
    return parsed


# --- Prompt strategy: declaration + reply contract --------------------------


def prompt_tool_declaration(specs: tuple[ToolSpec, ...]) -> str:
    lines = ["Available tools:"]
    for spec in specs:
        params = ", ".join(
            f"{p.name}: {p.type}"
            + (f" (one of {list(p.enum)})" if p.enum else "")
            + ("" if p.required else ", optional")
            for p in spec.params
        )
        lines.append(f"- {spec.name}({params}): {spec.description}")
    return "\n".join(lines)


PROMPT_STRATEGY_SYSTEM_PROMPT = (
    "You are a careful assistant that can call external tools. Answer briefly.\n\n"
    + prompt_tool_declaration(TOOLS)
    + "\n\nReply with exactly one JSON object, nothing else, no markdown fences.\n"
    'To call a tool: {"tool_call": {"name": "<tool name>", "arguments": {...}}}\n'
    'To answer without a tool: {"final_answer": "<answer text>"}'
)


@dataclass
class PromptReply:
    tool_call: ParsedCall | None
    final_answer: str | None
    format_error: str | None


def parse_prompt_reply(text: str) -> PromptReply:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
        stripped = stripped.strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        return PromptReply(None, None, f"invalid JSON: {exc}")
    if not isinstance(data, dict):
        return PromptReply(None, None, "top-level JSON value is not an object")
    if "tool_call" in data:
        call = data["tool_call"]
        if not isinstance(call, dict) or not isinstance(call.get("name"), str):
            return PromptReply(None, None, "tool_call missing string 'name'")
        arguments = call.get("arguments", {})
        if not isinstance(arguments, dict):
            return PromptReply(None, None, "tool_call 'arguments' is not an object")
        return PromptReply(
            ParsedCall(name=call["name"], arguments=arguments), None, None
        )
    if "final_answer" in data:
        answer = data["final_answer"]
        if not isinstance(answer, str):
            return PromptReply(None, None, "final_answer is not a string")
        return PromptReply(None, answer, None)
    return PromptReply(
        None, None, "JSON object has neither 'tool_call' nor 'final_answer'"
    )


# --- Shared: argument schema validation --------------------------------------


def _matches_type(value: object, type_name: ParamType) -> bool:
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "boolean":
        return isinstance(value, bool)
    return False


def validate_arguments(spec: ToolSpec, arguments: dict[str, object]) -> list[str]:
    errors: list[str] = []
    known = {p.name: p for p in spec.params}
    for name, param in known.items():
        if param.required and name not in arguments:
            errors.append(f"missing required argument '{name}'")
    for name, value in arguments.items():
        param = known.get(name)
        if param is None:
            errors.append(f"unexpected argument '{name}'")
            continue
        if not _matches_type(value, param.type):
            errors.append(
                f"argument '{name}' has wrong type: expected {param.type}, "
                f"got {type(value).__name__}"
            )
        elif param.enum and value not in param.enum:
            errors.append(
                f"argument '{name}' value {value!r} not in {list(param.enum)}"
            )
    return errors


def fake_tool_result(call: ParsedCall) -> dict[str, object]:
    if call.name == "get_weather":
        return {
            "city": call.arguments.get("city", "Berlin"),
            "temperature": 18,
            "condition": "cloudy",
        }
    if call.name == "search_web":
        return {
            "results": [{"title": "Example result", "url": "https://example.invalid/1"}]
        }
    return {"ok": True}


# --- Outcome classification (pure) -------------------------------------------


@dataclass
class SecondHopOutcome:
    ran: bool
    final_answer_present: bool
    spurious_tool_call: bool
    format_error: str | None
    transport_error: str | None = None


@dataclass
class ScenarioOutcome:
    strategy: Strategy
    scenario_key: str
    run_index: int
    wall_seconds: float
    expected_tool: str | None
    tool_called: str | None
    arguments: dict[str, object] | None
    validation_errors: list[str] = field(default_factory=list)
    final_answer_text: str | None = None
    format_error: str | None = None
    transport_error: str | None = None
    second_hop: SecondHopOutcome | None = None


def classify_outcome(
    scenario: Scenario,
    strategy: Strategy,
    run_index: int,
    wall_seconds: float,
    tool_called: str | None,
    arguments: dict[str, object] | None,
    final_answer_text: str | None,
    format_error: str | None,
    transport_error: str | None = None,
) -> ScenarioOutcome:
    validation_errors: list[str] = []
    if tool_called is not None:
        spec = TOOLS_BY_NAME.get(tool_called)
        if spec is None:
            validation_errors.append(f"unknown tool name '{tool_called}'")
        else:
            validation_errors.extend(validate_arguments(spec, arguments or {}))
    return ScenarioOutcome(
        strategy=strategy,
        scenario_key=scenario.key,
        run_index=run_index,
        wall_seconds=wall_seconds,
        expected_tool=scenario.expected_tool,
        tool_called=tool_called,
        arguments=arguments,
        validation_errors=validation_errors,
        final_answer_text=final_answer_text,
        format_error=format_error,
        transport_error=transport_error,
    )


def correct_tool_choice(outcome: ScenarioOutcome) -> bool:
    return outcome.tool_called == outcome.expected_tool


def is_false_positive(outcome: ScenarioOutcome) -> bool:
    return outcome.expected_tool is None and outcome.tool_called is not None


def is_missed_call(outcome: ScenarioOutcome) -> bool:
    return outcome.expected_tool is not None and outcome.tool_called is None


@dataclass
class StrategySummary:
    strategy: Strategy
    correct_call_rate: float
    false_positive_rate: float
    schema_validity_rate: float
    format_error_rate: float
    two_step_no_spurious_call_rate: float | None


def summarize(outcomes: list[ScenarioOutcome]) -> dict[Strategy, StrategySummary]:
    summaries: dict[Strategy, StrategySummary] = {}
    for strategy in STRATEGIES:
        rows = [o for o in outcomes if o.strategy == strategy]
        expecting_call = [o for o in rows if o.expected_tool is not None]
        not_expecting_call = [o for o in rows if o.expected_tool is None]
        calls_made = [o for o in rows if o.tool_called is not None]
        two_step_rows = [
            o for o in rows if o.second_hop is not None and o.second_hop.ran
        ]

        correct_call_rate = (
            sum(1 for o in expecting_call if correct_tool_choice(o))
            / len(expecting_call)
            if expecting_call
            else float("nan")
        )
        false_positive_rate = (
            sum(1 for o in not_expecting_call if o.tool_called is not None)
            / len(not_expecting_call)
            if not_expecting_call
            else float("nan")
        )
        schema_validity_rate = (
            sum(1 for o in calls_made if not o.validation_errors) / len(calls_made)
            if calls_made
            else float("nan")
        )
        format_error_rate = (
            sum(
                1
                for o in rows
                if o.format_error is not None or o.transport_error is not None
            )
            / len(rows)
            if rows
            else float("nan")
        )
        two_step_rate = (
            sum(
                1
                for o in two_step_rows
                if o.second_hop.final_answer_present
                and not o.second_hop.spurious_tool_call
            )
            / len(two_step_rows)
            if two_step_rows
            else None
        )
        summaries[strategy] = StrategySummary(
            strategy=strategy,
            correct_call_rate=correct_call_rate,
            false_positive_rate=false_positive_rate,
            schema_validity_rate=schema_validity_rate,
            format_error_rate=format_error_rate,
            two_step_no_spurious_call_rate=two_step_rate,
        )
    return summaries


# --- Network glue -------------------------------------------------------------


async def call_ollama(
    client: httpx.AsyncClient, payload: dict[str, object]
) -> dict[str, object]:
    response = await client.post("/api/chat", json=payload)
    if response.status_code >= 400:
        raise httpx.HTTPStatusError(
            f"{response.status_code} {response.reason_phrase}: {response.text}",
            request=response.request,
            response=response,
        )
    return response.json()


async def run_native_scenario(
    client: httpx.AsyncClient,
    backend: OllamaBackend,
    scenario: Scenario,
    run_index: int,
) -> ScenarioOutcome:
    messages: list[dict[str, object]] = [{"role": "user", "content": scenario.prompt}]
    payload = backend.build_payload(messages, reasoning_level=ReasoningLevel.OFF)
    payload["tools"] = NATIVE_TOOLS
    payload["stream"] = False

    t0 = time.perf_counter()
    tool_called: str | None = None
    arguments: dict[str, object] | None = None
    final_answer_text: str | None = None
    format_error: str | None = None
    transport_error: str | None = None
    calls: list[ParsedCall] = []
    message: dict[str, object] = {}
    try:
        data = await call_ollama(client, payload)
        message = data.get("message", {})
        calls = parse_native_tool_calls(message)
        if calls:
            tool_called = calls[0].name
            arguments = calls[0].arguments
            if len(calls) > 1:
                format_error = f"model requested {len(calls)} tool calls in one turn"
        else:
            content = message.get("content")
            final_answer_text = content if isinstance(content, str) else None
    except httpx.HTTPError as exc:
        transport_error = str(exc)
    wall_seconds = time.perf_counter() - t0

    outcome = classify_outcome(
        scenario,
        "native",
        run_index,
        wall_seconds,
        tool_called,
        arguments,
        final_answer_text,
        format_error,
        transport_error,
    )
    if scenario.two_step and transport_error is None:
        outcome.second_hop = await run_native_second_hop(
            client, backend, messages, message, calls
        )
    return outcome


async def run_native_second_hop(
    client: httpx.AsyncClient,
    backend: OllamaBackend,
    prior_messages: list[dict[str, object]],
    assistant_message: dict[str, object],
    calls: list[ParsedCall],
) -> SecondHopOutcome:
    if not calls:
        return SecondHopOutcome(
            ran=False,
            final_answer_present=False,
            spurious_tool_call=False,
            format_error=None,
        )
    tool_result = fake_tool_result(calls[0])
    messages = [
        *prior_messages,
        assistant_message,
        {"role": "tool", "content": json.dumps(tool_result)},
    ]
    payload = backend.build_payload(messages, reasoning_level=ReasoningLevel.OFF)
    payload["tools"] = NATIVE_TOOLS
    payload["stream"] = False
    try:
        data = await call_ollama(client, payload)
        message = data.get("message", {})
        second_calls = parse_native_tool_calls(message)
        content = message.get("content")
        return SecondHopOutcome(
            ran=True,
            final_answer_present=isinstance(content, str)
            and bool(content.strip())
            and not second_calls,
            spurious_tool_call=bool(second_calls),
            format_error=None,
        )
    except httpx.HTTPError as exc:
        return SecondHopOutcome(
            ran=True,
            final_answer_present=False,
            spurious_tool_call=False,
            format_error=None,
            transport_error=str(exc),
        )


async def run_prompt_scenario(
    client: httpx.AsyncClient,
    backend: OllamaBackend,
    scenario: Scenario,
    run_index: int,
) -> ScenarioOutcome:
    messages: list[dict[str, object]] = [
        {"role": "system", "content": PROMPT_STRATEGY_SYSTEM_PROMPT},
        {"role": "user", "content": scenario.prompt},
    ]
    payload = backend.build_payload(messages, reasoning_level=ReasoningLevel.OFF)
    payload["stream"] = False

    t0 = time.perf_counter()
    tool_called: str | None = None
    arguments: dict[str, object] | None = None
    final_answer_text: str | None = None
    format_error: str | None = None
    transport_error: str | None = None
    reply: PromptReply | None = None
    content = ""
    try:
        data = await call_ollama(client, payload)
        content = data.get("message", {}).get("content", "")
        reply = parse_prompt_reply(content)
        format_error = reply.format_error
        if reply.tool_call is not None:
            tool_called = reply.tool_call.name
            arguments = reply.tool_call.arguments
        elif reply.final_answer is not None:
            final_answer_text = reply.final_answer
    except httpx.HTTPError as exc:
        transport_error = str(exc)
    wall_seconds = time.perf_counter() - t0

    outcome = classify_outcome(
        scenario,
        "prompt",
        run_index,
        wall_seconds,
        tool_called,
        arguments,
        final_answer_text,
        format_error,
        transport_error,
    )
    if scenario.two_step and transport_error is None and reply is not None:
        outcome.second_hop = await run_prompt_second_hop(
            client, backend, messages, content, reply
        )
    return outcome


async def run_prompt_second_hop(
    client: httpx.AsyncClient,
    backend: OllamaBackend,
    prior_messages: list[dict[str, object]],
    assistant_raw_text: str,
    reply: PromptReply,
) -> SecondHopOutcome:
    if reply.tool_call is None:
        return SecondHopOutcome(
            ran=False,
            final_answer_present=False,
            spurious_tool_call=False,
            format_error=None,
        )
    tool_result = fake_tool_result(reply.tool_call)
    messages = [
        *prior_messages,
        {"role": "assistant", "content": assistant_raw_text},
        {
            "role": "user",
            "content": (
                "Tool result: "
                + json.dumps(tool_result)
                + "\nRespond again following the exact same JSON contract."
            ),
        },
    ]
    payload = backend.build_payload(messages, reasoning_level=ReasoningLevel.OFF)
    payload["stream"] = False
    try:
        data = await call_ollama(client, payload)
        content = data.get("message", {}).get("content", "")
        second_reply = parse_prompt_reply(content)
        return SecondHopOutcome(
            ran=True,
            final_answer_present=second_reply.final_answer is not None,
            spurious_tool_call=second_reply.tool_call is not None,
            format_error=second_reply.format_error,
        )
    except httpx.HTTPError as exc:
        return SecondHopOutcome(
            ran=True,
            final_answer_present=False,
            spurious_tool_call=False,
            format_error=None,
            transport_error=str(exc),
        )


# --- Reporting -----------------------------------------------------------------


async def ollama_version(client: httpx.AsyncClient) -> str:
    try:
        response = await client.get("/api/version")
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return f"unavailable ({exc})"
    return str(response.json().get("version", "unknown"))


def print_outcome(outcome: ScenarioOutcome) -> None:
    header = f"{outcome.strategy} / {outcome.scenario_key} / run {outcome.run_index}"
    print(f"\n=== {header} ===")
    print(f"wall_seconds: {outcome.wall_seconds:.2f}")
    print(f"expected_tool: {outcome.expected_tool!r}")
    print(f"tool_called: {outcome.tool_called!r}")
    print(f"arguments: {outcome.arguments!r}")
    print(f"validation_errors: {outcome.validation_errors!r}")
    print(f"final_answer_text: {outcome.final_answer_text!r}")
    print(f"format_error: {outcome.format_error!r}")
    print(f"transport_error: {outcome.transport_error!r}")
    if outcome.second_hop is not None:
        hop = outcome.second_hop
        print(
            f"second_hop: ran={hop.ran} "
            f"final_answer_present={hop.final_answer_present} "
            f"spurious_tool_call={hop.spurious_tool_call} "
            f"format_error={hop.format_error!r} "
            f"transport_error={hop.transport_error!r}"
        )


def print_summary(summaries: dict[Strategy, StrategySummary]) -> None:
    print("\n\n=== SUMMARY ===")
    for strategy in STRATEGIES:
        summary = summaries[strategy]
        print(f"\n--- {strategy} ---")
        print(f"correct_call_rate: {summary.correct_call_rate:.2f}")
        print(f"false_positive_rate: {summary.false_positive_rate:.2f}")
        print(f"schema_validity_rate: {summary.schema_validity_rate:.2f}")
        print(f"format_error_rate: {summary.format_error_rate:.2f}")
        two_step = summary.two_step_no_spurious_call_rate
        print(
            "two_step_no_spurious_call_rate: "
            + (
                f"{two_step:.2f}"
                if two_step is not None
                else "n/a (no successful first hop)"
            )
        )


async def run() -> None:
    settings = load_settings()
    timeout = httpx.Timeout(10.0, read=settings.backend.read_timeout_seconds)
    async with httpx.AsyncClient(
        base_url=settings.backend.endpoint, timeout=timeout
    ) as client:
        backend = OllamaBackend(EventBus(), settings.backend, client=client)
        print(f"Ollama endpoint: {settings.backend.endpoint}")
        print(f"Ollama version: {await ollama_version(client)}")
        print(f"Model: {settings.backend.model}")

        outcomes: list[ScenarioOutcome] = []
        for strategy in STRATEGIES:
            runner = (
                run_native_scenario if strategy == "native" else run_prompt_scenario
            )
            for scenario in SCENARIOS:
                for run_index in range(1, RUNS_PER_SCENARIO + 1):
                    outcome = await runner(client, backend, scenario, run_index)
                    print_outcome(outcome)
                    outcomes.append(outcome)

        print_summary(summarize(outcomes))


if __name__ == "__main__":
    asyncio.run(run())
