"""Why the proxy did not start, as an enum. Nothing about the cause beyond its
kind leaves the check that found it: no path, no exception text."""

from __future__ import annotations

from enum import StrEnum


class StartupFailureKind(StrEnum):
    TOPICS_FILE = "topics_file"
    PUBLIC_NAMES_FILE = "public_names_file"
    API_KEY = "api_key"
    ENDPOINT = "endpoint"
    SPEECH_DEPENDENCY = "speech_dependency"
    SPEECH_MODEL = "speech_model"
    SPEECH_DEVICE = "speech_device"
    OLLAMA = "ollama"
    CHECK_MODEL = "check_model"
    WARM_UP = "warm_up"
    INTERNAL = "internal"

    @property
    def ui_text_key(self) -> str:
        return f"personal_proxy_not_started_{self.value}"


class ProxyStartupError(Exception):
    def __init__(self, kind: StartupFailureKind) -> None:
        super().__init__(f"the personal proxy was not started: {kind.value}")
        self.kind = kind
