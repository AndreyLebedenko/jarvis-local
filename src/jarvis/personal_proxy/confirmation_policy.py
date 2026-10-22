"""Whether a checked request is put to the user before it is sent."""

from __future__ import annotations

from jarvis.personal_proxy.check_result import CheckedTranscript


def should_ask(checked: CheckedTranscript) -> bool:
    """The threshold (`[personal_proxy].doubt_min_listed`) was applied once, by
    the transcript check, into `would_ask`; it is not applied a second time."""
    return checked.would_ask
