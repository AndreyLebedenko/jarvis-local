"""The --mcp-mode server: one streamable-HTTP MCP endpoint on 127.0.0.1, one
bearer token, one tool, served by uvicorn inside Jarvis's own event loop.

The listener is bound separately (`bind_mcp_listener`) so a busy port fails
startup synchronously, before anything else starts. `McpModeServer.start()`
then serves in a task until it is cancelled and turns the cancellation into
uvicorn's graceful shutdown, which a further cancellation cannot abort.
Each `McpModeServer` is one run: the SDK's session manager runs once per
FastMCP instance, so every start builds a new one.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import socket
from collections.abc import Awaitable, Callable, Coroutine, Iterator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Protocol

import uvicorn
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent
from pydantic import Field
from starlette.types import ASGIApp, Receive, Scope, Send

from jarvis.core.bus import EventBus
from jarvis.core.config import McpModeSettings
from jarvis.dialog.voice_guide import EnqueueResult, VoiceGuideRequest
from jarvis.journal.external_canvas import ExternalCanvasCaller
from jarvis.mcp_mode.speak import (
    SpeakError,
    SpeakQueued,
    queued_or_error,
    request_or_error,
)
from jarvis.mcp_mode.token import load_or_create_token

logger = logging.getLogger(__name__)

MCP_HOST = "127.0.0.1"
MCP_SERVER_TASK_NAME = "mcp-server"
PORT_CONFIG_KEY = "[mcp_mode].port"
SPEAK_TOOL_NAME = "speak"
_SERVER_NAME = "jarvis"
_GRACEFUL_SHUTDOWN_SECONDS = 2
_SESSION_ID_HEADER = "mcp-session-id"


class McpPortUnavailableError(Exception):
    def __init__(self, port: int, reason: str) -> None:
        super().__init__(
            f"MCP mode cannot listen on {MCP_HOST}:{port} ({PORT_CONFIG_KEY}): {reason}"
        )
        self.port = port


class McpServerNotStartedError(Exception):
    def __init__(self, port: int) -> None:
        super().__init__(f"MCP mode server on {MCP_HOST}:{port} did not start")


class McpServerState(Enum):
    LISTENING = "listening"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True)
class McpServerStatusChanged:
    """`port` is set for LISTENING, `reason` for FAILED."""

    state: McpServerState
    port: int | None = None
    reason: str | None = None


class SpeakQueue(Protocol):
    def enqueue(self, request: VoiceGuideRequest) -> EnqueueResult: ...


def bind_mcp_listener(port: int) -> socket.socket:
    """Binds 127.0.0.1:`port` (0 = any free port). Never falls back to another
    port: the client's stored URL would then point at nothing."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind((MCP_HOST, port))
    except OSError as error:
        listener.close()
        raise McpPortUnavailableError(port, str(error.strerror)) from error
    return listener


