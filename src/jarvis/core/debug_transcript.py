"""The debug transcript: exactly what went to the model and what came back.

This is the deliberate exception to the v1.6.4 content rule that both the
system log and the events panel otherwise keep. It exists because the
2026-07-25 voice investigation had to re-derive the message list, the
attached tools, and the conversation history by reading source code -
everything the engine sends was invisible after the fact.

Boundaries that survive the exception:

- **Its own sink.** A dedicated logger with `propagate = False` and its
  own file, so request content can never reach `jarvis.log`, whose
  promise to the user is that it holds none. A run without the debug
  handler installed leaves the logger below its effective level, so the
  redaction work never runs either.
- **Media is described, not embedded.** Base64 in a diagnostic file
  multiplies its size for nothing readable, so an attachment becomes its
  kind and its byte count.
- **Reasoning traces stay out.** PROJECT.md isolates `message.thinking`
  from output, TTS, history, UI, and logs. Debug lifts the content rule,
  not that one; a trace is not "what the user sent".
"""

import base64
import json
import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from jarvis.core.config import LoggingSettings

TRANSCRIPT_LOGGER_NAME = "jarvis.debug.transcript"
TRANSCRIPT_FILE_NAME = "jarvis-debug.jsonl"

# Enough decoded bytes to recognize a container from its magic number.
_SNIFF_B64_CHARS = 16

_MAGIC_NUMBERS = (
    (b"RIFF", "wav"),
    (b"\x89PNG", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"ID3", "mp3"),
    (b"\xff\xfb", "mp3"),
    (b"OggS", "ogg"),
)

logger = logging.getLogger(TRANSCRIPT_LOGGER_NAME)


def disable_debug_transcript() -> None:
    """Stop recording, closing whatever sink was open.

    This logger is module state, so "debug is off" has to be an action
    rather than an absence: without it, a second run() in the same process
    would inherit the previous run's handler and keep writing request
    content with nothing announcing it (review finding, 2026-07-26)."""
    for handler in logger.handlers:
        handler.close()
    logger.handlers = []
    logger.setLevel(logging.NOTSET)


def configure_debug_transcript(settings: LoggingSettings) -> Path | None:
    """Install the transcript sink. Returns its path, or None if it could
    not be opened - a debug run must fail loudly rather than run silently
    without the recording it was started for, but that decision belongs to
    the caller, which is why this reports instead of raising.

    The old sink is closed first, so a failure here can never leave the
    previous run's file being written to behind an announcement that says
    nothing is being recorded."""
    disable_debug_transcript()
    directory = Path(settings.directory)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            directory / TRANSCRIPT_FILE_NAME,
            maxBytes=settings.max_bytes,
            backupCount=settings.backup_count,
            encoding="utf-8",
        )
    except OSError:
        return None
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return directory / TRANSCRIPT_FILE_NAME


def recording() -> bool:
    """A sink, not just a level: the level alone is inherited from the
    root logger, so a process that turned root to DEBUG would otherwise
    make this claim recording while nothing has anywhere to be written."""
    return bool(logger.handlers) and logger.isEnabledFor(logging.DEBUG)


def media_descriptor(encoded: str) -> dict[str, Any]:
    """What an attachment was, without the attachment."""
    prefix = base64.b64decode(encoded[:_SNIFF_B64_CHARS], validate=False)
    kind = next(
        (name for magic, name in _MAGIC_NUMBERS if prefix.startswith(magic)), "unknown"
    )
    # The exact decoded length without decoding the whole string: base64
    # is 4 characters per 3 bytes, minus the padding.
    padding = encoded[-2:].count("=")
    return {"kind": kind, "bytes": len(encoded) // 4 * 3 - padding}


def write_record(
    kind: str, fields: dict[str, Any], *, started: float | None = None
) -> None:
    """Writes one JSONL line, or does nothing if no sink is installed.

    Every record carries a "kind" discriminant and a timestamp, so one
    file can hold exchanges and utterance metrics - interleaved, since
    each is written independently - without ambiguity about which is
    which. Checked here even though callers already gate on recording()
    before doing the work to produce fields: debug could in principle be
    turned off between that gate and this call, and a line must never be
    written after the sink it would go to has been closed."""
    if not recording():
        return
    timestamp = time.time() if started is None else started
    record = {
        "kind": kind,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(timestamp)),
        **fields,
    }
    logger.debug(json.dumps(record, ensure_ascii=False))


def redacted_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    redacted = []
    for message in messages:
        entry = {key: value for key, value in message.items() if key != "images"}
        images = message.get("images")
        if images:
            entry["media"] = [media_descriptor(image) for image in images]
        redacted.append(entry)
    return redacted


class Exchange:
    """One request/response pair, written when the response ends.

    Written at the end rather than in two halves because a record split
    across two lines is a record that can interleave with another turn's.
    A request that never completes is still written - see write() - since
    a hung or failed call is exactly what a transcript is wanted for."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._started = time.time()
        self._request = {
            "model": payload.get("model"),
            "think": payload.get("think"),
            "options": payload.get("options"),
            "tools": payload.get("tools"),
            "messages": redacted_messages(payload.get("messages", [])),
        }
        self._content: list[str] = []
        self._tool_calls: list[Any] = []
        self._done: dict[str, Any] = {}

    def observe(self, chunk: dict[str, Any]) -> None:
        message = chunk.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if content:
                self._content.append(content)
            calls = message.get("tool_calls")
            if calls:
                self._tool_calls.extend(calls)
        if chunk.get("done"):
            self._done = {
                "done_reason": chunk.get("done_reason"),
                "eval_count": chunk.get("eval_count"),
                "prompt_eval_count": chunk.get("prompt_eval_count"),
            }

    def write(self) -> None:
        write_record(
            "exchange",
            {
                "elapsed_seconds": round(time.time() - self._started, 3),
                "request": self._request,
                "response": {
                    "content": "".join(self._content),
                    "tool_calls": self._tool_calls,
                    "completed": bool(self._done),
                    **self._done,
                },
            },
            started=self._started,
        )


def begin_exchange(payload: dict[str, Any]) -> Exchange | None:
    """None when nothing is recording, so callers pay one level check."""
    return Exchange(payload) if recording() else None
