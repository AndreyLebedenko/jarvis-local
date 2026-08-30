import asyncio
import time

from jarvis.app import (
    build_app,
    warm_up,
)
from jarvis.audio.sound_cues import SoundCuePlayer
from jarvis.audio.tts import BilingualTtsEngine, TtsOutput
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    HistoryAnnotationSettings,
    HistorySettings,
    JournalSettings,
    McpServerSettings,
    McpSettings,
    MemorySettings,
    MicrophoneSettings,
    PiperTtsSettings,
    PromptSettings,
    Settings,
    SileroTtsSettings,
    TtsSettings,
)
from jarvis.dialog.thinking_mode import (
    ReasoningLevel,
)
from jarvis.dialog.tool_presentation import PromptToolPresentation, ToolAwareDialog
from jarvis.tools.host import (
    McpModuleStatus,
)
from tests.main_split._support_from_test_main import (
    _FakeAudioInput,
    _FakeBackend,
    _FakeCaptureInput,
    _FakeStreamingBackend,
    _settings,
)

# --- shared playback lock (prevents device-contention crackling) -----------


def test_build_app_shares_one_playback_lock_between_tts_and_sound_cues():
    app = build_app(_settings(), backend=_FakeBackend())

    assert app.tts_output._playback_lock is app.sound_cues._playback_lock


def test_build_app_wires_the_configured_system_prompt_into_the_orchestrator(tmp_path):
    """task-v1.2.12: build_app() must bind settings.prompts.system, not the
    built-in default, so a config-file prompt actually reaches every turn."""
    settings = Settings(
        prompts=PromptSettings(system="You are Jarvis.", warmup="Hi"),
        memory=MemorySettings(root=str(tmp_path / "memory")),
    )

    app = build_app(settings, backend=_FakeBackend())

    assert app.orchestrator._system_prompt == "You are Jarvis."


async def test_build_app_appends_reasoning_section_after_loaded_memory(tmp_path):
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    (memory_root / "self.md").write_text("persona", encoding="utf-8")
    (memory_root / "memory.md").write_text("durable facts", encoding="utf-8")
    settings = Settings(
        prompts=PromptSettings(
            system="base prompt",
            warmup="Hi",
            reasoning_low="reason briefly",
        ),
        memory=MemorySettings(root=str(memory_root)),
        journal=JournalSettings(enabled=False),
    )
    backend = _FakeStreamingBackend()
    app = build_app(settings, backend=backend)
    await app.thinking_mode.set_level(ReasoningLevel.LOW, source="TEST")

    await app.orchestrator.submit_text_input("hello")

    assert backend.calls[-1][0][0] == {
        "role": "system",
        "content": (
            "base prompt\n\n"
            "[Jarvis curated self.md]\n"
            "persona\n"
            "[/Jarvis curated self.md]\n\n"
            "[Jarvis curated memory.md]\n"
            "durable facts\n"
            "[/Jarvis curated memory.md]\n\n"
            "reason briefly"
        ),
    }
    assert [reasoning_level for _messages, reasoning_level in backend.calls] == [
        ReasoningLevel.LOW
    ]


async def test_warm_up_sends_the_configured_warmup_prompt():
    backend = _FakeBackend()

    await warm_up(backend, EventBus(), "en", "Hello")

    assert backend.calls[-1][0] == [{"role": "user", "content": "Hello"}]


def test_build_app_wires_the_configured_microphone_device_into_the_stream_factory():
    """story-v1.2.4-task-3: restart-to-apply for microphone selection -
    build_app() must bind settings.microphone.device into the real
    AudioInput's stream_factory when audio_input is not injected. Never
    calls the resulting factory (would try to open a real device) -
    functools.partial inspection only, same as audio_in.py's own test."""
    settings = Settings(
        microphone=MicrophoneSettings(device="USB Headset", host_api="MME")
    )

    app = build_app(settings, backend=_FakeBackend())

    assert app.audio_input._stream_factory.keywords == {
        "device": "USB Headset",
        "host_api": "MME",
    }