class BearerTokenMiddleware:
    """Lets an HTTP request through only with `Authorization: Bearer <token>`;
    anything else gets a plain 401. Keeps only the token's digest."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self._app = app
        self._expected_digest = _digest(token)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not self._authorized(scope):
            await _send_unauthorized(send)
            return
        await self._app(scope, receive, send)

    def _authorized(self, scope: Scope) -> bool:
        credential = _bearer_credential(scope)
        if credential is None:
            return False
        return hmac.compare_digest(self._expected_digest, _digest(credential))


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def _bearer_credential(scope: Scope) -> str | None:
    for name, value in scope["headers"]:
        if name == b"authorization":
            scheme, _, credential = value.decode("latin-1").partition(" ")
            if scheme.lower() == "bearer" and credential:
                return credential.strip()
            return None
    return None


async def _send_unauthorized(send: Send) -> None:
    body = b"Unauthorized"
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def speak_tool_description(settings: McpModeSettings) -> str:
    if settings.canvas_speech == "verbatim":
        canvas_only = "Jarvis reads the canvas itself aloud."
    else:
        canvas_only = (
            "Jarvis speaks a short voice guide over the canvas: it tells the "
            "user what the answer covers and where to look, naming headings "
            "and file:line references as landmarks."
        )
    return (
        "Speak to the user aloud on their machine about an answer you have "
        "shown them, and store that answer in the user's local journal. "
        "The call returns at once with status queued and the call's position "
        "in the queue; speech happens later, one call at a time, in order.\n\n"
        "canvas: the full answer exactly as shown to the user. Keep its "
        "headings and file:line references; do not summarize it. "
        f"{canvas_only}\n"
        "spoken_text: optional. Give it only when you want Jarvis to say "
        "exactly this text instead of speaking about the canvas.\n"
        "guidance: optional short note that steers the voice guide, for "
        "example what to emphasize. It is ignored when spoken_text is given "
        "(the result then says guidance_ignored).\n\n"
        f"Limits, in characters: canvas {settings.max_canvas_chars}, "
        f"spoken_text {settings.max_spoken_text_chars}, "
        f"guidance {settings.max_guidance_chars}. A call over a limit is "
        "refused, never truncated. A refused call is an error whose text "
        "starts with a code: empty_canvas, canvas_too_long, "
        "empty_spoken_text, spoken_text_too_long, guidance_too_long, "
        "queue_full, closed."
    )


def _caller_of(ctx: Context) -> ExternalCanvasCaller:
    params = ctx.session.client_params
    client_info = params.clientInfo if params is not None else None
    request = ctx.request_context.request
    headers = getattr(request, "headers", None)
    return ExternalCanvasCaller(
        name=client_info.name if client_info is not None else None,
        version=client_info.version if client_info is not None else None,
        transport_session_id=(
            headers.get(_SESSION_ID_HEADER) if headers is not None else None
        ),
    )


def _tool_result(outcome: SpeakQueued | SpeakError) -> CallToolResult:
    if isinstance(outcome, SpeakError):
        return CallToolResult(
            content=[TextContent(type="text", text=outcome.text)], isError=True
        )
    payload: dict[str, Any] = outcome.payload()
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload))],
        structuredContent=payload,
        isError=False,
    )


@contextlib.contextmanager
def _root_logging_kept() -> Iterator[None]:
    # FastMCP() calls logging.basicConfig(), which installs its own handler
    # whenever the root logger has none yet.
    root = logging.getLogger()
    if root.handlers:
        yield
        return
    placeholder = logging.NullHandler()
    root.addHandler(placeholder)
    try:
        yield
    finally:
        root.removeHandler(placeholder)


def build_speak_mcp(settings: McpModeSettings, voice_guide: SpeakQueue) -> FastMCP:
    with _root_logging_kept():
        mcp = FastMCP(_SERVER_NAME, host=MCP_HOST, json_response=True)

    @mcp.tool(name=SPEAK_TOOL_NAME, description=speak_tool_description(settings))
    async def speak(
        canvas: Annotated[str, Field(description="The full answer as shown.")],
        ctx: Context,
        spoken_text: Annotated[
            str | None, Field(description="Exact text to say instead.")
        ] = None,
        guidance: Annotated[
            str | None, Field(description="Steering note for the voice guide.")
        ] = None,
    ) -> CallToolResult:
        request = request_or_error(
            canvas, spoken_text, guidance, limits=settings, caller=_caller_of(ctx)
        )
        if isinstance(request, SpeakError):
            return _tool_result(request)
        return _tool_result(queued_or_error(request, voice_guide.enqueue(request)))

    return mcp


class _EmbeddedUvicornServer(uvicorn.Server):
    def __init__(
        self, config: uvicorn.Config, on_started: Callable[[], Awaitable[None]]
    ) -> None:
        super().__init__(config)
        self._on_started = on_started
        self.startup_finished = asyncio.Event()

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        # uvicorn would take SIGINT/SIGTERM from Jarvis on the main thread.
        yield

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        try:
            await self._start(sockets)
        finally:
            # Set after the last await: uvicorn checks should_exit right after
            # startup() returns and skips shutdown if it is already set.
            self.startup_finished.set()

    async def _start(self, sockets: list[socket.socket] | None) -> None:
        try:
            await super().startup(sockets)
        except Exception:
            # uvicorn leaves the already started lifespan running when the
            # listener fails; its own bind-failure path shuts it down the same way.
            await self.lifespan.shutdown()
            raise
        if self.started:
            await self._on_started()


class McpModeServer:
    """One run of the server on an already bound listener. The token is
    handed to the bearer middleware and not kept here."""

    def __init__(
        self,
        *,
        listener: socket.socket,
        token: str,
        settings: McpModeSettings,
        voice_guide: SpeakQueue,
        bus: EventBus,
    ) -> None:
        self._listener = listener
        self._port = int(listener.getsockname()[1])
        self._bus = bus
        self._mcp = build_speak_mcp(settings, voice_guide)
        app = BearerTokenMiddleware(self._mcp.streamable_http_app(), token)
        config = uvicorn.Config(
            app,
            lifespan="on",
            ws="none",
            log_config=None,
            access_log=False,
            timeout_graceful_shutdown=_GRACEFUL_SHUTDOWN_SECONDS,
        )
        self._uvicorn = _EmbeddedUvicornServer(config, self._publish_listening)

    @property
    def port(self) -> int:
        return self._port

    def start(self) -> asyncio.Task[None]:
        """Serves in a new task until that task is cancelled, then shuts
        down gracefully and re-raises the cancellation. Publishes LISTENING,
        then STOPPED or FAILED. The task owns the listener: it is closed when
        the task ends, even if the task is cancelled before its first step."""
        task = asyncio.get_running_loop().create_task(
            self._serve(), name=MCP_SERVER_TASK_NAME
        )
        task.add_done_callback(self._release_listener)
        return task

    def _release_listener(self, task: asyncio.Task[None]) -> None:
        del task
        self._listener.close()

    async def _serve(self) -> None:
        serving = asyncio.ensure_future(self._uvicorn.serve(sockets=[self._listener]))
        try:
            await asyncio.shield(serving)
        except asyncio.CancelledError:
            await _complete_despite_cancellation(self._stop(serving))
            raise
        except Exception:
            await _complete_despite_cancellation(self._finish(serving))
            raise
        if self._uvicorn.started:
            logger.warning(
                "MCP mode server on port %d stopped without being asked to",
                self._port,
            )
        await self._finish(serving)
        if not self._uvicorn.started:
            raise McpServerNotStartedError(self._port)

    async def _stop(self, serving: asyncio.Future[None]) -> None:
        # should_exit set before startup has finished makes uvicorn skip shutdown.
        startup = asyncio.ensure_future(self._uvicorn.startup_finished.wait())
        await asyncio.wait({serving, startup}, return_when=asyncio.FIRST_COMPLETED)
        startup.cancel()
        try:
            await self._terminate_sessions()
        except Exception:
            logger.exception("MCP mode server could not terminate its sessions")
        self._uvicorn.should_exit = True
        await asyncio.wait({serving})
        await self._finish(serving)

    async def _finish(self, serving: asyncio.Future[None]) -> None:
        """Publishes how the run ended, after cleaning up what a failed uvicorn
        left running."""
        failure = serving.exception()
        if failure is not None:
            await self._clean_up_after_failure(failure)
        elif not self._uvicorn.started:
            not_started = McpServerNotStartedError(self._port)
            logger.error("%s", not_started)
            await self._publish_failed(str(not_started))
        else:
            await self._publish(McpServerStatusChanged(McpServerState.STOPPED))

    async def _clean_up_after_failure(self, failure: BaseException) -> None:
        """A uvicorn that raised ran no shutdown, so its lifespan and
        connections are still up unless it failed during startup."""
        logger.error("MCP mode server failed", exc_info=failure)
        if self._uvicorn.started:
            try:
                await self._terminate_sessions()
                await self._uvicorn.shutdown(sockets=[self._listener])
            except Exception:
                logger.exception("MCP mode server shutdown after a failure failed")
        await self._publish_failed(str(failure))

    async def _terminate_sessions(self) -> None:
        # Private SDK state: terminate() is the only way to end an open GET
        # stream, which uvicorn's graceful shutdown would otherwise wait for.
        for transport in list(self._mcp.session_manager._server_instances.values()):
            await transport.terminate()

    async def _publish_listening(self) -> None:
        await self._publish(
            McpServerStatusChanged(McpServerState.LISTENING, port=self.port)
        )

    async def _publish_failed(self, reason: str) -> None:
        await self._publish(
            McpServerStatusChanged(McpServerState.FAILED, reason=reason)
        )

    async def _publish(self, event: McpServerStatusChanged) -> None:
        await self._bus.publish(McpServerStatusChanged, event)


async def _complete_despite_cancellation(work: Coroutine[Any, Any, None]) -> None:
    """Runs `work` to the end even if the awaiting task is cancelled again
    meanwhile; the caller re-raises its own cancellation afterwards."""
    task = asyncio.ensure_future(work)
    while not task.done():
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.shield(task)
    task.result()


def prepare_mcp_mode_server(
    settings: McpModeSettings, voice_guide: SpeakQueue, bus: EventBus
) -> McpModeServer:
    """Everything that can fail at startup, done synchronously: reads or
    creates the token, binds the configured port, builds the server. Raises
    McpTokenFileError or McpPortUnavailableError."""
    token = load_or_create_token(Path(settings.token_file))
    listener = bind_mcp_listener(settings.port)
    try:
        return McpModeServer(
            listener=listener,
            token=token,
            settings=settings,
            voice_guide=voice_guide,
            bus=bus,
        )
    except BaseException:
        listener.close()
        raise
