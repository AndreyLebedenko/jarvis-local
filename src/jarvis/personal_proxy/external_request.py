"""The request of an external chat call: a closed set of body and headers."""

from __future__ import annotations

import json

import httpx

from jarvis.core.config import PersonalProxySettings
from jarvis.personal_proxy.external_error import (
    ExternalClientError,
    ExternalErrorKind,
)
from jarvis.personal_proxy.payload import OutboundPayload


def build_request_body(
    settings: PersonalProxySettings, payload: OutboundPayload
) -> dict[str, object]:
    return {
        "model": settings.model,
        "messages": payload.to_chat_messages(),
        "stream": True,
    }


def build_request_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept-Encoding": "identity",
    }


def _try_encode(
    settings: PersonalProxySettings, payload: OutboundPayload
) -> bytes | None:
    try:
        text = json.dumps(build_request_body(settings, payload), ensure_ascii=False)
        return text.encode("utf-8")
    except ValueError:
        return None


def encode_request_body(
    settings: PersonalProxySettings, payload: OutboundPayload
) -> bytes:
    """The encoding is attempted in a helper so that no frame of the raised
    error holds the text."""
    encoded = _try_encode(settings, payload)
    if encoded is None:
        raise ExternalClientError(ExternalErrorKind.BAD_REQUEST)
    return encoded


def build_http_request(endpoint: str, api_key: str, body: bytes) -> httpx.Request:
    return httpx.Request(
        "POST", endpoint, headers=build_request_headers(api_key), content=body
    )
