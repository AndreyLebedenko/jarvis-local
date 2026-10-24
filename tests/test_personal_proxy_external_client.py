import asyncio
import contextlib
import json
import logging
import socket
import traceback

import httpx
import pytest

from jarvis.core.config import PersonalProxySettings
from jarvis.personal_proxy.common.payload import build_outbound_payload
from jarvis.personal_proxy.external.external_client import ExternalClient
from jarvis.personal_proxy.external.external_error import (
    ExternalClientError,
    ExternalErrorKind,
)

KEY = "sk-test-KEY-4711"
KEY_ENV = "JARVIS_PERSONAL_PROXY_KEY"
SYSTEM_TEXT = "SYSTEM-TEXT-ABC"
REQUEST_TEXT = "REQUEST-TEXT-XYZ"
SERVER_BODY = "SERVER-BODY-QQQ"
ENDPOINT = "https://provider.example/v1/chat/completions"
PAYLOAD = build_outbound_payload(SYSTEM_TEXT, REQUEST_TEXT)
SECRETS = (KEY, SYSTEM_TEXT, REQUEST_TEXT, SERVER_BODY, "provider.example")
EXPECTED_BODY = {
    "model": "test-model",
    "messages": [
        {"role": "system", "content": SYSTEM_TEXT},
        {"role": "user", "content": REQUEST_TEXT},
    ],
    "stream": True,
}
DONE = "data: [DONE]\n\n"


def _delta(text):
    return f"data: {json.dumps({'choices': [{'delta': {'content': text}}]})}\n\n"


def _finish(reason):
    event = {"choices": [{"delta": {}, "finish_reason": reason}]}
    return f"data: {json.dumps(event)}\n\n"


def _settings(endpoint=ENDPOINT, **changes):
    return PersonalProxySettings(endpoint=endpoint, model="test-model", **changes)


def _client(handler, settings=None, environ=None):
    return ExternalClient(
        settings or _settings(),
        environ={KEY_ENV: KEY} if environ is None else environ,
        transport=httpx.MockTransport(handler),
    )


class _ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self._chunks = chunks

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk.encode()


def _sse_response(*chunks):
    return httpx.Response(
        200,
        headers={"Content-Type": "text/event-stream"},
        stream=_ChunkStream(chunks),
    )


async def _collect(client, payload=PAYLOAD):
    async def run():
        return [text async for text in client.stream(payload)]

    return await asyncio.wait_for(run(), timeout=10)


async def _error_of(client, payload=PAYLOAD):
    with pytest.raises(ExternalClientError) as caught:
        await _collect(client, payload)
    return caught.value


def _assert_carries_no_secret(error):
    rendered = repr(error) + str(error) + "".join(traceback.format_exception(error))
    for secret in SECRETS:
        assert secret not in rendered
    assert error.__cause__ is None
    assert error.__context__ is None


class TestRequest:
    async def test_body_and_headers_hold_only_the_allowed_keys(self):
        seen = {}

        def handler(request):
            seen["method"] = request.method
            seen["url"] = str(request.url)
            seen["headers"] = dict(request.headers)
            seen["body"] = json.loads(request.content)
            return _sse_response(_delta("ok"), DONE)

        await _collect(_client(handler))

        assert seen["method"] == "POST"
        assert seen["url"] == ENDPOINT
        assert seen["body"] == EXPECTED_BODY
        assert seen["headers"]["authorization"] == f"Bearer {KEY}"
        assert seen["headers"]["content-type"] == "application/json"
        assert set(seen["headers"]) <= {
            "host",
            "authorization",
            "content-type",
            "content-length",
            "accept",
            "accept-encoding",
            "connection",
            "user-agent",
        }

    async def test_key_is_read_from_the_environment_at_each_call(self):
        environ = {KEY_ENV: "first-key"}
        used = []

        def handler(request):
            used.append(request.headers["authorization"])
            return _sse_response(_delta("ok"), DONE)

        client = _client(handler, environ=environ)
        await _collect(client)
        environ[KEY_ENV] = "second-key"
        await _collect(client)

        assert used == ["Bearer first-key", "Bearer second-key"]

    async def test_a_custom_key_variable_name_is_honoured(self):
        client = _client(
            lambda request: _sse_response(_delta("ok"), DONE),
            _settings(api_key_env="MY_OTHER_KEY"),
            environ={"MY_OTHER_KEY": KEY},
        )

        assert await _collect(client) == ["ok"]


