import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from jarvis.audio.replay import ReplayOutcome
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    BackendSettings,
    PersonalProxySettings,
    Settings,
    VadSettings,
)
from jarvis.personal_proxy.proxy_assembly import (
    ProxyHost,
    ProxySeams,
    local_check_client,
    prepare_personal_proxy_runtime,
)
from jarvis.personal_proxy.startup_failure import (
    ProxyStartupError,
    StartupFailureKind,
)
from jarvis.personal_proxy.stt_engine import (
    MissingSpeechDependencyError,
    SpeechDeviceError,
    SpeechModelUnavailableError,
)
from jarvis.personal_proxy.stt_result import Transcription

PROXY = PersonalProxySettings(
    endpoint="https://api.example.test/v1",
    model="remote-model",
    check_model="gemma4:12b",
    check_num_ctx=8192,
)
SETTINGS = Settings(
    personal_proxy=PROXY,
    backend=BackendSettings(endpoint="http://localhost:11434"),
    vad=VadSettings(resume_cooldown_seconds=0.5),
)
ENVIRON = {"JARVIS_PERSONAL_PROXY_KEY": "sk-test-key"}
TAGS = {"models": [{"name": "gemma4:12b"}, {"name": "other:latest"}]}


class _Ollama:
    """A scripted local Ollama behind a mock transport; logs what it is asked."""

    def __init__(self, log, *, tags=TAGS, tags_status=200, chat_ok=True, replies=()):
        self.log = log
        self.replies = list(replies)
        self.tags = tags
        self.tags_status = tags_status
        self.chat_ok = chat_ok
        self.chat_requests = []
        self.clients = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            self.log.append("tags")
            if self.tags_status != 200:
                return httpx.Response(self.tags_status)
            return httpx.Response(200, json=self.tags)
        self.log.append("chat")
        self.chat_requests.append(json.loads(request.content))
        if not self.chat_ok:
            return httpx.Response(200, content=json.dumps({"error": "boom"}) + "\n")
        content = self.replies.pop(0) if self.replies else "ok"
        chunk = {"message": {"content": content}, "done": True, "done_reason": "stop"}
        return httpx.Response(200, content=json.dumps(chunk) + "\n")

    def make_client(self, backend):
        client = httpx.AsyncClient(
            base_url=backend.endpoint,
            transport=httpx.MockTransport(self.handler),
        )
        self.clients.append(client)
        return client


class _Engine:
    def transcribe(self, clip):
        return Transcription("", (), ())


class _Transport:
    def __init__(self):
        self.blocks = []

    def publish_proxy_block(self, payload):
        self.blocks.append(payload)

    def set_module_health(self, health):
        pass

    def set_data_locality(self, locality):
        pass


class _Audio:
    async def auto_pause_for_speech(self):
        pass

    async def auto_resume_after_speech(self):
        pass


class _Player:
    def start_run(self, items):
        return ReplayOutcome.DISABLED

    async def wait_for_pending(self):
        pass

    def cancel(self):
        return False


async def _report_dropped():
    return None


def _host(settings=SETTINGS, transport=None):
    return ProxyHost(
        settings=settings,
        bus=EventBus(),
        audio_input=_Audio(),
        player=_Player(),
        transport=transport or _Transport(),
        report_dropped=_report_dropped,
    )


def _seams(
    log, ollama, *, engine_error=None, environ=ENVIRON, probabilities_error=None
):
    def load_engine(settings):
        log.append("engine")
        if engine_error is not None:
            raise engine_error
        return _Engine()

    def load_probabilities():
        log.append("probabilities")
        if probabilities_error is not None:
            raise probabilities_error
        return lambda clip: None

    return ProxySeams(
        environ=environ,
        load_engine=load_engine,
        load_probabilities=load_probabilities,
        make_client=ollama.make_client,
    )


async def _prepare(log, ollama, settings=SETTINGS, **seam_changes):
    return await prepare_personal_proxy_runtime(
        _host(settings), _seams(log, ollama, **seam_changes)
    )


async def _failure(
    log, ollama, settings=SETTINGS, **seam_changes
) -> StartupFailureKind:
    with pytest.raises(ProxyStartupError) as raised:
        await _prepare(log, ollama, settings, **seam_changes)
    return raised.value.kind


async def test_a_successful_preparation_checks_ollama_then_loads_then_warms_up():
    log = []

    runtime = await _prepare(log, _Ollama(log))

    assert log == ["tags", "engine", "probabilities", "chat"]
    await runtime.stop()


async def test_the_warm_up_loads_the_check_model_at_its_own_context_size():
    log = []
    ollama = _Ollama(log)

    runtime = await _prepare(log, ollama)

    request = ollama.chat_requests[0]
    assert request["model"] == "gemma4:12b"
    assert request["options"]["num_ctx"] == 8192
    assert [message["role"] for message in request["messages"]] == ["user"]
    assert "images" not in request["messages"][-1]
    await runtime.stop()


