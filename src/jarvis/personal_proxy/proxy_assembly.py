"""Builds the personal proxy for a run: the checks, the second HTTP client, the
real adapters, the stages, and the service.

The order is cheap checks first (nothing is loaded for a bad topics file, key
or endpoint), then Ollama, then the speech engine and the presence model, then
the warm-up of the check model, so the first request does not meet a cold
load. Any failure closes what was opened and raises `ProxyStartupError`, which
names the kind of failure and nothing else."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from jarvis.core.bus import EventBus
from jarvis.core.config import BackendSettings, PersonalProxySettings, Settings
from jarvis.personal_proxy.answer_speaker import ReplayAnswerSpeaker, SpeechPlayer
from jarvis.personal_proxy.block_payload import JsonObject
from jarvis.personal_proxy.chat_sink import TransportChatSink
from jarvis.personal_proxy.external_client import ExternalClient
from jarvis.personal_proxy.guarded_transcription import ProbabilitySource
from jarvis.personal_proxy.journal_writer import (
    ProxyExchangeRecorder,
    ProxyJournalWriter,
)
from jarvis.personal_proxy.microphone_gate import AudioMicrophoneGate, AutoPausable
from jarvis.personal_proxy.ollama_check_backend import OllamaCheckBackend
from jarvis.personal_proxy.proxy_runtime import PersonalProxyRuntime
from jarvis.personal_proxy.proxy_service import PersonalProxyService
from jarvis.personal_proxy.proxy_submissions import ProxySubmissions
from jarvis.personal_proxy.service_ports import LanguageProvider, ProxyChatSink
from jarvis.personal_proxy.silero_probabilities import SileroSpeechProbabilities
from jarvis.personal_proxy.stage_binding import StageDependencies, bind_stages
from jarvis.personal_proxy.startup_checks import (
    load_speech_engine,
    read_topics,
    require_allowed_endpoint,
    require_check_model,
    require_usable_key,
    warm_up_check_model,
)
from jarvis.personal_proxy.startup_failure import (
    ProxyStartupError,
    StartupFailureKind,
)
from jarvis.personal_proxy.status_sink import ProxyStatusSink
from jarvis.personal_proxy.stt_engine import SpeechEngine
from jarvis.personal_proxy.stt_whisper import FasterWhisperEngine
from jarvis.ui.contract import DataLocality, ModuleHealth

LOCAL_CLIENT_CONNECT_SECONDS = 10.0
LOCAL_CLIENT_MIN_READ_SECONDS = 120.0


class ProxyTransport(Protocol):
    def publish_proxy_block(self, payload: JsonObject) -> None: ...

    def set_proxy_last_block(self, reason: JsonObject | None) -> object: ...

    def set_data_locality(self, locality: DataLocality) -> object: ...

    def set_module_health(self, health: ModuleHealth) -> object: ...


@dataclass(frozen=True)
class ProxyHost:
    """What the application gives the proxy: no module of it is imported here."""

    settings: Settings
    bus: EventBus
    audio_input: AutoPausable
    player: SpeechPlayer
    transport: ProxyTransport
    report_dropped: Callable[[], Awaitable[None]]
    journal: ProxyExchangeRecorder | None = None


def local_check_client(backend: BackendSettings) -> httpx.AsyncClient:
    """A client of its own for the local check and restoration calls: the main
    backend's client belongs to the dialog path. The read timeout covers a cold
    load of the check model."""
    return httpx.AsyncClient(
        base_url=backend.endpoint,
        trust_env=False,
        timeout=httpx.Timeout(
            LOCAL_CLIENT_CONNECT_SECONDS,
            read=max(LOCAL_CLIENT_MIN_READ_SECONDS, backend.read_timeout_seconds),
        ),
    )


@dataclass(frozen=True)
class ProxyChatChain:
    """The sink the service posts to, and what must run when it stops."""

    sink: ProxyChatSink
    on_stopped: Callable[[], Awaitable[None]] | None


def build_chat_chain(host: ProxyHost, language: LanguageProvider) -> ProxyChatChain:
    """The Status Console draws the block first, then tells it why a request was
    stopped, then the Journal keeps the exchange, each step after the one before
    it and none of the last two able to fail the request."""
    shown = ProxyStatusSink(TransportChatSink(host.transport, language), host.transport)
    if host.journal is None:
        return ProxyChatChain(shown, None)
    writer = ProxyJournalWriter(
        shown, host.journal, dry_run=host.settings.personal_proxy.dry_run
    )
    return ProxyChatChain(writer, writer.close)


@dataclass(frozen=True)
class ProxySeams:
    """Replaced only by tests."""

    environ: Mapping[str, str] = field(default_factory=lambda: os.environ)
    load_engine: Callable[[PersonalProxySettings], SpeechEngine] = FasterWhisperEngine
    load_probabilities: Callable[[], ProbabilitySource] = SileroSpeechProbabilities
    make_client: Callable[[BackendSettings], httpx.AsyncClient] = local_check_client
    make_external: Callable[[PersonalProxySettings], ExternalClient] = ExternalClient


async def prepare_personal_proxy_runtime(
    host: ProxyHost, seams: ProxySeams | None = None
) -> PersonalProxyRuntime:
    seams = seams or ProxySeams()
    proxy = host.settings.personal_proxy
    topics_text = read_topics(proxy)
    require_usable_key(proxy, seams.environ)
    require_allowed_endpoint(proxy)
    client = seams.make_client(host.settings.backend)
    runtime = None
    try:
        runtime = await _build(host, seams, client, topics_text)
        return runtime
    except ProxyStartupError:
        raise
    except Exception:
        raise ProxyStartupError(StartupFailureKind.INTERNAL) from None
    finally:
        if runtime is None:
            await client.aclose()


async def _build(
    host: ProxyHost,
    seams: ProxySeams,
    client: httpx.AsyncClient,
    topics_text: str,
) -> PersonalProxyRuntime:
    settings = host.settings
    proxy = settings.personal_proxy
    await require_check_model(client, proxy.check_model)
    engine = await load_speech_engine(proxy, seams.load_engine)
    probabilities = await asyncio.to_thread(seams.load_probabilities)
    backend = OllamaCheckBackend(settings.backend, proxy, client)

    async def warm_up() -> None:
        await warm_up_check_model(backend)

    stages = bind_stages(
        StageDependencies(
            settings=proxy,
            vad_threshold=settings.vad.threshold,
            engine=engine,
            probabilities=probabilities,
            backend=backend,
            open_stream=seams.make_external(proxy).stream,
            topics_text=topics_text,
            warm_up=warm_up,
        )
    )

    def language() -> str:
        return settings.ui.language

    chat = build_chat_chain(host, language)
    service = PersonalProxyService(
        stages=stages,
        sink=chat.sink,
        speaker=ReplayAnswerSpeaker(host.player),
        microphone=AudioMicrophoneGate(
            host.audio_input, settings.vad.resume_cooldown_seconds
        ),
        locality=host.transport,
        language=language,
        settings=proxy,
        topics_text=topics_text,
    )
    try:
        await service.warm_up()
    except Exception:
        raise ProxyStartupError(StartupFailureKind.WARM_UP) from None
    return PersonalProxyRuntime(
        service=service,
        submissions=ProxySubmissions(
            service,
            text_max_chars=settings.clipboard.max_chars,
            report_dropped=host.report_dropped,
        ),
        bus=host.bus,
        client=client,
        on_stopped=chat.on_stopped,
    )