class TestAnswer:
    async def test_deltas_are_yielded_in_order_until_done(self):
        client = _client(
            lambda request: _sse_response(_delta("Hel"), _delta("lo"), DONE)
        )

        assert await _collect(client) == ["Hel", "lo"]

    async def test_events_split_mid_line_across_chunks_are_reassembled(self):
        stream = _delta("Hello") + _delta(" world") + DONE
        chunks = [stream[i : i + 7] for i in range(0, len(stream), 7)]
        client = _client(lambda request: _sse_response(*chunks))

        assert await _collect(client) == ["Hello", " world"]

    async def test_roles_comments_empty_deltas_and_unknown_fields_are_ignored(self):
        role = 'data: {"choices":[{"delta":{"role":"assistant"}}],"x":1}\n\n'
        empty = 'data: {"choices":[{"delta":{"content":""}}]}\n\n'
        client = _client(
            lambda request: _sse_response(
                ": keep-alive\n\n", "event: chunk\n", role, empty, _delta("A"), DONE
            )
        )

        assert await _collect(client) == ["A"]

    async def test_finish_reason_stop_is_a_clean_end_without_done(self):
        client = _client(lambda request: _sse_response(_delta("A"), _finish("stop")))

        assert await _collect(client) == ["A"]

    async def test_text_in_the_same_event_as_stop_is_not_lost(self):
        event = {"choices": [{"delta": {"content": "Z"}, "finish_reason": "stop"}]}
        client = _client(
            lambda request: _sse_response(f"data: {json.dumps(event)}\n\n")
        )

        assert await _collect(client) == ["Z"]


