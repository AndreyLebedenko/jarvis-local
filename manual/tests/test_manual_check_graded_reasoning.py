import base64

from jarvis.core.bus import EventBus
from jarvis.core.config import BackendSettings
from jarvis.dialog.backend import OllamaBackend
from jarvis.dialog.thinking_mode import ReasoningLevel
from manual.manual_check_graded_reasoning import (
    LEVELS,
    build_probe_request,
    classify_chunks,
    content_has_inline_reasoning,
    create_probe_png_b64,
)


def _backend() -> OllamaBackend:
    settings = BackendSettings(model="test-model", num_ctx=123)
    return OllamaBackend(EventBus(), settings)


def test_all_four_product_levels_are_covered_in_order():
    assert LEVELS == (
        ReasoningLevel.OFF,
        ReasoningLevel.LOW,
        ReasoningLevel.MEDIUM,
        ReasoningLevel.HIGH,
    )


def test_build_request_off_sets_think_false():
    request = build_probe_request(_backend(), "calculation", ReasoningLevel.OFF, 1)

    assert request.payload["think"] is False


def test_build_request_sets_exact_graded_string_think_values():
    for level in (ReasoningLevel.LOW, ReasoningLevel.MEDIUM, ReasoningLevel.HIGH):
        request = build_probe_request(_backend(), "multi_step", level, 1)

        assert request.payload["think"] == level.value


def test_build_request_reuses_backend_model_and_options():
    settings = BackendSettings(model="test-model", num_ctx=123)
    backend = OllamaBackend(EventBus(), settings)

    request = build_probe_request(backend, "calculation", ReasoningLevel.OFF, 1)

    assert request.payload["model"] == "test-model"
    assert request.payload["stream"] is True
    assert request.payload["options"] == {"num_ctx": 123}


def test_build_text_probe_request_has_no_images_field():
    request = build_probe_request(_backend(), "calculation", ReasoningLevel.OFF, 1)
    [message] = request.payload["messages"]

    assert "images" not in message


def test_build_image_probe_request_uses_images_field():
    request = build_probe_request(_backend(), "image", ReasoningLevel.HIGH, 1)

    [message] = request.payload["messages"]
    assert "images" in message
    assert len(message["images"]) == 1


def test_probe_png_is_base64_png():
    decoded = base64.b64decode(create_probe_png_b64())

    assert decoded.startswith(b"\x89PNG\r\n\x1a\n")


def test_inline_reasoning_marker_detection():
    assert content_has_inline_reasoning("<think>I should count</think> Answer")
    assert content_has_inline_reasoning("<thinking>I should count</thinking> Answer")
    assert not content_has_inline_reasoning("Plain final answer only.")


def test_classify_chunks_separates_thinking_from_content_and_reports_eval_count():
    chunks = [
        {"message": {"thinking": "step one. "}},
        {"message": {"thinking": "step two."}},
        {"message": {"content": "42"}},
        {"done": True, "eval_count": 17},
    ]

    result = classify_chunks(
        "calculation", ReasoningLevel.MEDIUM, 1, chunks, wall_seconds=0.5
    )

    assert result.success is True
    assert result.eval_count == 17
    assert result.content_text == "42"
    assert result.thinking_text == "step one. step two."
    assert result.thinking_char_count == len("step one. step two.")
    assert result.reasoning_leaked_into_content is False


def test_classify_chunks_without_done_chunk_is_not_success():
    chunks = [{"message": {"content": "42"}}]

    result = classify_chunks(
        "calculation", ReasoningLevel.OFF, 1, chunks, wall_seconds=0.1
    )

    assert result.success is False


def test_classify_chunks_reports_transport_error_as_not_success():
    result = classify_chunks(
        "calculation", ReasoningLevel.LOW, 1, [], wall_seconds=0.1, error="boom"
    )

    assert result.success is False
    assert result.error == "boom"


def test_classify_chunks_flags_reasoning_leaked_into_content():
    chunks = [
        {"message": {"content": "<think>oops</think> 42"}},
        {"done": True, "eval_count": 5},
    ]

    result = classify_chunks(
        "calculation", ReasoningLevel.HIGH, 1, chunks, wall_seconds=0.1
    )

    assert result.reasoning_leaked_into_content is True
