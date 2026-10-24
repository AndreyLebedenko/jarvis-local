"""What the gate knows besides the payload: the values the sanitizer replaced
and the local-only topics text. Both are sensitive, so neither is shown by
`repr`. The mapping is copied at construction, so changing the caller's dict
later cannot weaken the gate."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class GateContext:
    mapping: Mapping[str, str] = field(default_factory=dict, repr=False)
    topics_text: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.mapping, Mapping):
            raise TypeError("mapping must be a Mapping")
        object.__setattr__(self, "mapping", MappingProxyType(dict(self.mapping)))