async def test_the_second_client_is_closed_when_the_runtime_stops():
    log = []
    ollama = _Ollama(log)

    runtime = await _prepare(log, ollama)
    assert not ollama.clients[0].is_closed
    await runtime.stop()

    assert ollama.clients[0].is_closed


@pytest.mark.parametrize(
    ("settings", "environ", "kind"),
    [
        (
            replace(PROXY, topics_file="no_such_topics_file.txt"),
            ENVIRON,
            StartupFailureKind.TOPICS_FILE,
        ),
        (PROXY, {}, StartupFailureKind.API_KEY),
        (PROXY, {"JARVIS_PERSONAL_PROXY_KEY": "  "}, StartupFailureKind.API_KEY),
        (
            replace(PROXY, endpoint="http://api.example.test/v1"),
            ENVIRON,
            StartupFailureKind.ENDPOINT,
        ),
    ],
)
async def test_a_bad_setting_stops_before_anything_is_opened_or_loaded(
    settings, environ, kind
):
    log = []
    ollama = _Ollama(log)

    result = await _failure(
        log, ollama, replace(SETTINGS, personal_proxy=settings), environ=environ
    )

    assert result is kind
    assert log == []
    assert ollama.clients == []


async def test_a_loopback_http_endpoint_is_accepted():
    log = []
    settings = replace(
        SETTINGS, personal_proxy=replace(PROXY, endpoint="http://127.0.0.1:8080/v1")
    )

    runtime = await _prepare(log, _Ollama(log), settings)

    await runtime.stop()


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (MissingSpeechDependencyError("x"), StartupFailureKind.SPEECH_DEPENDENCY),
        (SpeechModelUnavailableError("x"), StartupFailureKind.SPEECH_MODEL),
        (SpeechDeviceError("x"), StartupFailureKind.SPEECH_DEVICE),
    ],
)
async def test_a_speech_engine_that_cannot_load_is_named_and_the_client_closed(
    error, kind
):
    log = []
    ollama = _Ollama(log)

    assert await _failure(log, ollama, engine_error=error) is kind

    assert ollama.clients[0].is_closed
    assert "probabilities" not in log


async def test_an_unreachable_ollama_stops_before_the_speech_engine_loads():
    log = []
    ollama = _Ollama(log, tags_status=500)

    assert await _failure(log, ollama) is StartupFailureKind.OLLAMA

    assert "engine" not in log
    assert ollama.clients[0].is_closed


async def test_a_check_model_that_is_not_installed_is_named():
    log = []
    ollama = _Ollama(log, tags={"models": [{"name": "other:latest"}]})

    assert await _failure(log, ollama) is StartupFailureKind.CHECK_MODEL

    assert "engine" not in log


async def test_a_check_model_without_a_tag_matches_latest():
    log = []
    ollama = _Ollama(log, tags={"models": [{"model": "gemma4:latest"}]})
    settings = replace(SETTINGS, personal_proxy=replace(PROXY, check_model="gemma4"))

    runtime = await _prepare(log, ollama, settings)

    await runtime.stop()


async def test_a_check_model_that_does_not_answer_the_warm_up_is_named():
    log = []
    ollama = _Ollama(log, chat_ok=False)

    assert await _failure(log, ollama) is StartupFailureKind.WARM_UP

    assert ollama.clients[0].is_closed


async def test_an_unexpected_error_is_reported_without_its_text():
    log = []
    secret = "C:\\Users\\private\\topics.txt"
    ollama = _Ollama(log)

    with pytest.raises(ProxyStartupError) as raised:
        await _prepare(log, ollama, probabilities_error=RuntimeError(secret))

    assert raised.value.kind is StartupFailureKind.INTERNAL
    assert secret not in str(raised.value)
    assert raised.value.__cause__ is None
    assert ollama.clients[0].is_closed


async def test_every_failure_kind_has_a_message_in_both_languages():
    from jarvis.ui.text import ui_text

    for kind in StartupFailureKind:
        for language in ("en", "ru"):
            assert ui_text(kind.ui_text_key, language)


def test_the_second_client_reads_for_at_least_two_minutes():
    short = local_check_client(BackendSettings(read_timeout_seconds=30.0))
    long = local_check_client(BackendSettings(read_timeout_seconds=300.0))

    assert short.timeout.read == 120.0
    assert long.timeout.read == 300.0
    assert str(short.base_url).startswith("http://localhost:11434")


async def test_a_cancelled_preparation_still_closes_the_client():
    import asyncio

    log = []
    ollama = _Ollama(log)

    def cancelling_engine(settings):
        raise asyncio.CancelledError

    seams = _seams(log, ollama)
    seams = replace(seams, load_engine=cancelling_engine)

    task = asyncio.ensure_future(prepare_personal_proxy_runtime(_host(), seams))
    with pytest.raises(BaseException):  # noqa: B017
        await task

    assert ollama.clients[0].is_closed


