"""Health signal for the semantic half of history search.

Published by HistoryProjectionLifecycle from the semantic projection's own
state; consumed by ModuleHealthTracker for the Memory chip. Semantic search
disabled in configuration is the user's choice and reports as available.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SemanticSearchHealthObserved:
    available: bool
