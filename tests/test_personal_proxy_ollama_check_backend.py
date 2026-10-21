import json

import httpx
import pytest

from jarvis.core.config import (
    BackendSettings,
    GenerationOptions,
    GenerationSettings,
    PersonalProxySettings,
    Settings,
)
from jarvis.personal_proxy.check_backend import BackendReplyError, ChatRequest
from jarvis.personal_proxy.check_prompts import JUDGE_SCHEMA
from jarvis.personal_proxy.ollama_check_backend import OllamaCheckBackend

AUDIO = "QVVESU8="


def _lines(*chunks):
    return "".join(json.dumps(chunk) + "\n" for chunk in chunks).encode()


DONE = {"message": {"content": "ok"}, "done": True, "done_reason": "stop"}


def _backend(handler, backend_settings=None, proxy_settings=None):
    client = httpx.AsyncClient(
        base_url="http://ollama.test", transport=httpx.MockTransport(handler)
    )
    return OllamaCheckBackend(
        backend_settings or BackendSettings(),
        proxy_settings or PersonalProxySettings(),
        client,
    )


def _recording(sent, reply=None):
    reply = _lines(DONE) if reply is None else reply

    def handler(request):
        sent.append(request)
        return httpx.Response(200, content=reply)

    return handler


def _request(**changes):
    fields = {
        "prompt": "check this",
        "audio_base64": AUDIO,
        "options": GenerationOptions(temperature=0.618, num_predict=2048),
    }
    return ChatRequest(**{**fields, **changes})


async def test_the_reply_is_the_concatenated_streamed_content():
    reply = _lines(
        {"message": {"content": "Позвони "}},
        {"message": {"content": "Марине"}, "done": True},
    )

    text = await _backend(_recording([], reply)).complete(_request())

    assert text == "Позвони Марине"


async def test_the_recording_goes_in_images_and_never_in_an_audio_field():
    sent = []

    await _backend(_recording(sent)).complete(_request())

    body = json.loads(sent[0].content)
    assert sent[0].url.path == "/api/chat"
    assert body["messages"] == [
        {"role": "user", "content": "check this", "images": [AUDIO]}
    ]
    assert "audio" not in body
    assert "audio" not in body["messages"][0]


async def test_the_check_model_context_and_options_come_from_the_settings():
    sent = []
    proxy = PersonalProxySettings(check_model="other:7b", check_num_ctx=4096)

    await _backend(_recording(sent), proxy_settings=proxy).complete(_request())

    body = json.loads(sent[0].content)
    assert body["model"] == "other:7b"
    assert body["options"]["num_ctx"] == 4096
    assert body["options"]["temperature"] == 0.618
    assert body["options"]["num_predict"] == 2048
    assert body["think"] is False


async def test_the_dialog_backend_load_options_still_apply():
    sent = []
    dialog = BackendSettings(model="dialog:12b", num_ctx=65536, flash_attention=True)

    await _backend(_recording(sent), dialog).complete(_request())

    body = json.loads(sent[0].content)
    assert body["model"] == "gemma4:12b"
    assert body["options"]["flash_attention"] is True


async def test_a_plain_request_sends_no_format():
    sent = []

    await _backend(_recording(sent)).complete(_request())

    assert "format" not in json.loads(sent[0].content)


async def test_the_judge_request_carries_the_constraining_schema():
    sent = []

    await _backend(_recording(sent)).complete(_request(response_format=JUDGE_SCHEMA))

    assert json.loads(sent[0].content)["format"] == JUDGE_SCHEMA


async def test_an_error_answer_is_a_failure_without_its_text():
    reply = _lines({"error": "model 'x' not found, secret detail"})

    with pytest.raises(BackendReplyError) as raised:
        await _backend(_recording([], reply)).complete(_request())

    assert str(raised.value) == ""


async def test_a_stream_that_ends_without_a_done_chunk_is_a_failure():
    reply = _lines({"message": {"content": "Позвони "}})

    with pytest.raises(BackendReplyError):
        await _backend(_recording([], reply)).complete(_request())


async def test_a_reply_stopped_at_the_length_cap_is_a_failure():
    reply = _lines(
        {"message": {"content": "Позвони"}, "done": True, "done_reason": "length"}
    )

    with pytest.raises(BackendReplyError):
        await _backend(_recording([], reply)).complete(_request())


async def test_a_non_json_error_body_is_a_failure_without_its_text():
    def handler(request):
        return httpx.Response(500, content=b"<html>secret detail</html>")

    with pytest.raises(BackendReplyError) as raised:
        await _backend(handler).complete(_request())

    assert str(raised.value) == ""


async def test_the_sampling_comes_from_the_personal_proxy_settings():
    sent = []
    proxy = PersonalProxySettings(
        check_top_p=0.8, check_top_k=30, check_min_p=0.1, check_repeat_penalty=1.2
    )
    backend = _backend(_recording(sent), proxy_settings=proxy)

    await backend.complete(_request())
    await backend.complete(
        _request(options=GenerationOptions(temperature=0.0, seed=1, num_predict=2048))
    )

    sample, judge = (json.loads(s.content)["options"] for s in sent)
    for options in (sample, judge):
        assert options["top_p"] == 0.8
        assert options["top_k"] == 30
        assert options["min_p"] == 0.1
        assert options["repeat_penalty"] == 1.2
        assert options["num_predict"] == 2048
    assert sample["temperature"] == 0.618
    assert "seed" not in sample
    assert judge["temperature"] == 0.0
    assert judge["seed"] == 1


async def test_the_default_sampling_is_the_one_the_spikes_ran_with():
    sent = []

    await _backend(_recording(sent)).complete(_request())

    options = json.loads(sent[0].content)["options"]
    assert options["top_p"] == 0.9
    assert options["top_k"] == 50
    assert options["min_p"] == 0.05
    assert options["repeat_penalty"] == 1.025


async def test_the_generation_table_does_not_reach_the_check_requests():
    sent = []
    settings = Settings(
        generation=GenerationSettings(
            defaults=GenerationOptions(top_p=0.1, top_k=1, seed=99, stop=["x"])
        )
    )
    backend = OllamaCheckBackend(
        settings.backend,
        settings.personal_proxy,
        httpx.AsyncClient(
            base_url="http://ollama.test",
            transport=httpx.MockTransport(_recording(sent)),
        ),
    )

    await backend.complete(_request())

    options = json.loads(sent[0].content)["options"]
    assert options["top_p"] == 0.9
    assert options["top_k"] == 50
    assert "seed" not in options
    assert "stop" not in options


async def test_a_text_only_request_with_a_system_message_sends_no_images():
    sent = []

    await _backend(_recording(sent)).complete(_request(audio_base64="", system="rules"))

    body = json.loads(sent[0].content)
    assert body["messages"] == [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "check this"},
    ]
