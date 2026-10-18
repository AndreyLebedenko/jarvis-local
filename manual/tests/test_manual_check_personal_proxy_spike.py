import asyncio
import base64
import json

import httpx
import pytest

from jarvis.core.bus import EventBus
from jarvis.core.config import BackendSettings, GenerationOptions
from jarvis.dialog.backend import OllamaBackend
from jarvis.dialog.thinking_mode import ReasoningLevel
from jarvis.journal.transcription import (
    DEFAULT_TRANSCRIPTION_INSTRUCTION,
    build_transcription_messages,
)
from manual.manual_check_personal_proxy_spike import (
    OllamaModelCaller,
    parse_args,
    redact_audio,
)
from manual.personal_proxy_audio import sha256_hex
from manual.personal_proxy_prompts import COMBINED_SCHEMA
from manual.personal_proxy_records import CallStage
from manual.personal_proxy_runner import PlannedRequest

WAV = b"RIFFfakewavbytes"


def _ndjson(*chunks):
    return ("\n".join(json.dumps(c) for c in chunks) + "\n").encode("utf-8")


def _caller(handler):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://ollama.test"
    )
    backend = OllamaBackend(EventBus(), BackendSettings(), client)
    return OllamaModelCaller(backend, client), backend


def _ok_handler(captured):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            content=_ndjson(
                {"message": {"content": "Позво"}},
                {"message": {"content": "ни"}},
                {
                    "message": {"content": ""},
                    "done": True,
                    "done_reason": "stop",
                    "eval_count": 7,
                    "prompt_eval_count": 11,
                    "load_duration": 2_000_000_000,
                },
            ),
        )

    return handler


def _request(stage=CallStage.TRANSCRIBE, response_format=None, audio=WAV):
    messages = tuple(
        {"role": m.role, "content": m.content}
        for m in build_transcription_messages(DEFAULT_TRANSCRIPTION_INSTRUCTION)
    )
    return PlannedRequest(
        stage,
        messages,
        audio,
        GenerationOptions(seed=3, num_predict=64),
        response_format,
    )


def test_transcription_payload_matches_the_production_builder_exactly():
    captured = []
    caller, backend = _caller(_ok_handler(captured))
    request = _request()

    asyncio.run(caller(request))

    expected = backend.build_payload(
        list(request.messages),
        [base64.b64encode(WAV).decode("ascii")],
        ReasoningLevel.OFF,
        options=request.options,
    )
    assert captured == [expected]
    assert "format" not in captured[0]


def test_audio_travels_in_the_images_field_never_an_audio_field():
    captured = []
    caller, _ = _caller(_ok_handler(captured))

    asyncio.run(caller(_request()))

    message = captured[0]["messages"][-1]
    assert message["images"] == [base64.b64encode(WAV).decode("ascii")]
    assert "audio" not in message


def test_constrained_format_is_added_to_the_payload_only_when_requested():
    captured = []
    caller, _ = _caller(_ok_handler(captured))

    asyncio.run(caller(_request(CallStage.COMBINED, COMBINED_SCHEMA)))

    assert captured[0]["format"] == COMBINED_SCHEMA


def test_record_has_text_metrics_and_a_redacted_request():
    caller, _ = _caller(_ok_handler([]))

    record = asyncio.run(caller(_request()))

    assert record.response_text == "Позвони"
    assert (record.done_reason, record.eval_count, record.prompt_eval_count) == (
        "stop",
        7,
        11,
    )
    assert record.load_seconds == 2.0
    assert record.total_seconds >= 0
    recorded_images = record.request["messages"][-1]["images"]
    assert recorded_images == [f"[audio wav sha256={sha256_hex(WAV)} bytes={len(WAV)}]"]
    assert base64.b64encode(WAV).decode("ascii") not in json.dumps(record.request)


def test_a_text_only_request_has_no_images_and_is_recorded_unchanged():
    captured = []
    caller, _ = _caller(_ok_handler(captured))

    record = asyncio.run(caller(_request(audio=None)))

    assert "images" not in captured[0]["messages"][-1]
    assert record.request == captured[0]


def test_http_errors_raise_with_the_status_and_body():
    caller, _ = _caller(lambda request: httpx.Response(500, content=b"model gone"))

    with pytest.raises(RuntimeError, match="500.*model gone"):
        asyncio.run(caller(_request()))


def test_an_error_chunk_in_the_stream_raises():
    caller, _ = _caller(
        lambda request: httpx.Response(200, content=_ndjson({"error": "boom"}))
    )

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(caller(_request()))


def test_redact_audio_leaves_payloads_without_audio_alone():
    payload = {"messages": [{"role": "user", "content": "x"}]}

    assert redact_audio(payload, None) == payload


def test_cli_requires_wavs_for_every_subcommand():
    for command in ("stage0", "run", "score"):
        with pytest.raises(SystemExit):
            parse_args([command])
        assert parse_args([command, "--wavs", "w"]).command == command


def test_out_goes_before_the_subcommand():
    args = parse_args(["--out", "somewhere", "run", "--wavs", "w"])

    assert str(args.out) == "somewhere"
