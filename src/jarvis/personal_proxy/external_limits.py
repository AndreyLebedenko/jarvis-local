"""Size caps on an external answer, so a hostile or broken endpoint cannot
exhaust memory."""

MAX_LINE_BYTES = 64 * 1024
MAX_ANSWER_CHARS = 200_000
