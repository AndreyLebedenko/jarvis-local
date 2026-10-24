import asyncio
import json
import logging

import httpx
import pytest

from jarvis.core.config import PersonalProxySettings
from jarvis.personal_proxy.common import payload as payload_module
from jarvis.personal_proxy.common.payload import OutboundPayload, build_outbound_payload
from jarvis.personal_proxy.external.external_client import ExternalClient
from jarvis.personal_proxy.external.external_error import (
    ExternalClientError,
    ExternalErrorKind,
)
from jarvis.personal_proxy.external.external_limits import (
    MAX_ANSWER_CHARS,
    MAX_LINE_BYTES,
)
from jarvis.personal_proxy.external.external_lines import iter_lines

KEY = "sk-test-KEY-4711"
KEY_ENV = "JARVIS_PERSONAL_PROXY_KEY"
REQUEST_TEXT = "REQUEST-TEXT-XYZ"
ENDPOINT = "https://provider.example/v1/chat/completions"
PAYLOAD = build_outbound_payload("system", REQUEST_TEXT)
DONE = "data: [DONE]\n\n"


def _delta(text):
    return f"data: {json.dumps({'choices': [{'delta': {'content': text}}]})}\n\n"


def _settings(**changes):
    return PersonalProxySettings(endpoint=ENDPOINT, model="m", **changes)


class _Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self._chunks = chunks

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk if isinstance(chunk, bytes) else chunk.encode()


def _response(*chunks):
    return httpx.Response(200, stream=_Chunks(chunks))


def _client(handler, environ=None, **settings):
    return ExternalClient(
        _settings(**settings),
        environ={KEY_ENV: KEY} if environ is None else environ,
        transport=httpx.MockTransport(handler),
    )


async def _collect(client, payload=PAYLOAD):
    async def run():
        return [text async for text in client.stream(payload)]

    return await asyncio.wait_for(run(), timeout=10)


async def _error_of(client, payload=PAYLOAD):
    with pytest.raises(ExternalClientError) as caught:
        await _collect(client, payload)
    return caught.value


def _frame_locals(error):
    traceback = error.__traceback__
    while traceback is not None:
        frame = traceback.tb_frame
        if frame.f_globals["__name__"].startswith("jarvis."):
            yield from frame.f_locals.values()
        traceback = traceback.tb_next


def _assert_no_secret_in_frames(error, secrets):
    for value in _frame_locals(error):
        shown = [repr(value)]
        if isinstance(value, str):
            shown.append(value)
        elif isinstance(value, bytes | bytearray):
            shown.append(bytes(value).decode("utf-8", errors="replace"))
        for secret in secrets:
            assert all(secret not in text for text in shown)


class TestUntypedExceptionsCannotLeak:
    @pytest.mark.parametrize(
        "key",
        ["café-key", "key\r\nX-Evil: 1", "a b", "key\x7f", "k\x00", "кл"],
    )
    async def test_an_unsendable_key_is_key_invalid(self, key):
        client = _client(lambda request: pytest.fail("sent"), {KEY_ENV: key})

        with pytest.raises(ExternalClientError) as caught:
            client.stream(PAYLOAD)

        assert caught.value.kind is ExternalErrorKind.KEY_INVALID
        assert caught.value.status is None
        assert key not in repr(caught.value) + str(caught.value)
        _assert_no_secret_in_frames(caught.value, [key])

    async def test_a_key_with_surrounding_whitespace_is_trimmed_and_sent(self):
        seen = []

        def handler(request):
            seen.append(request.headers["authorization"])
            return _response(_delta("ok"), DONE)

        await _collect(_client(handler, {KEY_ENV: f"  {KEY}\n"}))

        assert seen == [f"Bearer {KEY}"]

    async def test_a_lone_surrogate_in_the_text_is_bad_request(self):
        text = "bad \ud800 text SURROGATE-MARK"
        payload = build_outbound_payload("system", text)
        client = _client(lambda request: pytest.fail("sent"))

        with pytest.raises(ExternalClientError) as caught:
            client.stream(payload)

        assert caught.value.kind is ExternalErrorKind.BAD_REQUEST
        assert "SURROGATE-MARK" not in repr(caught.value) + str(caught.value)
        assert caught.value.__context__ is None
        _assert_no_secret_in_frames(caught.value, ["SURROGATE-MARK", KEY])

    async def test_an_unexpected_failure_is_typed_without_its_text(self):
        def handler(request):
            raise RuntimeError(f"boom {KEY} {REQUEST_TEXT}")

        error = await _error_of(_client(handler))

        assert error.kind is ExternalErrorKind.UNEXPECTED
        assert error.__context__ is None
        assert KEY not in repr(error) + str(error)

    async def test_cancellation_is_not_swallowed(self):
        async def handler(request):
            await asyncio.sleep(30)

        client = _client(handler)

        async def run():
            return [text async for text in client.stream(PAYLOAD)]

        task = asyncio.create_task(run())
        await asyncio.sleep(0.1)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=5)


