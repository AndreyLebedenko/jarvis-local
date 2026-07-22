import logging
from logging.handlers import RotatingFileHandler

from jarvis.core.config import LoggingSettings
from jarvis.core.log_config import configure_logging


def _fresh_root() -> logging.Logger:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    return root


def test_configure_logging_adds_a_rotating_file_handler(tmp_path):
    root = _fresh_root()

    directory = configure_logging(
        LoggingSettings(directory=str(tmp_path / "logs")), root=root
    )

    file_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) == 1
    assert directory == tmp_path / "logs"
    assert directory.is_dir()


def test_configure_logging_keeps_stream_output_alongside_the_file(tmp_path):
    """Running from a terminal must behave exactly as before: the file is
    an addition, not a replacement."""
    root = _fresh_root()

    configure_logging(LoggingSettings(directory=str(tmp_path / "logs")), root=root)

    stream_handlers = [
        h
        for h in root.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, RotatingFileHandler)
    ]
    assert stream_handlers


def test_configure_logging_applies_the_configured_rotation_bounds(tmp_path):
    root = _fresh_root()

    configure_logging(
        LoggingSettings(
            directory=str(tmp_path / "logs"), max_bytes=4096, backup_count=3
        ),
        root=root,
    )

    handler = next(h for h in root.handlers if isinstance(h, RotatingFileHandler))
    assert handler.maxBytes == 4096
    assert handler.backupCount == 3


def test_configure_logging_writes_records_to_the_file(tmp_path):
    root = _fresh_root()

    directory = configure_logging(
        LoggingSettings(directory=str(tmp_path / "logs")), root=root
    )
    logging.getLogger("jarvis.test").info("hello from the engine")
    for handler in root.handlers:
        handler.flush()

    written = next(directory.iterdir()).read_text(encoding="utf-8")
    assert "hello from the engine" in written
    assert "INFO" in written
    assert "jarvis.test" in written


def test_configure_logging_degrades_to_stream_only_when_the_path_is_unusable(tmp_path):
    """Jarvis must not fail to start because it could not open a log file.
    A file where the log directory should be is the cheapest way to make
    directory creation fail without depending on platform permissions."""
    blocker = tmp_path / "logs"
    blocker.write_text("not a directory", encoding="utf-8")
    root = _fresh_root()

    directory = configure_logging(LoggingSettings(directory=str(blocker)), root=root)

    assert directory is None
    assert not [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    assert [h for h in root.handlers if isinstance(h, logging.StreamHandler)]


def test_configure_logging_is_idempotent_across_repeated_calls(tmp_path):
    """run() may be entered more than once in a test session, and stacking
    handlers would duplicate every line in the file."""
    root = _fresh_root()
    settings = LoggingSettings(directory=str(tmp_path / "logs"))

    configure_logging(settings, root=root)
    configure_logging(settings, root=root)

    assert len([h for h in root.handlers if isinstance(h, RotatingFileHandler)]) == 1