def test_build_app_always_constructs_an_inert_mcp_host_when_mcp_is_disabled():
    """story-v1.4.0 task 3's own acceptance criterion: "off equals the
    capability does not exist" must be a structural fact, not just
    McpHost's own runtime behavior. Per the code-review revision, McpHost
    is now always constructed (so a later live toggle has something to
    call enable() on) - the structural guarantee lives in McpHost itself
    being side-effect-free until enable() runs, asserted here as status
    OFF; builtin tools are local in-process registrations and do not
    weaken the MCP-off invariant."""
    app = build_app(_settings(), backend=_FakeBackend())

    assert app.mcp_host is not None
    assert app.mcp_host.status == McpModuleStatus.OFF
    assert app.mcp_host.enabled is False
    tools = {tool.name: tool for tool in app.mcp_host.registry.all()}
    assert set(tools) == {
        "capture_camera_image",
        "list_session_files",
        "read_history",
        "read_history_ranges",
        "read_session_text",
        "remember",
        "search_history",
        "set_reasoning_level",
        "stat_session_file",
        "view_session_image",
        "write_session_file",
    }
    assert {tool.provider_kind for tool in tools.values()} == {"builtin"}


async def test_build_app_wires_session_files_without_forcing_session_creation(
    tmp_path,
):
    """The session-file scope provider reads the live journal session on each
    call; with no accepted turn yet there is no current session, so the tools
    report no-active-session and no loose session directory is created."""
    journal_root = tmp_path / "journal"
    settings = Settings(
        journal=JournalSettings(enabled=True, root=str(journal_root)),
        memory=MemorySettings(root=str(tmp_path / "memory")),
    )
    app = build_app(settings, backend=_FakeBackend())

    result = await app.mcp_host.dispatcher.dispatch("list_session_files", {})

    assert result.ok is False
    assert "active session" in str(result.content).lower()
    assert not journal_root.exists() or list(journal_root.iterdir()) == []


def test_build_app_constructs_an_mcp_host_when_mcp_is_enabled():
    settings = Settings(
        mcp=McpSettings(
            enabled=True, servers={"search": McpServerSettings(command="search-server")}
        )
    )

    app = build_app(settings, backend=_FakeBackend())

    assert app.mcp_host is not None
    # build_app() itself never connects - run() decides that based on
    # settings.mcp.enabled, after build_app() returns.
    assert app.mcp_host.status == McpModuleStatus.OFF
    assert app.mcp_host.enabled is False  # constructed, not yet connected


def test_build_app_constructs_annotation_generation_service_with_settings():
    settings = Settings(
        journal=JournalSettings(enabled=False),
        history=HistorySettings(
            annotation=HistoryAnnotationSettings(
                instruction="Summarize only the cited excerpt.",
                reasoning="high",
                max_concurrency=2,
                max_source_events=42,
                max_source_chars=15000,
                max_annotation_chars=3000,
            )
        ),
    )

    app = build_app(settings, backend=_FakeBackend())

    service = app.annotation_generation_service
    assert service is not None
    assert service.reasoning is ReasoningLevel.HIGH
    assert service.max_source_events == 42
    assert service.max_source_chars == 15000
    assert service._max_annotation_chars == 3000
    assert service._instruction == "Summarize only the cited excerpt."


def test_build_app_always_constructs_consolidation_planner_and_executor():
    """Unlike transcription/annotation generation, consolidation planning and
    execution have no separate enable flag - task v1.8.0-24/25 provide no
    background/automatic behavior to gate, only explicit, user-triggered
    reads and the one destructive action, so there is nothing unsafe about
    always constructing them."""
    settings = Settings(journal=JournalSettings(enabled=False))

    app = build_app(settings, backend=_FakeBackend())

    assert app.archive_overlay_repository is not None
    assert app.consolidation_planner is not None
    assert app.consolidation_executor is not None


