"""Health signal for the long-term memory files (self.md, memory.md).

Published by the code that actually touches the files (the remember tool and
the memory panel endpoints); consumed by ModuleHealthTracker for the Memory
chip. The repository itself stays free of the bus.
"""

from dataclasses import dataclass
from enum import Enum

from jarvis.memory.files import MemoryFileId


class MemoryFileOutcome(Enum):
    READ_OK = "read_ok"
    WRITE_OK = "write_ok"
    WRITE_REFUSED_FULL = "write_refused_full"
    IO_FAILED = "io_failed"


@dataclass(frozen=True)
class MemoryFileOutcomeObserved:
    file_id: MemoryFileId
    outcome: MemoryFileOutcome
