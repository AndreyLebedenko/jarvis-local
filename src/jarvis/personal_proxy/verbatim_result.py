"""What stands in for the sanitize stage when a typed request is forced: the
verbatim text, nothing replaced, so the mapping is empty."""

from __future__ import annotations

from jarvis.personal_proxy.sanitize_result import SanitizeResult, SanitizeVerdict


def verbatim_result(text: str) -> SanitizeResult:
    return SanitizeResult(SanitizeVerdict.SEND, "", text, {})
