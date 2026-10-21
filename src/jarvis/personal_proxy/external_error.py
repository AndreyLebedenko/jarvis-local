"""The one error type of the external client. It never carries content."""

from __future__ import annotations

from enum import Enum


class ExternalErrorKind(Enum):
    KEY_MISSING = "key_missing"
    KEY_INVALID = "key_invalid"
    BAD_REQUEST = "bad_request"
    TOO_LARGE = "too_large"
    UNEXPECTED = "unexpected"
    INSECURE_ENDPOINT = "insecure_endpoint"
    CONNECT_FAILED = "connect_failed"
    TIMEOUT = "timeout"
    HTTP_STATUS = "http_status"
    BAD_STREAM = "bad_stream"
    TRUNCATED = "truncated"
    EMPTY_ANSWER = "empty_answer"


_MESSAGES = {
    ExternalErrorKind.KEY_MISSING: "the external API key is not set",
    ExternalErrorKind.KEY_INVALID: (
        "the external API key holds characters that cannot be sent in a header"
    ),
    ExternalErrorKind.BAD_REQUEST: "the external request could not be encoded",
    ExternalErrorKind.TOO_LARGE: "the external answer exceeded its size limit",
    ExternalErrorKind.UNEXPECTED: "the external call failed unexpectedly",
    ExternalErrorKind.INSECURE_ENDPOINT: (
        "the external endpoint must be https or loopback http"
    ),
    ExternalErrorKind.CONNECT_FAILED: "could not reach the external endpoint",
    ExternalErrorKind.TIMEOUT: "the external call exceeded its time limit",
    ExternalErrorKind.HTTP_STATUS: (
        "the external endpoint answered with an error status"
    ),
    ExternalErrorKind.BAD_STREAM: "the external answer stream was malformed",
    ExternalErrorKind.TRUNCATED: (
        "the external answer was cut off at the length limit; "
        "the text received is not a complete answer"
    ),
    ExternalErrorKind.EMPTY_ANSWER: "the external answer held no text",
}


class ExternalClientError(Exception):
    def __init__(self, kind: ExternalErrorKind, status: int | None = None) -> None:
        super().__init__(_MESSAGES[kind])
        self.kind = kind
        self.status = status