class TestStreamErrors:
    @pytest.mark.parametrize(
        "chunks",
        [
            (_delta("partial"),),
            (_delta("partial"), "data: {broken\n\n", DONE),
            (_delta("partial"), "data: [1,2]\n\n", DONE),
            (_delta("partial"), 'data: {"choices":[{"delta":{"content":7}}]}\n\n'),
            (_delta("partial"), _finish("content_filter"), DONE),
        ],
        ids=["no-clean-end", "invalid-json", "not-object", "non-text", "odd-finish"],
    )
    async def test_malformed_or_unfinished_stream_is_bad_stream(self, chunks):
        error = await _error_of(_client(lambda request: _sse_response(*chunks)))

        assert error.kind is ExternalErrorKind.BAD_STREAM
        assert error.status is None

    async def test_finish_reason_length_is_truncation_after_the_text_arrived(self):
        client = _client(
            lambda request: _sse_response(_delta("cut"), _finish("length"), DONE)
        )
        received = []

        with pytest.raises(ExternalClientError) as caught:
            async for text in client.stream(PAYLOAD):
                received.append(text)

        assert received == ["cut"]
        assert caught.value.kind is ExternalErrorKind.TRUNCATED
        assert "not a complete answer" in str(caught.value)

    @pytest.mark.parametrize(
        "chunks",
        [(DONE,), (_finish("stop"),), ('data: {"choices":[{"delta":{}}]}\n\n', DONE)],
    )
    async def test_an_answer_without_text_is_empty_answer(self, chunks):
        error = await _error_of(_client(lambda request: _sse_response(*chunks)))

        assert error.kind is ExternalErrorKind.EMPTY_ANSWER

    async def test_a_connection_lost_mid_stream_is_bad_stream(self):
        class Broken(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield _delta("a").encode()
                raise httpx.ReadError(f"{SERVER_BODY} {KEY}")

        client = _client(lambda request: httpx.Response(200, stream=Broken()))

        error = await _error_of(client)

        assert error.kind is ExternalErrorKind.BAD_STREAM
        _assert_carries_no_secret(error)


class TestHttpErrors:
    @pytest.mark.parametrize("status", [401, 429, 500, 302, 404])
    async def test_a_non_2xx_status_is_an_http_error_with_its_number(self, status):
        client = _client(
            lambda request: httpx.Response(
                status,
                text=SERVER_BODY,
                headers={"Location": "https://other.example/x"},
            )
        )

        error = await _error_of(client)

        assert error.kind is ExternalErrorKind.HTTP_STATUS
        assert error.status == status
        _assert_carries_no_secret(error)


class TestRefusalsBeforeNetwork:
    async def test_a_non_payload_argument_is_a_type_error(self):
        calls = []
        client = _client(lambda request: calls.append(request))

        for argument in ("plain text", {"messages": []}, None):
            with pytest.raises(TypeError):
                client.stream(argument)

        assert calls == []

    async def test_a_non_payload_argument_is_refused_before_the_key_is_read(self):
        client = ExternalClient(_settings(), environ=_FatalEnviron())

        with pytest.raises(TypeError):
            client.stream("plain text")

    async def test_a_missing_or_blank_key_is_refused_before_any_request(self):
        calls = []
        for environ in ({}, {KEY_ENV: ""}, {KEY_ENV: "  \n"}):
            client = _client(lambda request: calls.append(request), environ=environ)

            with pytest.raises(ExternalClientError) as caught:
                client.stream(PAYLOAD)

            assert caught.value.kind is ExternalErrorKind.KEY_MISSING
        assert calls == []

    async def test_a_non_loopback_http_endpoint_is_refused_before_the_key_is_read(
        self,
    ):
        client = ExternalClient(
            _settings("http://provider.example/v1/chat"), environ=_FatalEnviron()
        )

        with pytest.raises(ExternalClientError) as caught:
            client.stream(PAYLOAD)

        assert caught.value.kind is ExternalErrorKind.INSECURE_ENDPOINT
        _assert_carries_no_secret(caught.value)


class _FatalEnviron(dict):
    def get(self, *args):
        raise AssertionError("the key was read")


class TestFailures:
    async def test_a_connect_error_is_connect_failed_without_its_text(self):
        def handler(request):
            raise httpx.ConnectError(f"{KEY} {REQUEST_TEXT} provider.example")

        error = await _error_of(_client(handler))

        assert error.kind is ExternalErrorKind.CONNECT_FAILED
        _assert_carries_no_secret(error)

    async def test_a_connect_timeout_is_a_timeout(self):
        def handler(request):
            raise httpx.ConnectTimeout("slow")

        error = await _error_of(_client(handler))

        assert error.kind is ExternalErrorKind.TIMEOUT

    async def test_a_trickling_stream_hits_the_overall_deadline(self):
        class Trickle(httpx.AsyncByteStream):
            async def __aiter__(self):
                while True:
                    await asyncio.sleep(0.05)
                    yield _delta("x").encode()

        client = _client(
            lambda request: httpx.Response(200, stream=Trickle()),
            _settings(request_timeout_seconds=0.4),
        )
        loop = asyncio.get_running_loop()
        started = loop.time()

        error = await _error_of(client)

        assert error.kind is ExternalErrorKind.TIMEOUT
        assert loop.time() - started < 2

    async def test_a_response_that_never_starts_hits_the_overall_deadline(self):
        async def handler(request):
            await asyncio.sleep(30)

        client = _client(handler, _settings(request_timeout_seconds=0.3))

        error = await _error_of(client)

        assert error.kind is ExternalErrorKind.TIMEOUT


class TestNothingIsLogged:
    @pytest.mark.parametrize(
        "handler",
        [
            lambda request: _sse_response(_delta("ok"), DONE),
            lambda request: httpx.Response(500, text=SERVER_BODY),
            lambda request: _sse_response(_delta("a"), "data: {bad\n\n"),
            lambda request: _sse_response(_delta("a"), _finish("length")),
            lambda request: _sse_response(DONE),
        ],
        ids=["success", "http", "bad-stream", "truncated", "empty"],
    )
    async def test_no_log_record_at_any_level(self, handler, caplog):
        caplog.set_level(logging.DEBUG)
        client = _client(handler)

        with contextlib.suppress(ExternalClientError):
            await _collect(client)

        assert caplog.records == []

    async def test_no_logger_level_is_changed(self):
        names = ("httpx", "httpcore")
        before = {name: logging.getLogger(name).level for name in names}

        await _collect(_client(lambda request: _sse_response(_delta("ok"), DONE)))

        assert {name: logging.getLogger(name).level for name in names} == before

    async def test_reprs_do_not_show_the_endpoint_the_key_or_the_text(self):
        client = _client(lambda request: _sse_response(_delta("ok"), DONE))

        rendered = repr(client) + str(client) + repr(PAYLOAD)

        for secret in SECRETS:
            assert secret not in rendered


class FakeServer:
    def __init__(self, script):
        self._script = script
        self.requests = []
        self._server = None

    async def start(self):
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self

    @property
    def endpoint(self):
        port = self._server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}/v1/chat/completions"

    async def stop(self):
        self._server.close()
        try:
            async with asyncio.timeout(5):
                await self._server.wait_closed()
        except TimeoutError:
            pass

    async def _handle(self, reader, writer):
        try:
            async with asyncio.timeout(10):
                head = await reader.readuntil(b"\r\n\r\n")
                lines = head.decode().split("\r\n")
                headers = {
                    key.lower(): value
                    for key, value in (
                        line.split(": ", 1) for line in lines[1:] if line
                    )
                }
                length = int(headers.get("content-length", 0))
                body = await reader.readexactly(length)
                self.requests.append((lines[0], headers, body))
                await self._script(writer)
        except (TimeoutError, asyncio.IncompleteReadError, OSError):
            pass
        finally:
            writer.close()