# --- the settings reach the service, not the defaults ---------------------------

TOPIC = "секретная тема"
SANITIZE_REPLY = json.dumps(
    {
        "verdict": "send",
        "reason": "",
        "sanitized_text": f"Расскажи про {TOPIC} подробнее",
        "mapping": {},
    },
    ensure_ascii=False,
)


class _NoExternal:
    def __init__(self, settings):
        self.opened = []

    def stream(self, payload):
        self.opened.append(payload)
        raise AssertionError("the gate must have blocked this payload")


def _custom_settings(tmp_path):
    topics = tmp_path / "topics.txt"
    topics.write_text(TOPIC + "\n", encoding="utf-8")
    proxy = replace(
        PROXY,
        dry_run=False,
        topics_file=str(topics),
        confirmation_timeout_seconds=7.5,
        doubt_min_listed=3,
    )
    return replace(
        SETTINGS,
        personal_proxy=proxy,
        vad=VadSettings(resume_cooldown_seconds=0.75),
        ui=replace(SETTINGS.ui, language="ru"),
    )


async def _custom_runtime(tmp_path, monkeypatch, ollama, transport):
    from jarvis.personal_proxy import proxy_assembly

    captured = {}

    class _RecordingService(proxy_assembly.PersonalProxyService):
        def __init__(self, **kwargs):
            captured["service"] = kwargs
            super().__init__(**kwargs)

    class _RecordingGate(proxy_assembly.AudioMicrophoneGate):
        def __init__(self, audio_input, cooldown_seconds, *args):
            captured["cooldown"] = cooldown_seconds
            super().__init__(audio_input, cooldown_seconds, *args)

    monkeypatch.setattr(proxy_assembly, "PersonalProxyService", _RecordingService)
    monkeypatch.setattr(proxy_assembly, "AudioMicrophoneGate", _RecordingGate)
    seams = replace(_seams([], ollama), make_external=_NoExternal)
    settings = _custom_settings(tmp_path)
    runtime = await prepare_personal_proxy_runtime(_host(settings, transport), seams)
    return runtime, captured, settings


async def _until_blocked(transport):
    for _ in range(500):
        if any(b.get("kind") == "gate_blocked" for b in transport.blocks):
            return
        await asyncio.sleep(0.01)


async def test_the_service_gets_the_configured_settings_topics_and_cooldown(
    tmp_path, monkeypatch
):
    ollama = _Ollama([])

    runtime, captured, settings = await _custom_runtime(
        tmp_path, monkeypatch, ollama, _Transport()
    )

    service = captured["service"]
    assert service["settings"] == settings.personal_proxy
    assert service["settings"].dry_run is False
    assert service["settings"].confirmation_timeout_seconds == 7.5
    assert service["settings"].doubt_min_listed == 3
    assert TOPIC in service["topics_text"]
    assert captured["cooldown"] == 0.75
    await runtime.stop()


async def test_a_topic_phrase_in_the_outbound_text_is_blocked_by_the_gate(
    tmp_path, monkeypatch
):
    ollama = _Ollama([], replies=["ok", SANITIZE_REPLY])
    transport = _Transport()
    runtime, _, _ = await _custom_runtime(tmp_path, monkeypatch, ollama, transport)
    runtime.start()

    result = await runtime.submit_text("Расскажи подробнее")
    await _until_blocked(transport)
    await runtime.stop()

    assert result.accepted
    assert "gate_blocked" in [b.get("kind") for b in transport.blocks]
    assert not any(b["type"] == "sent" for b in transport.blocks)


async def test_the_sanitize_request_carries_the_topics_text(tmp_path, monkeypatch):
    ollama = _Ollama([], replies=["ok", SANITIZE_REPLY])
    transport = _Transport()
    runtime, _, _ = await _custom_runtime(tmp_path, monkeypatch, ollama, transport)
    runtime.start()

    await runtime.submit_text("Расскажи подробнее")
    await _until_blocked(transport)
    await runtime.stop()

    assert TOPIC in json.dumps(ollama.chat_requests[1], ensure_ascii=False)


async def test_notices_are_shown_in_the_configured_ui_language(tmp_path, monkeypatch):
    ollama = _Ollama([], replies=["ok", SANITIZE_REPLY])
    transport = _Transport()
    runtime, _, _ = await _custom_runtime(tmp_path, monkeypatch, ollama, transport)
    runtime.start()

    await runtime.submit_text("Расскажи подробнее")
    await _until_blocked(transport)
    await runtime.stop()

    blocked = next(b for b in transport.blocks if b.get("kind") == "gate_blocked")
    assert blocked["text"].startswith("Заблокировано")


def test_the_second_client_ignores_proxy_variables_of_the_environment(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("NO_PROXY", "")

    client = local_check_client(BackendSettings())

    assert client._trust_env is False
    assert client._mounts == {} or all(
        "proxy.invalid" not in str(getattr(t, "_pool", ""))
        for t in client._mounts.values()
    )
