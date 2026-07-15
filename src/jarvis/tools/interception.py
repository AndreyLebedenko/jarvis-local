"""The single interception point for every MCP tool call.

Per story-v1.4.0's Architecture position: "All tool calls flow through a
single interception point between 'model requested' and 'executed'."
Nothing else in the codebase may execute a tool - the model presentation
layer (task 4) calls ToolDispatcher.dispatch(), never an McpClient
directly. This is also where a later watchdog/policy component attaches
(tasks/backlog/mcp-egress-watchdog.md) without rewiring anything upstream.

ToolCallStarted/ToolCallFinished are the typed, correlated contract a
watchdog or task 5's audit view consumes - the paired SystemEvent (same
correlation_id) is the human-readable trace for the events panel, not the
source of truth: a consumer must never have to parse the localized
ui_message string to recover which tool, provider, or duration a call
involved.

enter_dispatch()/exit_dispatch() are McpHost's admission gate (review
round 2, finding 1): dispatch() must not be able to acquire a client
reference and start a call after McpHost has begun disable()'s teardown -
see host.py's module docstring for the full lifecycle contract.
on_transport_error() is McpHost's hook for a provider whose call_tool()
raised McpTransportError specifically (round 3 follow-up) - not just any
exception. mcp_client.py's McpTransportError boundary is deliberately
narrow: a normal protocol error or a single timed-out call surfaces from
the SDK as McpError and must only fail that one call, exactly like a
tool-reported isError result; only McpTransportError means the
underlying session/subprocess is suspect, which is what gets reported to
the host separately from the per-call ToolDispatchResult.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from jarvis.core.bus import EventBus
from jarvis.core.config import DataBoundary
from jarvis.core.system_log import publish_system_event
from jarvis.tools.json_types import JSONObject
from jarvis.tools.mcp_client import McpTransportError, ToolArguments, ToolCallResult
from jarvis.tools.registry import ToolRegistry, UnsupportedToolArguments
from jarvis.ui.contract import EventLevel
from jarvis.ui.text import DEFAULT_UI_LANGUAGE, ui_text

logger = logging.getLogger(__name__)

SOURCE = "MCP"


class _CallableClient(Protocol):
    async def call_tool(
        self, name: str, arguments: ToolArguments
    ) -> ToolCallResult: ...


@dataclass(frozen=True)
class ToolCallStarted:
    correlation_id: str
    tool_name: str
    provider: str
    arguments: ToolArguments
    outbound_summary: str
    timestamp: float
    data_boundary: DataBoundary = DataBoundary.UNKNOWN


@dataclass(frozen=True)
class ToolCallFinished:
    correlation_id: str
    tool_name: str
    provider: str | None
    outbound_summary: str
    duration_seconds: float
    ok: bool
    error: str | None
    data_boundary: DataBoundary = DataBoundary.UNKNOWN


@dataclass(frozen=True)
class ToolDispatchResult:
    ok: bool
    correlation_id: str
    content: object | None = None
    structured_content: JSONObject | None = None
    error: str | None = None


def summarize_outbound(provider: str, tool_name: str, arguments: ToolArguments) -> str:
    """User-readable statement of what is being sent and to which
    provider - task 3's acceptance criteria requires this on every call
    event: enough for the events panel, the "where does my data go"
    answer, and later watchdog rules (see tasks/backlog/
    mcp-egress-watchdog.md)."""
    args_text = ", ".join(
        f"{key}={value!r}" for key, value in sorted(arguments.items())
    )
    return f"{provider}.{tool_name}({args_text})"


class ToolDispatcher:
    def __init__(
        self,
        bus: EventBus,
        registry: ToolRegistry,
        get_client: Callable[[str], _CallableClient | None],
        enter_dispatch: Callable[[], bool],
        exit_dispatch: Callable[[], None],
        on_transport_error: Callable[[str, Exception], Awaitable[None]] | None = None,
        ui_language: str = DEFAULT_UI_LANGUAGE,
    ) -> None:
        """get_client is a callable, not a captured snapshot: McpHost's
        connected-clients set can change between dispatches (reconnect,
        toggle), and this must always see the live value."""
        self._bus = bus
        self._registry = registry
        self._get_client = get_client
        self._enter_dispatch = enter_dispatch
        self._exit_dispatch = exit_dispatch
        self._on_transport_error = on_transport_error
        self._ui_language = ui_language

    async def dispatch(
        self, tool_name: str, arguments: ToolArguments
    ) -> ToolDispatchResult:
        correlation_id = uuid.uuid4().hex

        if not self._enter_dispatch():
            return await self._complete_outcome(
                self._reject(
                    correlation_id,
                    tool_name,
                    None,
                    arguments,
                    "MCP is disabled",
                    "mcp_call_rejected_disabled",
                )
            )
        try:
            return await self._dispatch_admitted(correlation_id, tool_name, arguments)
        finally:
            self._exit_dispatch()

    async def _dispatch_admitted(
        self, correlation_id: str, tool_name: str, arguments: ToolArguments
    ) -> ToolDispatchResult:
        tool = self._registry.get(tool_name)
        if tool is None:
            return await self._complete_outcome(
                self._reject(
                    correlation_id,
                    tool_name,
                    None,
                    arguments,
                    f"Unknown tool: {tool_name!r}",
                    "mcp_call_rejected_unknown_tool",
                )
            )
        if not tool.enabled:
            return await self._complete_outcome(
                self._reject(
                    correlation_id,
                    tool_name,
                    tool.provider,
                    arguments,
                    f"Tool disabled: {tool_name!r}",
                    "mcp_call_rejected_tool_disabled",
                    data_boundary=tool.data_boundary,
                )
            )
        client = self._get_client(tool.provider)
        if client is None:
            return await self._complete_outcome(
                self._reject(
                    correlation_id,
                    tool_name,
                    tool.provider,
                    arguments,
                    f"Provider not connected: {tool.provider!r}",
                    "mcp_call_rejected_provider_not_connected",
                    data_boundary=tool.data_boundary,
                )
            )

        try:
            upstream_name, outbound_arguments = tool.prepare_call(arguments)
        except UnsupportedToolArguments as exc:
            return await self._complete_outcome(
                self._reject(
                    correlation_id,
                    tool_name,
                    tool.provider,
                    arguments,
                    str(exc),
                    "mcp_call_rejected_arguments",
                    data_boundary=tool.data_boundary,
                )
            )

        summary = summarize_outbound(tool.provider, tool_name, outbound_arguments)
        started = time.perf_counter()
        await self._bus.publish(
            ToolCallStarted,
            ToolCallStarted(
                correlation_id=correlation_id,
                tool_name=tool_name,
                provider=tool.provider,
                arguments=outbound_arguments,
                outbound_summary=summary,
                timestamp=time.time(),
                data_boundary=tool.data_boundary,
            ),
        )
        try:
            await publish_system_event(
                self._bus,
                logger,
                SOURCE,
                EventLevel.ACTIVE,
                log_message=(
                    f"Calling tool {tool_name!r} via {tool.provider!r}: {summary}"
                ),
                ui_message=ui_text(
                    "mcp_calling_tool",
                    self._ui_language,
                    tool=tool_name,
                    provider=tool.provider,
                    summary=summary,
                ),
                correlation_id=correlation_id,
            )
            result = await client.call_tool(upstream_name, outbound_arguments)
        except asyncio.CancelledError:
            duration = time.perf_counter() - started
            await self._complete_outcome(
                self._finish(
                    correlation_id,
                    tool_name,
                    tool.provider,
                    summary,
                    duration,
                    ok=False,
                    error="cancelled",
                    content=None,
                    structured_content=None,
                    data_boundary=tool.data_boundary,
                    level=EventLevel.WARN,
                    log_message=(
                        f"Tool {tool_name!r} via {tool.provider!r} call was "
                        f"cancelled after {duration:.2f}s"
                    ),
                    ui_key="mcp_tool_call_cancelled",
                    ui_args={"tool": tool_name, "provider": tool.provider},
                )
            )
            raise
        except McpTransportError as exc:
            # The session/subprocess itself is suspect - unlike a normal
            # per-call failure below, this also degrades the provider at
            # the host level (see on_transport_error's docstring above).
            duration = time.perf_counter() - started
            if self._on_transport_error is not None:
                await self._on_transport_error(tool.provider, exc)
            return await self._complete_outcome(
                self._finish(
                    correlation_id,
                    tool_name,
                    tool.provider,
                    summary,
                    duration,
                    ok=False,
                    error=str(exc),
                    content=None,
                    structured_content=None,
                    data_boundary=tool.data_boundary,
                    level=EventLevel.ERROR,
                    log_message=(
                        f"Tool {tool_name!r} via {tool.provider!r} raised after "
                        f"{duration:.2f}s: {exc}"
                    ),
                    ui_key="mcp_tool_call_failed",
                    ui_args={"tool": tool_name, "duration": duration},
                )
            )
        except Exception as exc:
            # A normal per-call failure (protocol error, timeout, tool-
            # level exception) - McpError and anything else that is not
            # McpTransportError lands here. This ends only this call; the
            # provider is not touched and the module does not degrade.
            duration = time.perf_counter() - started
            return await self._complete_outcome(
                self._finish(
                    correlation_id,
                    tool_name,
                    tool.provider,
                    summary,
                    duration,
                    ok=False,
                    error=str(exc),
                    content=None,
                    structured_content=None,
                    data_boundary=tool.data_boundary,
                    level=EventLevel.WARN,
                    log_message=(
                        f"Tool {tool_name!r} via {tool.provider!r} raised after "
                        f"{duration:.2f}s: {exc}"
                    ),
                    ui_key="mcp_tool_call_failed",
                    ui_args={"tool": tool_name, "duration": duration},
                )
            )

        duration = time.perf_counter() - started
        ok = not result.is_error
        return await self._complete_outcome(
            self._finish(
                correlation_id,
                tool_name,
                tool.provider,
                summary,
                duration,
                ok=ok,
                error=None if ok else "tool reported an error",
                content=result.content,
                structured_content=result.structured_content,
                data_boundary=tool.data_boundary,
                level=EventLevel.INFO if ok else EventLevel.WARN,
                log_message=(
                    f"Tool {tool_name!r} via {tool.provider!r} finished in "
                    f"{duration:.2f}s (error={result.is_error})"
                ),
                ui_key="mcp_tool_call_finished",
                ui_args={
                    "tool": tool_name,
                    "provider": tool.provider,
                    "duration": duration,
                },
            )
        )

    async def _complete_outcome(
        self, outcome: Awaitable[ToolDispatchResult]
    ) -> ToolDispatchResult:
        """Completes one correlated outcome even if its caller is cancelled."""
        outcome_task = asyncio.ensure_future(outcome)
        try:
            return await asyncio.shield(outcome_task)
        except asyncio.CancelledError:
            await outcome_task
            raise

    async def _reject(
        self,
        correlation_id: str,
        tool_name: str,
        provider: str | None,
        arguments: ToolArguments,
        reason: str,
        ui_key: str,
        data_boundary: DataBoundary = DataBoundary.UNKNOWN,
    ) -> ToolDispatchResult:
        summary = summarize_outbound(provider or "?", tool_name, arguments)
        await self._bus.publish(
            ToolCallFinished,
            ToolCallFinished(
                correlation_id=correlation_id,
                tool_name=tool_name,
                provider=provider,
                outbound_summary=summary,
                duration_seconds=0.0,
                ok=False,
                error=reason,
                data_boundary=data_boundary,
            ),
        )
        await publish_system_event(
            self._bus,
            logger,
            SOURCE,
            EventLevel.WARN,
            log_message=f"Rejected tool call {tool_name!r}: {reason}",
            ui_message=ui_text(
                ui_key, self._ui_language, tool=tool_name, provider=provider or "-"
            ),
            correlation_id=correlation_id,
        )
        return ToolDispatchResult(ok=False, correlation_id=correlation_id, error=reason)

    async def _finish(
        self,
        correlation_id: str,
        tool_name: str,
        provider: str,
        summary: str,
        duration: float,
        *,
        ok: bool,
        error: str | None,
        content: object | None,
        structured_content: JSONObject | None,
        data_boundary: DataBoundary,
        level: EventLevel,
        log_message: str,
        ui_key: str,
        ui_args: dict[str, str | int | float],
    ) -> ToolDispatchResult:
        await self._bus.publish(
            ToolCallFinished,
            ToolCallFinished(
                correlation_id=correlation_id,
                tool_name=tool_name,
                provider=provider,
                outbound_summary=summary,
                duration_seconds=duration,
                ok=ok,
                error=error,
                data_boundary=data_boundary,
            ),
        )
        await publish_system_event(
            self._bus,
            logger,
            SOURCE,
            level,
            log_message=log_message,
            ui_message=ui_text(ui_key, self._ui_language, **ui_args),
            correlation_id=correlation_id,
        )
        return ToolDispatchResult(
            ok=ok,
            correlation_id=correlation_id,
            content=content,
            structured_content=structured_content,
            error=error,
        )
