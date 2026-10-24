"""The restoration fallback: the base-form original in place of a placeholder."""

from __future__ import annotations

from collections.abc import Mapping

from jarvis.personal_proxy.sanitize.placeholders import ANY_PLACEHOLDER


def substitute(sentence: str, mapping: Mapping[str, str]) -> str:
    """One pass, so an original is never searched for placeholders again."""
    return ANY_PLACEHOLDER.sub(
        lambda found: mapping.get(found.group(), found.group()), sentence
    )
