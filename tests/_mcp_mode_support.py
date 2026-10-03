"""Shared factories for the MCP-mode story's tests (task v2.0-7, item 4).

Imported explicitly rather than installed as pytest fixtures, so every test
states what it builds and nothing hides in a conftest. Placed beside the tests
that use it, like tests/main_split/_support_from_test_main.py.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from jarvis.core.bus import EventBus
from jarvis.dialog.voice_guide import (
    EnqueueResult,
    VoiceGuideAccepted,
    VoiceGuideRejected,
    VoiceGuideRejection,
    VoiceGuideRequest,
)
from jarvis.journal.corpus import SPOKEN_DERIVATIVE_METADATA_KEY
from jarvis.journal.events import JournalEvent, JSONValue
from jarvis.journal.external_canvas import (
    CALLER_METADATA_KEY,
    MCP_CANVAS_SOURCE,
    SPEECH_ORIGIN_METADATA_KEY,
    SPEECH_STATUS_METADATA_KEY,
    SpeechOrigin,
    SpeechStatus,
)
from jarvis.mcp_mode.server import (
    McpModeServer,
    McpServerState,
    McpServerStatusChanged,
)

CANVAS_TEXT = "Реле перегрелось после обеда."
DERIVATIVE_TEXT = "напоминаю, реле перегрелось из-за пыли"
DEFAULT_CALLER: dict[str, JSONValue] = {"name": "claude-code", "version": None}


def external_canvas_event(
    *,
    session_id: str,
    timestamp: str,
    text: str = CANVAS_TEXT,
    caller: dict[str, JSONValue] | None = DEFAULT_CALLER,
    speech_origin: SpeechOrigin | None = None,
    speech_status: SpeechStatus | None = None,
    derivative: str | None = None,
) -> JournalEvent:
    """One external answer shaped the way ``record_external_canvas()`` records
    it: role ``assistant``, source ``mcp_canvas``, and only the speech fields
    the caller asks for."""
    metadata: dict[str, JSONValue] = {}
    if caller is not None:
        metadata[CALLER_METADATA_KEY] = dict(caller)
    if speech_origin is not None:
        metadata[SPEECH_ORIGIN_METADATA_KEY] = speech_origin.value
    if speech_status is not None:
        metadata[SPEECH_STATUS_METADATA_KEY] = speech_status.value
    if derivative is not None:
        metadata[SPOKEN_DERIVATIVE_METADATA_KEY] = derivative
    return JournalEvent(
        session_id=session_id,
        timestamp=timestamp,
        source=MCP_CANVAS_SOURCE,
        role="assistant",
        text=text,
        media=(),
        transcript=None,
        metadata=metadata,
    )


class FakeVoiceGuide:
    """Accepts or rejects synchronously, the way the speak tool needs. The
    origin is whatever the test configures, never derived from the request:
    the real rule lives in VoiceGuideService and is tested there."""

    def __init__(
        self,
        rejection: VoiceGuideRejection | None = None,
        origin: SpeechOrigin = SpeechOrigin.DERIVATIVE,
    ) -> None:
        self.requests: list[VoiceGuideRequest] = []
        self._rejection = rejection
        self._origin = origin

    def enqueue(self, request: VoiceGuideRequest) -> EnqueueResult:
        if self._rejection is not None:
            return VoiceGuideRejected(self._rejection)
        self.requests.append(request)
        return VoiceGuideAccepted(len(self.requests), self._origin)


@dataclass
class ServerStatusLog:
    """Records the server's status events off the bus."""

    bus: EventBus
    events: list[McpServerStatusChanged] = field(default_factory=list)
    listening: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self) -> None:
        self.bus.subscribe(McpServerStatusChanged, self._record)

    async def _record(self, event: McpServerStatusChanged) -> None:
        self.events.append(event)
        if event.state is McpServerState.LISTENING:
            self.listening.set()


@dataclass
class RunningMcpServer:
    """A real ``McpModeServer`` on an ephemeral loopback port."""

    server: McpModeServer
    task: asyncio.Task
    bus: EventBus
    status: ServerStatusLog

    @property
    def port(self) -> int:
        return self.server.port

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"

    async def wait_for_state(self, state: McpServerState, timeout: float = 5) -> None:
        async with asyncio.timeout(timeout):
            while not any(event.state is state for event in self.status.events):
                await asyncio.sleep(0.01)

    async def stop(self) -> None:
        self.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.task


@contextlib.asynccontextmanager
async def serving_mcp_server(
    *,
    build: Callable[[EventBus], McpModeServer],
    bus: EventBus | None = None,
) -> AsyncIterator[RunningMcpServer]:
    """Runs a real server until the block exits, once it is listening.

    ``build`` constructs it from the given bus, so a caller can start from the
    token and settings it has or from settings alone (which reads the token
    file). ``bus`` is the caller's when it already has subscribers - the
    transport tests need theirs; a fresh one otherwise.
    """
    bus = EventBus() if bus is None else bus
    server = build(bus)
    running = RunningMcpServer(
        server=server,
        task=server.start(),
        bus=bus,
        status=ServerStatusLog(bus),
    )
    try:
        await running.wait_for_state(McpServerState.LISTENING)
        yield running
    finally:
        await running.stop()
