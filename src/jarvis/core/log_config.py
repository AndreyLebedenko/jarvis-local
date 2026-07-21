"""Installs Jarvis's durable system log.

story-v1.6.4: `publish_system_event()` has always carried two texts - a
detailed English `log_message` for engineers and a `ui_message` for the
console's events panel. Only the second one had somewhere to go: logging
was configured by a bare `basicConfig()` with no file handler, so started
outside a terminal the whole diagnostic stream was lost. This module is
the missing half.

Boundaries:
- Local file sink only. No network handler, no log shipping, no
  telemetry. Nothing here opens a socket, so the runtime locality
  contract is untouched.
- Content rule (story-v1.6.4): kinds, counts, durations, sizes - never
  payload content. This module decides where records go, never what any
  call site chooses to log.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from jarvis.core.config import LoggingSettings

LOG_FILE_NAME = "jarvis.log"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(
    settings: LoggingSettings,
    root: logging.Logger | None = None,
) -> Path | None:
    """Install stream and rotating-file handlers; return the log directory.

    Returns None when the directory could not be opened. Jarvis must not
    fail to start because it could not open a log file, so an unusable
    location degrades to stream-only logging with a warning rather than
    raising.
    """
    root = root if root is not None else logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter(LOG_FORMAT)

    if not _has_handler(root, logging.StreamHandler, exclude=RotatingFileHandler):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    if _has_handler(root, RotatingFileHandler):
        return _existing_directory(root)

    directory = Path(settings.directory)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            directory / LOG_FILE_NAME,
            maxBytes=settings.max_bytes,
            backupCount=settings.backup_count,
            encoding="utf-8",
        )
    except OSError as error:
        root.warning(
            "Logging to %s is unavailable, continuing without a log file: %s",
            directory,
            error,
        )
        return None

    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    return directory


def _has_handler(
    root: logging.Logger,
    kind: type[logging.Handler],
    exclude: type[logging.Handler] | None = None,
) -> bool:
    return any(
        isinstance(handler, kind)
        and not (exclude is not None and isinstance(handler, exclude))
        for handler in root.handlers
    )


def _existing_directory(root: logging.Logger) -> Path:
    handler = next(h for h in root.handlers if isinstance(h, RotatingFileHandler))
    return Path(handler.baseFilename).parent
