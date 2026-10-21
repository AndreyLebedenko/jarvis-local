"""The only code that talks to the external provider.

It sends one `OutboundPayload` and streams the answer back as text deltas. It
logs nothing, never retries, and reports every failure as an
`ExternalClientError` that carries no content.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TypeVar

import httpx

from jarvis.core.config import PersonalProxySettings
from jarvis.personal_proxy.external_endpoint import require_secure_endpoint
from jarvis.personal_proxy.external_error import (
    ExternalClientError,
    ExternalErrorKind,
)
from jarvis.personal_proxy.external_key import key_problem
from jarvis.personal_proxy.external_limits import MAX_ANSWER_CHARS, MAX_LINE_BYTES
from jarvis.personal_proxy.external_lines import iter_lines
from jarvis.personal_proxy.external_logging import external_call_scope
from jarvis.personal_proxy.external_request import (
    build_http_request,
    encode_request_body,
)
from jarvis.personal_proxy.external_sse import parse_event_line
from jarvis.personal_proxy.payload import OutboundPayload

_T = TypeVar("_T")
_FINISH_STOP = "stop"
_FINISH_LENGTH = "length"
_TRANSPORT_FAILURES = (httpx.HTTPError, httpx.InvalidURL, OSError)


async def _within(deadline: float, awaitable: Awaitable[_T]) -> _T:
    with external_call_scope():
        async with asyncio.timeout_at(deadline):
            return await awaitable


def _failure_kind(error: Exception, response_started: bool) -> ExternalErrorKind:
    if isinstance(error, TimeoutError | httpx.TimeoutException):
        return ExternalErrorKind.TIMEOUT
    if response_started:
        return ExternalErrorKind.BAD_STREAM
    return ExternalErrorKind.CONNECT_FAILED


@asynccontextmanager
async def _sent(
    client: httpx.AsyncClient, request: httpx.Request
) -> AsyncIterator[httpx.Response]:
    response = await client.send(request, stream=True)
    try:
        yield response
    finally:
        await response.aclose()


class ExternalClient:
    __slots__ = ("_environ", "_settings", "_transport")

    def __init__(
        self,
        settings: PersonalProxySettings,
        *,
        environ: Mapping[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._environ = os.environ if environ is None else environ
        self._transport = transport

    def __repr__(self) -> str:
        return "ExternalClient()"

    def stream(self, payload: OutboundPayload) -> AsyncIterator[str]:
        """Validation happens here, before any key is sent or socket opened.

        Any exception raised while iterating means the text already yielded is
        an incomplete answer and must be discarded by the consumer. No proxy
        and no netrc are used (trust_env is off).
        """
        if type(payload) is not OutboundPayload:
            raise TypeError("the external client sends only an OutboundPayload")
        require_secure_endpoint(self._settings.endpoint)
        self._require_usable_key()
        body = encode_request_body(self._settings, payload)
        request = build_http_request(self._settings.endpoint, self._read_key(), body)
        return self._answer(request)

    def _require_usable_key(self) -> None:
        problem = key_problem(self._environ.get(self._settings.api_key_env, ""))
        if problem is not None:
            raise ExternalClientError(problem)

    def _read_key(self) -> str:
        return self._environ[self._settings.api_key_env].strip()

    def _new_http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            timeout=httpx.Timeout(
                self._settings.request_timeout_seconds,
                connect=self._settings.connect_timeout_seconds,
            ),
            follow_redirects=False,
            trust_env=False,
        )

    async def _answer(self, request: httpx.Request) -> AsyncIterator[str]:
        deadline = asyncio.get_running_loop().time() + (
            self._settings.request_timeout_seconds
        )
        response_started = False
        failure: ExternalErrorKind | None = None
        try:
            async with AsyncExitStack() as stack:
                client = await stack.enter_async_context(self._new_http_client())
                try:
                    response = await _within(
                        deadline, stack.enter_async_context(_sent(client, request))
                    )
                finally:
                    del request
                response_started = True
                if not response.is_success:
                    raise ExternalClientError(
                        ExternalErrorKind.HTTP_STATUS, response.status_code
                    )
                async for text in self._texts(response, deadline):
                    yield text
        except ExternalClientError:
            raise
        except (TimeoutError, *_TRANSPORT_FAILURES) as error:
            failure = _failure_kind(error, response_started)
        except Exception:
            failure = ExternalErrorKind.UNEXPECTED
        if failure is not None:
            raise ExternalClientError(failure) from None

    async def _texts(
        self, response: httpx.Response, deadline: float
    ) -> AsyncIterator[str]:
        lines = iter_lines(response.aiter_raw(), MAX_LINE_BYTES)
        delivered = 0
        try:
            while True:
                line = await _within(deadline, anext(lines, None))
                if line is None:
                    raise ExternalClientError(ExternalErrorKind.BAD_STREAM)
                event = parse_event_line(line)
                if event is None:
                    continue
                delivered += len(event.text)
                if delivered > MAX_ANSWER_CHARS:
                    raise ExternalClientError(ExternalErrorKind.TOO_LARGE)
                if event.text:
                    yield event.text
                if event.finish_reason == _FINISH_LENGTH:
                    raise ExternalClientError(ExternalErrorKind.TRUNCATED)
                if event.finish_reason not in (None, _FINISH_STOP):
                    raise ExternalClientError(ExternalErrorKind.BAD_STREAM)
                if event.done or event.finish_reason == _FINISH_STOP:
                    break
        finally:
            await lines.aclose()
        if not delivered:
            raise ExternalClientError(ExternalErrorKind.EMPTY_ANSWER)
