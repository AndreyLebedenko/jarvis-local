import pytest

from jarvis.personal_proxy.external_endpoint import require_secure_endpoint
from jarvis.personal_proxy.external_error import (
    ExternalClientError,
    ExternalErrorKind,
)
from jarvis.personal_proxy.external_sse import StreamEvent, parse_event_line


def _data(json_text):
    return f"data: {json_text}"


@pytest.mark.parametrize("line", ["", ": keep-alive", "event: message", "id: 7"])
def test_non_data_lines_are_not_events(line):
    assert parse_event_line(line) is None


def test_done_marker_is_a_done_event():
    assert parse_event_line("data: [DONE]") == StreamEvent(done=True)


def test_content_delta_gives_its_text():
    line = _data('{"choices":[{"delta":{"content":"Hi"}}]}')
    assert parse_event_line(line) == StreamEvent(text="Hi")


def test_data_without_a_space_after_the_colon_is_accepted():
    line = 'data:{"choices":[{"delta":{"content":"Hi"}}]}'
    assert parse_event_line(line) == StreamEvent(text="Hi")


@pytest.mark.parametrize(
    "json_text",
    [
        '{"choices":[{"delta":{"role":"assistant"}}]}',
        '{"choices":[{"delta":{"content":""}}]}',
        '{"choices":[{"delta":{"content":null}}]}',
        '{"choices":[]}',
        '{"usage":{"total_tokens":3}}',
        '{"choices":[{"delta":{"content":"","unknown":1}}],"extra":true}',
    ],
)
def test_events_without_text_give_empty_text(json_text):
    assert parse_event_line(_data(json_text)) == StreamEvent()


def test_finish_reason_is_reported():
    line = _data('{"choices":[{"delta":{},"finish_reason":"stop"}]}')
    assert parse_event_line(line) == StreamEvent(finish_reason="stop")


@pytest.mark.parametrize(
    "json_text",
    [
        "not json",
        "[1, 2]",
        '"text"',
        "null",
        '{"choices":"x"}',
        '{"choices":["x"]}',
        '{"choices":[{"delta":"x"}]}',
        '{"choices":[{"delta":{"content":5}}]}',
        '{"choices":[{"delta":{"content":["a"]}}]}',
        '{"choices":[{"delta":{},"finish_reason":3}]}',
    ],
)
def test_malformed_events_are_bad_stream(json_text):
    with pytest.raises(ExternalClientError) as caught:
        parse_event_line(_data(json_text))

    assert caught.value.kind is ExternalErrorKind.BAD_STREAM


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://api.example.com/v1/chat/completions",
        "http://localhost:8080/v1/chat",
        "http://127.0.0.1:1234/x",
        "http://[::1]:1234/x",
        "http://model.localhost/x",
        "HTTP://LOCALHOST/x",
    ],
)
def test_secure_or_loopback_endpoints_are_allowed(endpoint):
    require_secure_endpoint(endpoint)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://api.example.com/v1/chat",
        "http://192.168.1.5/v1/chat",
        "http://localhost.evil.com/x",
        "http://evillocalhost/x",
        "ftp://localhost/x",
        "localhost:8080/x",
        "",
        "http://[::1/x",
    ],
)
def test_other_endpoints_are_insecure(endpoint):
    with pytest.raises(ExternalClientError) as caught:
        require_secure_endpoint(endpoint)

    assert caught.value.kind is ExternalErrorKind.INSECURE_ENDPOINT
