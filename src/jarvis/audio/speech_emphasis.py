"""Asterisk emphasis markers in one speech unit: which to keep, which to drop."""

import re

_MARKER = re.compile(r"(?<![\w*])\*(?=[^\s*]*[^\W_])([^\s*]+)\*(?![\w*])")
_SENTENCE_PUNCTUATION = "?!.…"
_CLOSERS_AND_SPACE = " \t\r\n\"'»“”’)]}"
_MAX_MARKERS_IN_QUESTION = 2
_MAX_MARKERS_IN_STATEMENT = 1


def normalize_emphasis(unit: str) -> str:
    """Keep the markers a Silero v5 sentence can use and drop every other `*`."""
    markers = list(_MARKER.finditer(unit))
    kept = _kept_marker_indexes(len(markers), _is_question(unit))
    pieces: list[str] = []
    cursor = 0
    for index, marker in enumerate(markers):
        pieces.append(strip_emphasis(unit[cursor : marker.start()]))
        pieces.append(marker.group() if index in kept else marker.group(1))
        cursor = marker.end()
    pieces.append(strip_emphasis(unit[cursor:]))
    return "".join(pieces)


def strip_emphasis(text: str) -> str:
    return text.replace("*", "")


def _is_question(unit: str) -> bool:
    without_closers = strip_emphasis(unit).rstrip(_CLOSERS_AND_SPACE)
    final_run = without_closers[len(without_closers.rstrip(_SENTENCE_PUNCTUATION)) :]
    return "?" in final_run


def _kept_marker_indexes(count: int, is_question: bool) -> set[int]:
    if not is_question:
        return set(range(min(count, _MAX_MARKERS_IN_STATEMENT)))
    if count <= _MAX_MARKERS_IN_QUESTION:
        return set(range(count))
    return {0, count - 1}
