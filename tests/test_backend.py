import base64
import json

import httpx
import pytest

from backend import LatencyMetrics, OllamaBackend, ResponseComplete, ResponseToken
from bus import EventBus
from config import BackendSettings


def _fake_audio_b64() -> str:
    return base64.b64encode(b"not-really-a-wav").decode()


def test_payload_places_media_under_images_never_under_audio():
    backend = OllamaBackend(bus=EventBus(), settings=BackendSettings())
    media = [_fake_audio_b64()]

    payload = backend.build_payload(
        messages=[{"role": "user", "content": "what did I say?"}],
        images_b64=media,
    )

    assert payload["messages"][-1]["images"] == media
    assert "audio" not in payload
    for message in payload["messages"]:
        assert "audio" not in message


def test_payload_without_media_has_no_images_key():
    backend = OllamaBackend(bus=EventBus(), settings=BackendSettings())

    payload = backend.build_payload(messages=[{"role": "user", "content": "hi"}])

    assert "images" not in payload["messages"][-1]


def test_payload_defaults_to_thinking_disabled():
    backend = OllamaBackend(bus=EventBus(), settings=BackendSettings())

    payload = backend.build_payload(messages=[{"role": "user", "content": "hi"}])

    assert payload["think"] is False


def test_payload_thinking_enabled_sets_think_true():
    backend = OllamaBackend(bus=EventBus(), settings=BackendSettings())

    payload = backend.build_payload(
        messages=[{"role": "user", "content": "hi"}], thinking_enabled=True
    )

    assert payload["think"] is True


def test_payload_uses_model_and_num_ctx_from_settings():
    settings = BackendSettings(model="custom-model", num_ctx=1234)
    backend = OllamaBackend(bus=EventBus(), settings=settings)

    payload = backend.build_payload(messages=[{"role": "user", "content": "hi"}])

    assert payload["model"] == "custom-model"
    assert payload["options"]["num_ctx"] == 1234


def test_payload_includes_configured_flash_attention_and_kv_cache_type():
    settings = BackendSettings(
        model="custom-model",
        num_ctx=1234,
        flash_attention=True,
        kv_cache_type="q8_0",
    )
    backend = OllamaBackend(bus=EventBus(), settings=settings)

    payload = backend.build_payload(messages=[{"role": "user", "content": "hi"}])

    assert payload["options"] == {
        "num_ctx": 1234,
        "flash_attention": True,
        "kv_cache_type": "q8_0",
    }


def test_payload_preserves_an_explicit_false_flash_attention_value():
    settings = BackendSettings(flash_attention=False)
    backend = OllamaBackend(bus=EventBus(), settings=settings)

    payload = backend.build_payload(messages=[{"role": "user", "content": "hi"}])

    assert payload["options"]["flash_attention"] is False


def test_default_client_uses_configured_read_timeout():
    """Regression test: httpx's own default timeout (~5 s total) is too
    short for a genuinely cold Ollama start - verified live, it raised
    httpx.ReadTimeout. settings.read_timeout_seconds must actually reach
    the client this class constructs when no client is injected."""
    settings = BackendSettings(read_timeout_seconds=42.0)
    backend = OllamaBackend(bus=EventBus(), settings=settings)

    assert backend._client.timeout.read == 42.0


def _ndjson_fixture_body() -> bytes:
    lines = [
        {"message": {"content": "Hello"}, "done": False},
        {"message": {"content": " world"}, "done": False},
        {
            "message": {"content": ""},
            "done": True,
            "load_duration": 300_000_000,
            "prompt_eval_duration": 200_000_000,
            "eval_duration": 1_000_000_000,
            "eval_count": 87,
        },
    ]
    return "\n".join(json.dumps(line) for line in lines).encode() + b"\n"


def _client_with_fixture_response() -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_ndjson_fixture_body())

    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://localhost:11434"
    )


async def test_streamed_tokens_are_republished_in_order():
    bus = EventBus()
    received = []

    async def on_token(token: ResponseToken) -> None:
        received.append(token.text)

    bus.subscribe(ResponseToken, on_token)

    backend = OllamaBackend(
        bus=bus, settings=BackendSettings(), client=_client_with_fixture_response()
    )
    await backend.chat(messages=[{"role": "user", "content": "hi"}])

    assert received == ["Hello", " world"]