class TestOnlyExactlyAnOutboundPayload:
    async def test_a_subclass_is_refused(self):
        class Sneaky(OutboundPayload):
            pass

        sneaky = Sneaky((), _token=payload_module._CONSTRUCTION_TOKEN)
        client = _client(lambda request: pytest.fail("sent"))

        with pytest.raises(TypeError):
            client.stream(sneaky)


class TestSizeCaps:
    async def test_the_request_asks_for_an_identity_encoding(self):
        seen = []

        def handler(request):
            seen.append(request.headers["accept-encoding"])
            return _response(_delta("ok"), DONE)

        await _collect(_client(handler))

        assert seen == ["identity"]

    async def test_an_endless_line_without_newline_is_too_large_and_reading_stops(
        self,
    ):
        produced = []

        class Endless(httpx.AsyncByteStream):
            async def __aiter__(self):
                while True:
                    produced.append(1)
                    yield b"x" * 1024

        client = _client(lambda request: httpx.Response(200, stream=Endless()))

        error = await _error_of(client)

        assert error.kind is ExternalErrorKind.TOO_LARGE
        assert len(produced) <= MAX_LINE_BYTES // 1024 + 2

    async def test_an_oversized_total_answer_is_too_large_and_reading_stops(self):
        produced = []
        received = []

        class Endless(httpx.AsyncByteStream):
            async def __aiter__(self):
                while True:
                    produced.append(1)
                    yield _delta("y" * 10_000).encode()

        client = _client(lambda request: httpx.Response(200, stream=Endless()))

        with pytest.raises(ExternalClientError) as caught:
            async for text in client.stream(PAYLOAD):
                received.append(text)

        assert caught.value.kind is ExternalErrorKind.TOO_LARGE
        assert sum(map(len, received)) <= MAX_ANSWER_CHARS
        assert len(produced) <= MAX_ANSWER_CHARS // 10_000 + 2

    async def test_an_answer_exactly_at_the_cap_is_accepted(self):
        piece = 10_000
        events = [_delta("z" * piece)] * (MAX_ANSWER_CHARS // piece)
        client = _client(lambda request: _response(*events, DONE))

        assert sum(map(len, await _collect(client))) == MAX_ANSWER_CHARS

    async def test_a_single_event_line_over_the_line_cap_is_too_large(self):
        client = _client(lambda request: _response(_delta("z" * MAX_LINE_BYTES), DONE))

        error = await _error_of(client)

        assert error.kind is ExternalErrorKind.TOO_LARGE

    async def test_a_line_at_the_cap_is_accepted_by_the_line_reader(self):
        async def chunks():
            yield b"a" * MAX_LINE_BYTES + b"\nlast"

        lines = [line async for line in iter_lines(chunks(), MAX_LINE_BYTES)]

        assert [len(line) for line in lines] == [MAX_LINE_BYTES, 4]

    async def test_a_gzip_declared_answer_is_not_expanded(self):
        class Bomb(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"\x1f\x8b\x08\x00 not really gzip"

        client = _client(
            lambda request: httpx.Response(
                200, headers={"Content-Encoding": "gzip"}, stream=Bomb()
            )
        )

        error = await _error_of(client)

        assert error.kind is ExternalErrorKind.BAD_STREAM


class TestLineReader:
    async def test_crlf_and_split_lines_and_a_final_line_without_newline(self):
        async def chunks():
            yield b"data: a\r\nda"
            yield b"ta: b\n\nlast"

        lines = [line async for line in iter_lines(chunks(), 1024)]

        assert lines == ["data: a", "data: b", "", "last"]

    async def test_a_leading_bom_is_removed_from_the_first_line_only(self):
        async def chunks():
            yield "﻿data: a\n﻿data: b\n".encode()

        lines = [line async for line in iter_lines(chunks(), 1024)]

        assert lines == ["data: a", "﻿data: b"]

    async def test_the_first_event_survives_a_bom_end_to_end(self):
        client = _client(
            lambda request: _response("﻿" + _delta("first"), _delta("x"), DONE)
        )

        assert await _collect(client) == ["first", "x"]

    async def test_invalid_utf8_becomes_replacement_characters(self):
        async def chunks():
            yield b"\xff\xfe\n"

        lines = [line async for line in iter_lines(chunks(), 1024)]

        assert lines == ["��"]


class TestEventContent:
    async def test_an_error_event_after_text_is_bad_stream(self):
        error_event = 'data: {"error": {"message": "overloaded"}}\n\n'
        client = _client(lambda request: _response(_delta("a"), error_event, DONE))

        error = await _error_of(client)

        assert error.kind is ExternalErrorKind.BAD_STREAM

    async def test_deeply_nested_json_is_bad_stream(self):
        nested = "data: " + "[" * 30000 + "]" * 30000 + "\n\n"
        client = _client(lambda request: _response(_delta("a"), nested, DONE))

        error = await _error_of(client)

        assert error.kind is ExternalErrorKind.BAD_STREAM

    async def test_only_the_choice_with_index_zero_is_used(self):
        event = {
            "choices": [
                {"index": 1, "delta": {"content": "second"}},
                {"index": 0, "delta": {"content": "first"}},
            ]
        }
        client = _client(
            lambda request: _response(f"data: {json.dumps(event)}\n\n", DONE)
        )

        assert await _collect(client) == ["first"]


class TestSecretsAreNotKeptInFrames:
    async def test_frames_of_a_late_error_hold_neither_key_nor_text(self):
        client = _client(lambda request: _response(_delta("a"), "data: {bad\n\n"))

        error = await _error_of(client)

        _assert_no_secret_in_frames(error, [KEY, REQUEST_TEXT])

    async def test_frames_of_an_http_error_hold_neither_key_nor_text(self):
        client = _client(lambda request: httpx.Response(500))

        error = await _error_of(client)

        _assert_no_secret_in_frames(error, [KEY, REQUEST_TEXT])


class TestHttpxLogFilter:
    async def test_the_call_leaves_no_httpx_record_at_info_or_debug(self, caplog):
        caplog.set_level(logging.DEBUG)
        caplog.set_level(logging.DEBUG, logger="httpx")

        await _collect(_client(lambda request: _response(_delta("ok"), DONE)))

        assert [r for r in caplog.records if r.name.startswith("http")] == []

    async def test_httpx_itself_does_log_so_the_filter_is_what_silences_it(
        self, caplog
    ):
        caplog.set_level(logging.INFO, logger="httpx")
        transport = httpx.MockTransport(lambda request: httpx.Response(200))

        async with httpx.AsyncClient(transport=transport) as plain:
            await plain.get("http://plain.example/")

        assert [r for r in caplog.records if r.name == "httpx"]

    async def test_an_unrelated_httpx_record_during_the_call_is_kept(self, caplog):
        caplog.set_level(logging.INFO, logger="httpx")
        inside = asyncio.Event()
        release = asyncio.Event()

        async def handler(request):
            inside.set()
            await release.wait()
            return _response(_delta("ok"), DONE)

        task = asyncio.create_task(_collect(_client(handler)))
        await asyncio.wait_for(inside.wait(), timeout=5)
        logging.getLogger("httpx").info("UNRELATED-RECORD")
        release.set()
        await task

        messages = [r.getMessage() for r in caplog.records if r.name == "httpx"]
        assert messages == ["UNRELATED-RECORD"]

    async def test_the_filter_is_installed_once(self):
        for _ in range(3):
            await _collect(_client(lambda request: _response(_delta("ok"), DONE)))

        filters = [
            f
            for f in logging.getLogger("httpx").filters
            if type(f).__name__ == "_DropDuringExternalCall"
        ]
        assert len(filters) == 1


class TestTrustEnvIsOff:
    async def test_a_proxy_environment_does_not_reroute_the_call(self, monkeypatch):
        monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
        monkeypatch.setenv("ALL_PROXY", "http://proxy.invalid:3128")
        seen = []

        class Spy(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                seen.append(request.url.host)
                return httpx.Response(200, stream=_Chunks([_delta("ok"), DONE]))

        client = ExternalClient(_settings(), environ={KEY_ENV: KEY}, transport=Spy())
        await _collect(client)

        assert seen == ["provider.example"]

    async def test_the_http_client_is_built_without_trust_env(self, monkeypatch):
        built = []
        real = httpx.AsyncClient

        def spy(*args, **kwargs):
            built.append(kwargs)
            return real(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", spy)

        await _collect(_client(lambda request: _response(_delta("ok"), DONE)))

        assert built[0]["trust_env"] is False
        assert built[0]["follow_redirects"] is False


class TestDeadlinesFailInsteadOfHanging:
    async def test_a_trickle_is_cut_off_by_the_overall_deadline(self):
        class Trickle(httpx.AsyncByteStream):
            async def __aiter__(self):
                while True:
                    await asyncio.sleep(0.02)
                    yield b": keep-alive\n"

        client = _client(
            lambda request: httpx.Response(200, stream=Trickle()),
            request_timeout_seconds=0.3,
        )

        error = await asyncio.wait_for(_error_of(client), timeout=3)

        assert error.kind is ExternalErrorKind.TIMEOUT
