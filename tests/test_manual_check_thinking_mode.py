import base64

from config import BackendSettings
from manual_check_thinking_mode import (
    THINKING_PARAM,
    build_probe_request,
    content_has_inline_reasoning,
    create_probe_png_b64,
)


def test_build_text_probe_request_sets_think_false():
    settings = BackendSettings(model="test-model", num_ctx=123)

    request = build_probe_request(settings, "text", "off")

    assert request.payload["model"] == "test-model"
    assert request.payload[THINKING_PARAM] is False
    assert request.payload["stream"] is True
    assert request.payload["options"] == {"num_ctx": 123}
    [message] = request.payload["messages"]
    assert "images" not in message


def test_build_media_probe_request_sets_think_true_and_uses_images_field():
    settings = BackendSettings(model="test-model", num_ctx=123)

    request = build_probe_request(settings, "media", "on")

    assert request.payload[THINKING_PARAM] is True
    [message] = request.payload["messages"]
    assert "images" in message
    assert len(message["images"]) == 1


def test_probe_png_is_base64_png():
    encoded = create_probe_png_b64()

    decoded = base64.b64decode(encoded)

    assert decoded.startswith(b"\x89PNG\r\n\x1a\n")


def test_inline_reasoning_marker_detection():
    assert content_has_inline_reasoning("<think>I should count</think> Answer")
    assert content_has_inline_reasoning("<thinking>I should count</thinking> Answer")
    assert not content_has_inline_reasoning("Plain final answer only.")