def test_build_app_omits_annotation_generation_service_when_disabled():
    settings = Settings(
        journal=JournalSettings(enabled=False),
        history=HistorySettings(annotation=HistoryAnnotationSettings(enabled=False)),
    )

    app = build_app(settings, backend=_FakeBackend())

    assert app.annotation_generation_service is None


def test_build_app_wires_configured_tool_presentation_and_budget():
    settings = Settings(
        mcp=McpSettings(presentation_strategy="prompt", max_tool_calls_per_turn=5)
    )

    app = build_app(settings, backend=_FakeBackend())

    dialog = app.orchestrator._backend
    assert isinstance(dialog, ToolAwareDialog)
    assert isinstance(dialog._presentation, PromptToolPresentation)
    assert dialog._max_tool_calls == 5


def test_build_app_wires_configured_bilingual_tts_engine(tmp_path):
    model_path = tmp_path / "en.onnx"
    config_path = tmp_path / "en.onnx.json"
    model_path.write_bytes(b"model")
    config_path.write_text("{}", encoding="utf-8")
    settings = Settings(
        tts=TtsSettings(
            languages={
                "ru": SileroTtsSettings(),
                "en": PiperTtsSettings(model=str(model_path)),
            }
        )
    )

    app = build_app(
        settings,
        backend=_FakeBackend(),
        audio_input=_FakeAudioInput(),
        capture_input=_FakeCaptureInput(),
    )

    assert isinstance(app.tts_output._engine, BilingualTtsEngine)


def test_build_app_does_not_probe_configured_piper_paths_before_playback(tmp_path):
    settings = Settings(
        tts=TtsSettings(
            languages={
                "ru": SileroTtsSettings(),
                "en": PiperTtsSettings(model=str(tmp_path / "missing.onnx")),
            }
        )
    )

    app = build_app(
        settings,
        backend=_FakeBackend(),
        audio_input=_FakeAudioInput(),
        capture_input=_FakeCaptureInput(),
    )

    assert isinstance(app.tts_output._engine, BilingualTtsEngine)


async def test_shared_playback_lock_prevents_overlapping_device_access(
    tmp_path, monkeypatch
):
    """Exercises the real TtsOutput._default_play and
    SoundCuePlayer._default_play_file with sounddevice/soundfile mocked
    out, sharing one lock - asserts the underlying device is never
    accessed by both at once, which is what caused the audible
    crackling/tempo artifacts reported live."""
    from jarvis.audio import sound_cues as sound_cues_module
    from jarvis.audio import tts as tts_module
    from jarvis.core.config import SoundCueSettings, TtsSettings

    currently_playing = False

    def fake_play(_data, _sample_rate) -> None:
        nonlocal currently_playing
        assert not currently_playing, "overlapping device access detected"
        currently_playing = True

    def fake_wait() -> None:
        nonlocal currently_playing

        time.sleep(0.02)
        currently_playing = False

    monkeypatch.setattr(tts_module.sd, "play", fake_play)
    monkeypatch.setattr(tts_module.sd, "wait", fake_wait)
    monkeypatch.setattr(tts_module.sf, "read", lambda *a, **k: (b"samples", 48000))
    monkeypatch.setattr(
        sound_cues_module.sf, "read", lambda *a, **k: (b"samples", 22050)
    )

    cue_path = tmp_path / "thinking.wav"
    cue_path.write_bytes(b"dummy")

    lock = asyncio.Lock()

    class UnusedEngine:
        async def synthesize(self, text: str, language: str = "ru") -> bytes:
            raise AssertionError("This playback-lock test must not synthesize")

    tts_output = TtsOutput(TtsSettings(), engine=UnusedEngine(), playback_lock=lock)
    sound_cues = SoundCuePlayer(
        SoundCueSettings(thinking=str(cue_path)), playback_lock=lock
    )

    await asyncio.gather(
        tts_output._default_play(b"wav-bytes-placeholder"),
        sound_cues._default_play_file(str(cue_path)),
    )
