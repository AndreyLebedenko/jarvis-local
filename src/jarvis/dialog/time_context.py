"""Pure current-turn time context formatting.

format_time_context() renders the local weekday and an ISO 8601 timestamp
with an explicit numeric UTC offset, for injection as an extra system
message on every turn (see PROJECT.md's v1.3.2 decision). No project-module
dependencies, matching language_segments.py/speech_markup.py's shape.

Deliberately avoids strftime("%A") and "%Z": both depend on the OS
locale/timezone-abbreviation table, which is not reliably available on
Windows. The weekday name comes from a hardcoded Russian table indexed by
datetime.weekday() instead.

The numeric offset (not a bare local time) matters across a DST fall-back
hour, where the local wall clock genuinely repeats - e.g. 01:30 BST is
chronologically before 01:15 GMT even though "01:30" > "01:15" as bare
numbers. An explicit offset keeps the two instants distinguishable.
"""

from datetime import datetime

_WEEKDAYS_RU = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)


def format_time_context(epoch: float) -> str:
    dt = datetime.fromtimestamp(epoch).astimezone()
    weekday = _WEEKDAYS_RU[dt.weekday()]
    return f"{weekday}, {dt.isoformat(timespec='minutes')}"
