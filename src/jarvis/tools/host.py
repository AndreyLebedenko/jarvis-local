"""McpHost: the switchable MCP module.

Always constructed by jarvis.app.build_app(), regardless of
[mcp].enabled - this is the state owner a live toggle (task 5's Control
Center switch) can always call enable()/disable() on, and it genuinely is
a client manager: it owns _client_factory, _clients, and the
connect/disconnect loop. What "off equals the capability does not exist"
actually rests on is narrower: at rest (status OFF) this object holds no
client objects and has spawned no subprocess - client_factory is only
ever invoked from inside enable(). This revision (a persistent, always-
constructed controller rather than a conditionally-omitted one) is a
    recorded human decision - see PROJECT.md's MCP host core section and
    tasks/done/story-v1.4.0-task-3-mcp-host-core.md's acceptance criteria,
both updated to match.

enable()/disable() are serialized by one asyncio.Lock so two concurrent
callers (a race between a config-driven startup enable and a UI click, or
two rapid UI clicks) can never both run the connect/disconnect loop at
once.

Admission gate (review round 2, finding 1): disable() must not tear down
a client that a concurrently-running dispatch() call still holds a
reference to. _admitting/_inflight/_drained implement a closeable gate:
disable() flips _admitting False as the first thing it does (synchronous,
no await, so no dispatch() call can race the flip), then awaits
_drained before touching any client - guaranteeing every dispatch()
call already in flight finishes (or the client it was using is at least
not concurrently disconnected) before teardown proceeds. New dispatch()
calls arriving after the flip see _admitting False and are rejected
before ever reaching self._clients.

McpModuleStatusChanged is the typed, authoritative signal task 5's
Control Center needs (review round 2, finding 2): every _status
transition - including the CONNECTING/DISCONNECTING transient states -
publishes this on the bus, so the UI never has to infer engine state from
SystemEvent prose or poll .status. Ordering matters (review round 3,
finding 1): enable() flips _admitting True *before* publishing the
ON/DEGRADED status, and disable() flips it False and publishes
DISCONNECTING *before* awaiting the drain - in both directions, a
subscriber reacting to the status event the instant it arrives must see
dispatch() behave consistently with what that status claims, never a
stale "on" while admission is already closed or a not-yet-open gate while
the status already says "on".
"""

import asyncio
import enum
import logging
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.core.bus import EventBus
from jarvis.core.config import McpServerSettings, McpSettings
from jarvis.core.system_log import publish_system_event
from jarvis.tools.interception import SOURCE, ToolDispatcher
from jarvis.tools.mcp_client import McpClient, StdioMcpClient
from jarvis.tools.registry import RegisteredTool, ToolRegistry
from jarvis.ui.contract import EventLevel
from jarvis.ui.text import DEFAULT_UI_LANGUAGE, ui_text

logger = logging.getLogger(__name__)

ClientFactory = Callable[[McpServerSettings], McpClient]


def _default_client_factory(server: McpServerSettings) -> McpClient:
    return StdioMcpClient(server.command, server.args)


class McpModuleStatus(enum.Enum):
    OFF = "off"
    CONNECTING = "connecting"
    ON = "on"
    # At least one enabled server failed to connect, at least one of its
    # declared tools was rejected as a name collision, or a previously
    # healthy provider's call_tool() raised (transport/session failure,
    # not a normal tool-reported error) - the module is switched on and
    # partially working, not fully healthy. Never silently reported as ON
    # (VISION.md's "prefer honest incomplete state over fake success").
    DEGRADED = "degraded"
    DISCONNECTING = "disconnecting"


@dataclass(frozen=True)
class McpModuleStatusChanged:
    status: McpModuleStatus


@dataclass(frozen=True)
class _ConnectOutcome:
    connected: bool
    rejected_tools: tuple[str, ...] = ()


