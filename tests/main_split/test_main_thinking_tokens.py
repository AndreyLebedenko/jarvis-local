import json

import httpx

from jarvis.app import (
    build_app,
    wire,
)
from jarvis.audio.input import (
    UtteranceChunk,
)
from jarvis.audio.tts import TtsOutput
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    BackendSettings,
    JournalSettings,
    PromptSettings,
    ResponseSettings,
    Settings,
    TtsSettings,
)
from jarvis.dialog.backend import (
    OllamaBackend,
    ResponseComplete,
    ResponseToken,
)
from jarvis.dialog.thinking_mode import (
    ReasoningLevel,
)
from jarvis.journal import (
    JournalStore,
)
from tests.main_split._support_from_test_main import (
    _FakeAudioInput,
    _FakeCaptureInput,
    _settings,
)

# --- thinking-token isolation through the real bus (task-13) ---------------


def _client_with_ndjson_body(lines: list[dict]) -> httpx.AsyncClient:
    body = "\n".join(json.dumps(line) for line in lines).encode() + b"\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://localhost:11434"
    )


class _RecordingTtsOutput:
    """Records exactly what reaches on_token - the real regression check
    for the story's hard rule (message.thinking must never reach TTS),
    exercised through the real bus/wire() wiring rather than backend.py's
    own unit tests, which only check backend.py in isolation."""

    def __init__(self) -> None:
        self.received_texts: list[str] = []

    async def on_request_started(self, event) -> None:
        pass

    async def on_token(self, event: ResponseToken) -> None:
        self.received_texts.append(event.text)

    async def on_response_complete(self, event: ResponseComplete) -> None:
        pass

    async def wait_for_pending(self) -> None:
        return None


async def test_thinking_chunks_never_reach_tts_through_real_bus_wiring():
    lines = [
        {"message": {"thinking": "reasoning step one", "content": ""}, "done": False},
        {"message": {"thinking": "reasoning step two", "content": ""}, "done": False},
        {"message": {"content": "Hello"}, "done": False},
        {"message": {"content": ""}, "done": True, "eval_count": 1},
    ]
    bus = EventBus()
    backend = OllamaBackend(
        bus=bus, settings=BackendSettings(), client=_client_with_ndjson_body(lines)
    )
    tts_output = _RecordingTtsOutput()

    app = build_app(
        _settings(),
        bus=bus,
        backend=backend,
        audio_input=_FakeAudioInput(),
        tts_output=tts_output,
        capture_input=_FakeCaptureInput(),
    )
    wire(app)

    await backend.chat(
        messages=[{"role": "user", "content": "hi"}],
        reasoning_level=ReasoningLevel.HIGH,
    )

    assert tts_output.received_texts == ["Hello"]


async def test_thinking_chunks_never_reach_journal_through_real_bus_wiring(tmp_path):
    lines = [
        {"message": {"thinking": "reasoning step one", "content": ""}, "done": False},
        {"message": {"thinking": "reasoning step two", "content": ""}, "done": False},
        {"message": {"content": "Hello"}, "done": False},
        {"message": {"content": ""}, "done": True, "eval_count": 1},
    ]
    bus = EventBus()
    backend = OllamaBackend(
        bus=bus, settings=BackendSettings(), client=_client_with_ndjson_body(lines)
    )
    tts_output = _RecordingTtsOutput()
    settings = Settings(journal=JournalSettings(root=str(tmp_path)))

    app = build_app(
        settings,
        bus=bus,
        backend=backend,
        audio_input=_FakeAudioInput(),
        tts_output=tts_output,
        capture_input=_FakeCaptureInput(),
    )
    wire(app)

    await app.bus.publish(
        UtteranceChunk,
        UtteranceChunk(wav_bytes=b"voice clip", start_seconds=0, end_seconds=1),
    )
    assert app.journal_recorder is not None
    await app.journal_recorder.wait_for_pending()

    session_id = app.journal_recorder.session_id
    assert session_id is not None
    replay = JournalStore(tmp_path).read_session(session_id)

    assert [(event.role, event.source, event.text) for event in replay.events] == [
        ("user", "voice", ""),
        ("assistant", "assistant", "Hello"),
    ]
    assert all("reasoning" not in event.text for event in replay.events)
    assert tts_output.received_texts == ["Hello"]


def _client_with_sequential_ndjson_bodies(
    bodies: list[list[dict]],
) -> httpx.AsyncClient:
    """Like _client_with_ndjson_body, but a different canned response per
    call - mode 3's second pass (story-v1.9.0 task 3) is a real second
    POST to the same backend, not a re-read of the first."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        lines = bodies[min(call_count, len(bodies) - 1)]
        call_count += 1
        body = "\n".join(json.dumps(line) for line in lines).encode() + b"\n"
        return httpx.Response(200, content=body)

    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://localhost:11434"
    )


async def test_mode_3_derivative_reaches_tts_while_first_pass_stays_silent(tmp_path):
    """The full mode-3 flow (story-v1.9.0 task 3) through the real bus/wire()
    wiring AND the real TtsOutput (not a fake that skips its own gating
    logic): the canonical first pass streams to history/journal but never
    reaches synthesis, and the derivative second pass - a real second POST
    to the backend - is what actually gets spoken."""

    class _FakeTtsEngine:
        async def synthesize(self, text: str, language: str = "ru") -> bytes:
            return text.encode()

    played: list[str] = []

    async def fake_play(audio: bytes) -> None:
        played.append(audio.decode())

    canonical_lines = [
        {"message": {"content": "Canonical text."}, "done": False},
        {"message": {"content": ""}, "done": True, "eval_count": 1},
    ]
    derivative_lines = [
        {"message": {"content": "Derivative speech."}, "done": False},
        {"message": {"content": ""}, "done": True, "eval_count": 1},
    ]
    bus = EventBus()
    backend = OllamaBackend(
        bus=bus,
        settings=BackendSettings(),
        client=_client_with_sequential_ndjson_bodies(
            [canonical_lines, derivative_lines]
        ),
    )
    tts_output = TtsOutput(
        TtsSettings(), engine=_FakeTtsEngine(), play=fake_play, bus=bus
    )
    settings = Settings(
        journal=JournalSettings(root=str(tmp_path)),
        response=ResponseSettings(mode="text_voice"),
        prompts=PromptSettings(response_text_voice="derivative contract"),
    )

    app = build_app(
        settings,
        bus=bus,
        backend=backend,
        audio_input=_FakeAudioInput(),
        tts_output=tts_output,
        capture_input=_FakeCaptureInput(),
    )
    wire(app)

    await app.bus.publish(
        UtteranceChunk,
        UtteranceChunk(wav_bytes=b"voice clip", start_seconds=0, end_seconds=1),
    )
    assert app.journal_recorder is not None
    await app.journal_recorder.wait_for_pending()

    assert played == ["Derivative speech."]

    session_id = app.journal_recorder.session_id
    assert session_id is not None
    replay = JournalStore(tmp_path).read_session(session_id)
    [assistant_event] = [e for e in replay.events if e.role == "assistant"]
    assert assistant_event.text == "Canonical text."
    assert assistant_event.metadata["spoken_derivative"] == "Derivative speech."
