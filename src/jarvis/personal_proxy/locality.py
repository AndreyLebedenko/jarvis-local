"""The seam through which a turn answered externally reports
`DataLocality.EXTERNAL`."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Protocol

from jarvis.ui.contract import DataLocality


class LocalityReporter(Protocol):
    def set_data_locality(self, locality: DataLocality) -> object: ...


@contextmanager
def external_locality(reporter: LocalityReporter) -> Iterator[None]:
    reporter.set_data_locality(DataLocality.EXTERNAL)
    try:
        yield
    finally:
        reporter.set_data_locality(DataLocality.LOCAL)