class McpHost:
    def __init__(
        self,
        bus: EventBus,
        settings: McpSettings,
        client_factory: ClientFactory = _default_client_factory,
        ui_language: str = DEFAULT_UI_LANGUAGE,
    ) -> None:
        self._bus = bus
        self._settings = settings
        self._client_factory = client_factory
        self._ui_language = ui_language
        self._registry = ToolRegistry()
        self._clients: dict[str, McpClient] = {}
        self._status = McpModuleStatus.OFF
        self._lock = asyncio.Lock()
        # Admission gate - see module docstring.
        self._admitting = False
        self._inflight = 0
        self._drained = asyncio.Event()
        self._drained.set()
        self.dispatcher = ToolDispatcher(
            bus,
            self._registry,
            self._get_client,
            self._enter_dispatch,
            self._exit_dispatch,
            on_transport_error=self._on_transport_error,
            ui_language=ui_language,
        )

    @property
    def status(self) -> McpModuleStatus:
        return self._status

    @property
    def enabled(self) -> bool:
        """True for ON or DEGRADED - "the module is switched on",
        regardless of whether every configured server actually connected.
        Callers that need the finer-grained picture read .status
        directly."""
        return self._status in (McpModuleStatus.ON, McpModuleStatus.DEGRADED)

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    def set_tool_enabled(self, name: str, enabled: bool) -> bool:
        return self._registry.set_tool_enabled(name, enabled)

    def _get_client(self, provider: str) -> McpClient | None:
        return self._clients.get(provider)

    def _enter_dispatch(self) -> bool:
        if not self._admitting:
            return False
        self._inflight += 1
        self._drained.clear()
        return True

    def _exit_dispatch(self) -> None:
        self._inflight -= 1
        if self._inflight <= 0:
            self._inflight = 0
            self._drained.set()

    async def _set_status(self, status: McpModuleStatus) -> None:
        self._status = status
        await self._bus.publish(
            McpModuleStatusChanged, McpModuleStatusChanged(status=status)
        )

    async def _on_transport_error(self, provider: str, exc: Exception) -> None:
        """A raised exception from call_tool() (not a normal isError
        result) means the session/subprocess for this provider is
        suspect - review round 2 finding 3. Its tools are pulled from the
        registry immediately (no further dispatch can reach them, since
        dispatch() looks tools up by name in the registry) and the module
        is marked DEGRADED if it was previously reporting healthy. The
        client itself is left in _clients rather than force-disconnected
        here - actively tearing down a connection from inside a call
        that's already failing is more invasive than this fix requires;
        disable()'s own teardown still reaches it normally."""
        self._registry.clear_provider(provider)
        if self._status == McpModuleStatus.ON:
            await self._set_status(McpModuleStatus.DEGRADED)
        await publish_system_event(
            self._bus,
            logger,
            SOURCE,
            EventLevel.ERROR,
            log_message=(
                f"MCP server {provider!r} failed during a tool call and was "
                f"marked unavailable: {exc}"
            ),
            ui_message=ui_text(
                "mcp_server_call_failed", self._ui_language, server=provider
            ),
        )

    async def enable(self) -> None:
        async with self._lock:
            if self._status != McpModuleStatus.OFF:
                return
            await self._set_status(McpModuleStatus.CONNECTING)
            try:
                enabled_servers = [
                    (name, server)
                    for name, server in self._settings.servers.items()
                    if server.enabled
                ]
                had_issue = False
                for name, server in enabled_servers:
                    outcome = await self._connect_server(name, server)
                    had_issue = (
                        had_issue
                        or not outcome.connected
                        or bool(outcome.rejected_tools)
                    )

                # Admission opens before the terminal status is published -
                # otherwise a subscriber reacting to the ON/DEGRADED event
                # could dispatch immediately and see "MCP is disabled" even
                # though the status it just received said otherwise (review
                # round 3 finding 1).
                self._admitting = True
                await self._set_status(
                    McpModuleStatus.DEGRADED if had_issue else McpModuleStatus.ON
                )
                await publish_system_event(
                    self._bus,
                    logger,
                    SOURCE,
                    EventLevel.INFO if not had_issue else EventLevel.WARN,
                    log_message=(
                        f"MCP enabled, status={self._status.value} "
                        f"({len(self._clients)} server(s) connected)"
                    ),
                    ui_message=ui_text(
                        "mcp_enabled_degraded" if had_issue else "mcp_enabled",
                        self._ui_language,
                    ),
                )
            except asyncio.CancelledError:
                await self._rollback_cancelled_enable()
                raise

    async def _rollback_cancelled_enable(self) -> None:
        """Returns a partially enabled host to its inert OFF state."""
        self._admitting = False
        for name in list(self._clients):
            try:
                await self._disconnect_server(name)
            except Exception:
                logger.warning(
                    "MCP server %r: disconnect during cancelled enable raised",
                    name,
                    exc_info=True,
                )
        self._clients.clear()
        self._registry.clear()
        await self._set_status(McpModuleStatus.OFF)

    async def disable(self) -> None:
        async with self._lock:
            if self._status == McpModuleStatus.OFF:
                return
            # Close admission first, synchronously (no await between the
            # status check above and this line) - no dispatch() call can
            # observe _admitting True after this point. DISCONNECTING is
            # published immediately after, before the drain wait, so the
            # status signal is never stale while admission is already
            # closed (review round 3 finding 1) - only then do we wait for
            # any call that already got in before the flip to finish.
            self._admitting = False
            await self._set_status(McpModuleStatus.DISCONNECTING)
            await self._drained.wait()

            errors: list[tuple[str, Exception]] = []
            for name in list(self._clients):
                try:
                    await self._disconnect_server(name)
                except Exception as exc:
                    # A provider's own disconnect() misbehaving must not
                    # abandon the rest of the cleanup loop or leave the
                    # module stuck in a half-torn-down status.
                    errors.append((name, exc))

            self._clients.clear()
            self._registry.clear()
            await self._set_status(McpModuleStatus.OFF)

            for name, exc in errors:
                await publish_system_event(
                    self._bus,
                    logger,
                    SOURCE,
                    EventLevel.ERROR,
                    log_message=(
                        f"MCP server {name!r} failed to disconnect cleanly: {exc}"
                    ),
                    ui_message=ui_text(
                        "mcp_server_disconnect_failed", self._ui_language, server=name
                    ),
                )
            await publish_system_event(
                self._bus,
                logger,
                SOURCE,
                EventLevel.INFO,
                log_message=(
                    "MCP disabled"
                    if not errors
                    else f"MCP disabled ({len(errors)} disconnect error(s))"
                ),
                ui_message=ui_text("mcp_disabled", self._ui_language),
            )

    async def _connect_server(
        self, name: str, server: McpServerSettings
    ) -> _ConnectOutcome:
        client = self._client_factory(server)
        try:
            await client.connect()
            declarations = await client.list_tools()
        except asyncio.CancelledError:
            try:
                await client.disconnect()
            except Exception:
                logger.warning(
                    "MCP server %r: disconnect after cancelled discovery raised",
                    name,
                    exc_info=True,
                )
            raise
        except Exception as exc:
            try:
                await client.disconnect()
            except Exception:
                # Best-effort: connect() already stops its connection-owner
                # task and unwinds SDK contexts on failure, so this is usually a no-op;
                # if it does raise, the original connect failure is still
                # the fact worth reporting, not this secondary one.
                logger.warning(
                    "MCP server %r: cleanup disconnect after a failed "
                    "connect/list_tools also raised",
                    name,
                    exc_info=True,
                )
            await publish_system_event(
                self._bus,
                logger,
                SOURCE,
                EventLevel.ERROR,
                log_message=f"MCP server {name!r} failed to connect: {exc}",
                ui_message=ui_text(
                    "mcp_server_unavailable", self._ui_language, server=name
                ),
            )
            return _ConnectOutcome(connected=False)

        self._clients[name] = client
        registered = [
            RegisteredTool(
                name=declaration.name,
                description=declaration.description,
                schema=declaration.schema,
                provider=name,
            )
            for declaration in declarations
        ]
        rejected = self._registry.set_provider_tools(name, registered)
        for tool_name in rejected:
            await publish_system_event(
                self._bus,
                logger,
                SOURCE,
                EventLevel.WARN,
                log_message=(
                    f"Tool name collision: {tool_name!r} from server {name!r} "
                    "was rejected - a different, already-registered provider "
                    "owns that name"
                ),
                ui_message=ui_text(
                    "mcp_tool_name_collision",
                    self._ui_language,
                    tool=tool_name,
                    server=name,
                ),
            )
        return _ConnectOutcome(connected=True, rejected_tools=rejected)

    async def _disconnect_server(self, name: str) -> None:
        """Only attempts the actual disconnect - disable()'s trailing
        self._clients.clear()/self._registry.clear() handle bookkeeping
        for every provider in one place, once, regardless of which
        individual disconnects here succeeded or raised."""
        client = self._clients.get(name)
        if client is not None:
            await client.disconnect()