def _http_head():
    return (
        b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
        b"Connection: close\r\n\r\n"
    )


async def _stream_script(writer, *chunks, pause=0.0):
    writer.write(_http_head())
    for chunk in chunks:
        writer.write(chunk.encode())
        await writer.drain()
        await asyncio.sleep(pause)


@pytest.fixture
async def serve():
    servers = []

    async def start(script):
        server = await FakeServer(script).start()
        servers.append(server)
        return server

    yield start
    for server in servers:
        await server.stop()


def _real_client(endpoint, **changes):
    return ExternalClient(_settings(endpoint, **changes), environ={KEY_ENV: KEY})


class TestThroughARealLoopbackSocket:
    async def test_request_bytes_and_a_split_stream_over_http_loopback(self, serve):
        stream = _delta("Hello") + _delta(" there") + DONE

        async def script(writer):
            await _stream_script(
                writer, stream[:11], stream[11:40], stream[40:], pause=0.02
            )

        server = await serve(script)

        texts = await asyncio.wait_for(
            _collect(_real_client(server.endpoint)), timeout=10
        )

        assert texts == ["Hello", " there"]
        request_line, headers, body = server.requests[0]
        assert request_line == "POST /v1/chat/completions HTTP/1.1"
        assert headers["authorization"] == f"Bearer {KEY}"
        assert headers["content-type"] == "application/json"
        assert json.loads(body) == EXPECTED_BODY

    async def test_a_redirect_is_an_error_and_the_second_host_sees_nothing(self, serve):
        async def target_script(writer):
            await _stream_script(writer, _delta("leaked"), DONE)

        target = await serve(target_script)

        async def redirect_script(writer):
            writer.write(
                f"HTTP/1.1 302 Found\r\nLocation: {target.endpoint}\r\n"
                "Content-Length: 0\r\nConnection: close\r\n\r\n".encode()
            )
            await writer.drain()

        redirector = await serve(redirect_script)

        error = await asyncio.wait_for(
            _error_of(_real_client(redirector.endpoint)), timeout=10
        )

        assert error.kind is ExternalErrorKind.HTTP_STATUS
        assert error.status == 302
        assert len(redirector.requests) == 1
        assert target.requests == []

    async def test_a_slow_trickling_server_hits_the_overall_deadline(self, serve):
        async def script(writer):
            await _stream_script(writer, *[_delta("x")] * 200, pause=0.05)

        server = await serve(script)
        client = _real_client(server.endpoint, request_timeout_seconds=0.5)

        error = await asyncio.wait_for(_error_of(client), timeout=10)

        assert error.kind is ExternalErrorKind.TIMEOUT

    async def test_nothing_is_logged_through_a_real_socket(self, serve, caplog):
        async def script(writer):
            await _stream_script(writer, _delta("ok"), DONE)

        server = await serve(script)
        caplog.set_level(logging.DEBUG)

        await asyncio.wait_for(_collect(_real_client(server.endpoint)), timeout=10)

        not_httpcore = [r for r in caplog.records if not r.name.startswith("httpcore")]
        assert not_httpcore == []

    async def test_a_refused_connection_is_connect_failed(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        client = _real_client(f"http://127.0.0.1:{port}/v1/chat")

        error = await asyncio.wait_for(_error_of(client), timeout=10)

        assert error.kind is ExternalErrorKind.CONNECT_FAILED
        _assert_carries_no_secret(error)
