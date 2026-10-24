"""Placeholder patterns. `PLACEHOLDER` is the strict one of the sanitize
parser (`<TYPE_N>`, a type of the sanitize prompt). `ANY_PLACEHOLDER` is the
broad shape the outbound gate looks for; text of that shape that the mapping
does not know is unresolved."""

from __future__ import annotations

import re
from collections.abc import Mapping

from jarvis.personal_proxy.sanitize.sanitize_prompts import PLACEHOLDER_TYPES

PLACEHOLDER = re.compile(rf"<(?:{'|'.join(PLACEHOLDER_TYPES)})_[1-9][0-9]*>")
ANY_PLACEHOLDER = re.compile(r"<[A-Z_]+_\d+>")


def known_entries(sentence: str, mapping: Mapping[str, str]) -> dict[str, str]:
    """The mapping entries whose placeholder occurs in the sentence, in order
    of first use."""
    found = dict.fromkeys(ANY_PLACEHOLDER.findall(sentence))
    return {key: mapping[key] for key in found if key in mapping}


def has_unresolved(sentence: str, mapping: Mapping[str, str]) -> bool:
    return any(key not in mapping for key in ANY_PLACEHOLDER.findall(sentence))
