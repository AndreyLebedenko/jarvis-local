"""MCP client management: one connection to one configured MCP server.

McpClient is the seam McpHost drives and pure tests inject a fake
through - nothing outside this module talks to the official MCP SDK
directly, and nothing outside jarvis.tools talks to McpClient directly
(McpHost owns every instance). StdioMcpClient wraps mcp.client.stdio's
subprocess transport plus mcp.ClientSession; the SDK import is deferred to
the connection-owner task started by connect() (matching tts_piper.py's
lazy-import precedent) so importing
this module - or any module that imports it - never pulls in the mcp
package's own dependency tree (starlette, uvicorn, cryptography, ...)
when MCP is disabled. `ClientSession`/`ContentBlock` are only imported
under TYPE_CHECKING for that same reason - real values still flow through
at runtime, only the type-checker needs the import. `anyio` itself is
imported eagerly below (not deferred): it is already a base Jarvis
dependency via httpx (`pip show anyio` lists httpx as a requirer
independent of mcp), so importing it costs nothing extra when MCP is
disabled.

The official stdio transport enters an AnyIO task group, whose cancel
scope must exit in the same asyncio task that entered it. StdioMcpClient
therefore owns one connection task per active server. Public connect() and
disconnect() only start/signal/await that owner, so startup and future
Control Center toggles may safely call them from different tasks while the
SDK contexts still enter and exit in one task.

McpTransportError boundary: read mcp.shared.session.BaseSession.
send_request()'s source (installed mcp 1.28.1) before drawing this line.
A JSON-RPC error reply, and a request that simply timed out waiting for a
reply, are both raised by the SDK as `mcp.McpError` - the session is
provably still alive in both cases, the request just failed or was slow.
A genuinely broken transport (subprocess died, pipe closed) instead
surfaces as one of anyio's own stream exceptions on the underlying
memory-object streams stdio_client() pumps the subprocess through.
StdioMcpClient.call_tool() catches exactly that anyio-exception family
(plus a bare OSError as a safety net for whatever anyio doesn't wrap) and
re-raises it as McpTransportError - every other exception, including
McpError, propagates unchanged and must be treated as "this one call
failed", not "the provider is dead". This is a best-effort boundary based
on reading the SDK's source, not verified against a live broken pipe -
task 6's manual handoff is where that gets exercised for real.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

import anyio

from jarvis.tools.json_types import JSONObject

if TYPE_CHECKING:
    from mcp import ClientSession
    from mcp.types import ContentBlock

ToolArguments = JSONObject

# The anyio exception family that means "the underlying transport itself
# broke", not "this one request failed" - see the module docstring.
_TRANSPORT_EXCEPTIONS = (
    anyio.BrokenResourceError,
    anyio.ClosedResourceError,
    anyio.EndOfStream,
    OSError,
)


class McpTransportError(Exception):
    """The MCP session/subprocess itself appears broken, as opposed to a
    normal per-call failure (a bad request, a tool-level protocol error,
    a single timed-out call - all of which the SDK raises as McpError,
    not this). Only this exception should make a caller treat the
    provider as dead; every other exception from call_tool() means only
    that one call failed."""


@dataclass(frozen=True)
class ToolDeclaration:
    name: str
    description: str
    schema: JSONObject


@dataclass(frozen=True)
class ToolCallResult:
    content: list[ContentBlock]
    is_error: bool = False
    # CallToolResult.structuredContent (verified against installed mcp
    # 1.28.1's CallToolResult.model_fields) - carried through rather than
    # dropped, even though nothing consumes it yet (task 4's job).
    structured_content: JSONObject | None = None


class McpClient(Protocol):
    """connect()/disconnect() are the lifecycle boundary McpHost drives;
    list_tools()/call_tool() are only ever called between them."""

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def list_tools(self) -> list[ToolDeclaration]: ...

    async def call_tool(
        self, name: str, arguments: ToolArguments
    ) -> ToolCallResult: ...


class StdioMcpClient:
    """Real MCP client over a stdio subprocess, using the official SDK."""

    def __init__(
        self,
        command: str,
        args: tuple[str, ...] = (),
        env: dict[str, str] | None = None,
    ) -> None:
        self._command = command
        self._args = args
        self._env = None if env is None else dict(env)
        self._session: ClientSession | None = None
        self._connection_task: asyncio.Task[None] | None = None
        self._stop_connection: asyncio.Event | None = None

    async def connect(self) -> None:
        if self._connection_task is not None:
            raise RuntimeError("StdioMcpClient.connect() called while connected")

        ready = asyncio.get_running_loop().create_future()
        stop_connection = asyncio.Event()
        connection_task = asyncio.create_task(
            self._run_connection(ready, stop_connection)
        )
        self._connection_task = connection_task
        self._stop_connection = stop_connection
        try:
            await asyncio.shield(ready)
        except BaseException:
            connection_task.cancel()
            await asyncio.gather(connection_task, return_exceptions=True)
            self._clear_connection_task(connection_task)
            raise

    async def _run_connection(
        self, ready: asyncio.Future[None], stop_connection: asyncio.Event
    ) -> None:
        """Owns SDK context entry and exit in one asyncio task.

        AnyIO task-group cancel scopes cannot be exited from a different
        task. Public connect()/disconnect() are requests into this owner,
        so startup and Control Center callers may safely be different tasks.
        """
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        try:
            params = StdioServerParameters(
                command=self._command, args=list(self._args), env=self._env
            )
            async with stdio_client(params) as streams:
                read_stream, write_stream = streams
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    self._session = session
                    if not ready.done():
                        ready.set_result(None)
                    await stop_connection.wait()
        except asyncio.CancelledError:
            if not ready.done():
                ready.cancel()
            raise
        except BaseException as exc:
            if not ready.done():
                ready.set_exception(exc)
                return
            raise
        finally:
            self._session = None

    async def disconnect(self) -> None:
        connection_task = self._connection_task
        if connection_task is None:
            return
        stop_connection = self._stop_connection
        if stop_connection is not None:
            stop_connection.set()
        try:
            await asyncio.shield(connection_task)
        except asyncio.CancelledError:
            # The caller may go away, but the owner task must still finish
            # unwinding the subprocess/session contexts before cancellation
            # is allowed to propagate.
            await connection_task
            raise
        finally:
            self._clear_connection_task(connection_task)

    def _clear_connection_task(self, connection_task: asyncio.Task[None]) -> None:
        if self._connection_task is connection_task:
            self._connection_task = None
            self._stop_connection = None

    async def list_tools(self) -> list[ToolDeclaration]:
        if self._session is None:
            raise RuntimeError("StdioMcpClient.list_tools() called before connect()")
        declarations: list[ToolDeclaration] = []
        cursor: str | None = None
        # ListToolsResult.nextCursor (verified against installed mcp
        # 1.28.1) - a server with more tools than fit in one page would
        # otherwise silently lose everything past the first page.
        while True:
            result = await self._session.list_tools(cursor=cursor)
            declarations.extend(
                ToolDeclaration(
                    name=tool.name,
                    description=tool.description or "",
                    schema=cast(JSONObject, tool.inputSchema),
                )
                for tool in result.tools
            )
            cursor = result.nextCursor
            if not cursor:
                break
        return declarations

    async def call_tool(self, name: str, arguments: ToolArguments) -> ToolCallResult:
        if self._session is None:
            raise RuntimeError("StdioMcpClient.call_tool() called before connect()")
        try:
            result = await self._session.call_tool(name, arguments)
        except _TRANSPORT_EXCEPTIONS as exc:
            raise McpTransportError(
                f"MCP transport failed during call_tool({name!r}): {exc}"
            ) from exc
        return ToolCallResult(
            content=result.content,
            is_error=bool(result.isError),
            structured_content=cast(JSONObject | None, result.structuredContent),
        )
