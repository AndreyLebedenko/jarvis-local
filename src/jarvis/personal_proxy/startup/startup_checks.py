"""The checks that must pass before the proxy starts anything. Each maps what
it finds to a `StartupFailureKind` and drops the cause (`from None`): the
causes carry paths and file text."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Protocol

import httpx

from jarvis.core.config import GenerationOptions, PersonalProxySettings
from jarvis.personal_proxy.check.check_backend import ChatRequest, CheckBackend
from jarvis.personal_proxy.external.external_endpoint import require_secure_endpoint
from jarvis.personal_proxy.external.external_error import ExternalClientError
from jarvis.personal_proxy.external.external_key import key_problem
from jarvis.personal_proxy.gate.topics_file import TopicsFileError, load_topics
from jarvis.personal_proxy.startup.startup_failure import (
    ProxyStartupError,
    StartupFailureKind,
)
from jarvis.personal_proxy.stt.stt_engine import (
    MissingSpeechDependencyError,
    SpeechDeviceError,
    SpeechEngine,
    SpeechEngineLoadError,
    SpeechModelUnavailableError,
)

WARM_UP_PROMPT = "Reply with the single word: ok"
_DEFAULT_TAG = "latest"

_ENGINE_FAILURES: tuple[tuple[type[SpeechEngineLoadError], StartupFailureKind], ...] = (
    (MissingSpeechDependencyError, StartupFailureKind.SPEECH_DEPENDENCY),
    (SpeechModelUnavailableError, StartupFailureKind.SPEECH_MODEL),
    (SpeechDeviceError, StartupFailureKind.SPEECH_DEVICE),
)


class OllamaTags(Protocol):
    async def get(self, url: str) -> httpx.Response: ...


def read_topics(settings: PersonalProxySettings) -> str:
    try:
        return load_topics(settings)
    except TopicsFileError:
        raise ProxyStartupError(StartupFailureKind.TOPICS_FILE) from None


def require_usable_key(
    settings: PersonalProxySettings, environ: Mapping[str, str]
) -> None:
    if key_problem(environ.get(settings.api_key_env, "")) is not None:
        raise ProxyStartupError(StartupFailureKind.API_KEY)


def require_allowed_endpoint(settings: PersonalProxySettings) -> None:
    try:
        require_secure_endpoint(settings.endpoint)
    except ExternalClientError:
        raise ProxyStartupError(StartupFailureKind.ENDPOINT) from None


async def load_speech_engine(
    settings: PersonalProxySettings,
    loader: Callable[[PersonalProxySettings], SpeechEngine],
) -> SpeechEngine:
    try:
        return await asyncio.to_thread(loader, settings)
    except SpeechEngineLoadError as error:
        for failure_type, kind in _ENGINE_FAILURES:
            if isinstance(error, failure_type):
                raise ProxyStartupError(kind) from None
        raise ProxyStartupError(StartupFailureKind.SPEECH_DEVICE) from None


def _with_tag(name: str) -> str:
    return name if ":" in name else f"{name}:{_DEFAULT_TAG}"


async def require_check_model(client: OllamaTags, model: str) -> None:
    try:
        response = await client.get("/api/tags")
        response.raise_for_status()
        listed = response.json().get("models", [])
    except (httpx.HTTPError, ValueError, AttributeError):
        raise ProxyStartupError(StartupFailureKind.OLLAMA) from None
    names = {
        _with_tag(name)
        for entry in listed
        if isinstance(entry, dict)
        and isinstance(name := entry.get("model") or entry.get("name"), str)
    }
    if _with_tag(model) not in names:
        raise ProxyStartupError(StartupFailureKind.CHECK_MODEL)


async def warm_up_check_model(backend: CheckBackend) -> None:
    """Loads the check model at its own context size, so the first restoration
    does not meet a cold load. The fixed prompt holds nothing personal."""
    await backend.complete(
        ChatRequest(
            prompt=WARM_UP_PROMPT,
            audio_base64="",
            options=GenerationOptions(temperature=0.0, seed=1),
        )
    )
