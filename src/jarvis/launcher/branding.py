"""Runs the icon generator for the launcher's Settings button off the UI thread."""

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jarvis.core.brand_icon import BrandIconError
from jarvis.core.brand_render import GenerationOutcome, regenerate_home_icons
from jarvis.core.config import ConfigError

Generator = Callable[[Path], GenerationOutcome]


@dataclass(frozen=True)
class RegenerationResult:
    message: str
    error: Exception | None = None


def regenerate(
    home: Path, generate: Generator = regenerate_home_icons
) -> RegenerationResult:
    """Never raises: an explicit click must end in a message or an error
    dialog, whatever the generator does."""
    try:
        return RegenerationResult(generate(home).message)
    except (ConfigError, BrandIconError, OSError) as error:
        return RegenerationResult(str(error), error)
    except Exception as error:
        return RegenerationResult(
            f"Icon generation failed: {error!r}",
            RuntimeError(f"Icon generation failed: {error!r}"),
        )


class RegenerationJob:
    """One generator run on a worker thread; the Tk thread polls for the result."""

    def __init__(self, home: Path, generate: Generator = regenerate_home_icons) -> None:
        self._results: queue.Queue[RegenerationResult] = queue.Queue(maxsize=1)
        self._thread = threading.Thread(
            target=lambda: self._results.put(regenerate(home, generate)),
            name="jarvis-brand-icons",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def poll(self) -> RegenerationResult | None:
        try:
            return self._results.get_nowait()
        except queue.Empty:
            return None


WORKING_STATUS = "Working..."
FAILED_STATUS = "Icon generation failed"


class IconRegeneration:
    """The state behind the Settings button: one job at a time for the saved
    home; on success the launcher identity is reloaded; on failure the error is
    handed to the caller's dialog."""

    def __init__(
        self,
        home: Callable[[], Path],
        on_success: Callable[[], None],
        show_error: Callable[[Exception], None],
        start_job: Callable[[Path], RegenerationJob] = RegenerationJob,
    ) -> None:
        self._home = home
        self._on_success = on_success
        self._show_error = show_error
        self._start_job = start_job
        self._job: RegenerationJob | None = None
        self.status = ""

    @property
    def working(self) -> bool:
        return self._job is not None

    def click(self) -> None:
        if self._job is not None:
            return
        job = self._start_job(self._home())
        try:
            job.start()
        except (RuntimeError, OSError) as error:
            self.status = FAILED_STATUS
            self._show_error(error)
            return
        self._job = job
        self.status = WORKING_STATUS

    def poll(self) -> None:
        if self._job is None:
            return
        result = self._job.poll()
        if result is None:
            return
        self._job = None
        if result.error is None:
            self.status = result.message
            self._on_success()
        else:
            self.status = FAILED_STATUS
            self._show_error(result.error)

    def clear(self) -> None:
        if self._job is None:
            self.status = ""