async def test_latency_metrics_parsed_and_published_on_completion():
    bus = EventBus()
    received = []

    async def on_complete(event: ResponseComplete) -> None:
        received.append(event)

    bus.subscribe(ResponseComplete, on_complete)

    backend = OllamaBackend(
        bus=bus, settings=BackendSettings(), client=_client_with_fixture_response()
    )
    await backend.chat(messages=[{"role": "user", "content": "hi"}])

    assert received == [
        ResponseComplete(
            metrics=LatencyMetrics(
                load_seconds=0.3,
                prompt_eval_seconds=0.2,
                eval_seconds=1.0,
                eval_count=87,
            )
        )
    ]


def _client_with_ndjson_body(lines: list[dict]) -> httpx.AsyncClient:
    body = "\n".join(json.dumps(line) for line in lines).encode() + b"\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://localhost:11434"
    )


async def test_thinking_chunks_never_published_as_response_token():
    bus = EventBus()
    received = []

    async def on_token(token: ResponseToken) -> None:
        received.append(token.text)

    bus.subscribe(ResponseToken, on_token)

    lines = [
        {"message": {"thinking": "reasoning step one", "content": ""}, "done": False},
        {"message": {"thinking": "reasoning step two", "content": ""}, "done": False},
        {"message": {"content": "Hello"}, "done": False},
        {"message": {"content": ""}, "done": True, "eval_count": 1},
    ]
    backend = OllamaBackend(
        bus=bus, settings=BackendSettings(), client=_client_with_ndjson_body(lines)
    )
    await backend.chat(messages=[{"role": "user", "content": "hi"}], thinking_enabled=True)

    assert received == ["Hello"]


async def test_thinking_only_stream_publishes_no_response_token():
    bus = EventBus()
    received = []

    async def on_token(token: ResponseToken) -> None:
        received.append(token.text)

    bus.subscribe(ResponseToken, on_token)

    lines = [
        {"message": {"thinking": "reasoning only", "content": ""}, "done": False},
        {"message": {"content": ""}, "done": True, "eval_count": 1},
    ]
    backend = OllamaBackend(
        bus=bus, settings=BackendSettings(), client=_client_with_ndjson_body(lines)
    )
    await backend.chat(messages=[{"role": "user", "content": "hi"}], thinking_enabled=True)

    assert received == []


async def test_stream_ending_without_done_still_publishes_response_complete():
    """Regression test: if Ollama's connection closes/ends the stream
    without ever sending a `done: true` chunk, chat() must still publish
    ResponseComplete - otherwise Orchestrator.finish_turn() (subscribed to
    ResponseComplete, see main.py) never runs and _busy stays True forever,
    permanently ignoring every later utterance/clipboard turn as "previous
    request still in flight"."""
    bus = EventBus()
    received = []

    async def on_complete(event: ResponseComplete) -> None:
        received.append(event)

    bus.subscribe(ResponseComplete, on_complete)

    lines = [
        {"message": {"content": "Hello"}, "done": False},
        {"message": {"content": " world"}, "done": False},
    ]
    backend = OllamaBackend(
        bus=bus, settings=BackendSettings(), client=_client_with_ndjson_body(lines)
    )
    await backend.chat(messages=[{"role": "user", "content": "hi"}])

    assert received == [ResponseComplete(metrics=LatencyMetrics(0.0, 0.0, 0.0, 0))]


async def test_stream_ending_without_done_still_republishes_seen_tokens():
    bus = EventBus()
    received = []

    async def on_token(token: ResponseToken) -> None:
        received.append(token.text)

    bus.subscribe(ResponseToken, on_token)

    lines = [{"message": {"content": "Hello"}, "done": False}]
    backend = OllamaBackend(
        bus=bus, settings=BackendSettings(), client=_client_with_ndjson_body(lines)
    )
    await backend.chat(messages=[{"role": "user", "content": "hi"}])

    assert received == ["Hello"]
