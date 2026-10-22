"""Typed text is the user's own words: it needs no speech stage and no check."""

from __future__ import annotations

from jarvis.personal_proxy.check_result import CheckedTranscript, CheckSource


def typed_checked_transcript(text: str) -> CheckedTranscript:
    return CheckedTranscript(
        text=text, doubts=(), source=CheckSource.TYPED, would_ask=False
    )
