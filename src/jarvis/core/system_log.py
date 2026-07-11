"""Single source of truth for UI-visible system events (task-ui-03).

Resolves this task's Stop Condition ("if logs and bus events diverge as
competing sources of truth, stop and define which layer owns UI-visible
events before implementation"): publish_system_event() is the one call
that decides a user-facing system event happened. It always does both of
its jobs together - logs via the given logger AND publishes
ui_contract.py's SystemEvent on the bus - so the console/file log and the
Status Console's events panel can never disagree about whether something
was logged for a given occurrence.

log_message and ui_message are two separate strings, not the same string
reused: this project's existing console log lines are English/technical
(see main.py's pre-existing "Thinking mode enabled"/"Microphone asleep"
lines, and CLAUDE.md's "English for code, identifiers... and technical
documentation"), while the Status Console is a Russian-language, end-user
product surface (matching PROJECT.md's SYSTEM_PROMPT and
.planning/UI/mock-ups). Requiring one literal string for both would force
a language choice that fits neither audience; requiring both at the same
call site instead means the two can never drift apart about *whether* or
*for what occurrence* an event fired, only how it reads.

A caller that also wants a full diagnostic stack trace (logger.exception())
may still do that separately, before or after calling this - that is
additional diagnostic detail for developers, not a second copy of the same
user-facing fact.
"""

import logging
import time

from jarvis.core.bus import EventBus
from jarvis.ui.contract import EventLevel, SystemEvent

_PYTHON_LOG_LEVEL = {
    EventLevel.INFO: logging.INFO,
    EventLevel.ACTIVE: logging.INFO,
    EventLevel.WARN: logging.WARNING,
    EventLevel.ERROR: logging.ERROR,
}


async def publish_system_event(
    bus: EventBus,
    logger: logging.Logger,
    source: str,
    level: EventLevel,
    log_message: str,
    ui_message: str,
    correlation_id: str | None = None,
) -> SystemEvent:
    event = SystemEvent(
        timestamp=time.time(),
        source=source,
        level=level,
        message=ui_message,
        correlation_id=correlation_id,
    )
    logger.log(_PYTHON_LOG_LEVEL[level], "[%s] %s", source, log_message)
    await bus.publish(SystemEvent, event)
    return event
