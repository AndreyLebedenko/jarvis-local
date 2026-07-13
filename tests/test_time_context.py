"""Unit tests for jarvis.dialog.time_context.format_time_context().

The DST fall-back test forces the process timezone to Europe/London via
time.tzset(), which is POSIX-only (unavailable on Windows) - it is skipped
on platforms without it. The ordinary-case test makes no timezone
assumption, so it is portable everywhere including the project's Windows 11
dev machine.
"""

import os
import time
from datetime import UTC, datetime

import pytest

from jarvis.dialog.time_context import _WEEKDAYS_RU, format_time_context

has_tzset = hasattr(time, "tzset")


def test_format_returns_weekday_and_iso_with_minute_precision_offset():
    epoch = datetime(2026, 7, 13, 12, 0, tzinfo=UTC).timestamp()

    result = format_time_context(epoch)

    weekday, _, rest = result.partition(", ")
    assert weekday in _WEEKDAYS_RU
    dt = datetime.fromisoformat(rest)
    assert dt.utcoffset() is not None
    assert rest == dt.isoformat(timespec="minutes")


@pytest.mark.skipif(not has_tzset, reason="time.tzset() is POSIX-only")
def test_dst_fall_back_hour_keeps_both_instants_individually_well_formed():
    """UK 2026-10-25: clocks go back from 02:00 BST to 01:00 GMT, so local
    01:30 occurs twice. Ordering is not "fixed" by this format - the point
    is that each rendering stays individually well-formed with a distinct,
    explicit numeric offset, so the two instants remain distinguishable."""
    original_tz = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/London"
    time.tzset()
    try:
        before_fallback = datetime(2026, 10, 25, 0, 30, tzinfo=UTC).timestamp()
        after_fallback = datetime(2026, 10, 25, 1, 30, tzinfo=UTC).timestamp()

        result_before = format_time_context(before_fallback)
        result_after = format_time_context(after_fallback)

        weekday_before, _, rest_before = result_before.partition(", ")
        weekday_after, _, rest_after = result_after.partition(", ")

        assert weekday_before == weekday_after  # same calendar day
        assert rest_before.startswith("2026-10-25T01:30")
        assert rest_after.startswith("2026-10-25T01:30")
        assert rest_before.endswith("+01:00")  # BST, before the fall-back
        assert rest_after.endswith("+00:00")  # GMT, after the fall-back
        assert rest_before != rest_after
    finally:
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz
        time.tzset()
