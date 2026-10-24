"""The sentence buffer of the restoration stage: the speech `SentenceBuffer`
plus two bounds, so that no input can make one pending sentence grow without
limit or make the buffer's rescans quadratic."""

from __future__ import annotations

from jarvis.audio.tts import SentenceBuffer

MAX_PENDING_CHARS = 4000
_FEED_SLICE_CHARS = 1024
MAX_PLACEHOLDER_PREFIX_CHARS = 32
_SPACES = " \t"


class BoundedSentenceBuffer(SentenceBuffer):
    """A newline ends the pending text (list items carry no punctuation); more
    than MAX_PENDING_CHARS pending without a boundary is emitted at the last
    space, or, with no space, up to a trailing unterminated "<..." that could
    still become a placeholder, or whole. A placeholder is never cut."""

    def feed(self, text: str) -> list[str]:
        *lines, tail = text.split("\n")
        sentences: list[str] = []
        for line in lines:
            sentences += self._feed_bounded(line)
            self._flush_into(sentences)
        sentences += self._feed_bounded(tail)
        return sentences

    def _feed_bounded(self, text: str) -> list[str]:
        sentences: list[str] = []
        for start in range(0, len(text), _FEED_SLICE_CHARS):
            sentences += super().feed(text[start : start + _FEED_SLICE_CHARS])
            self._cut_oversized_into(sentences)
        return sentences

    def _flush_into(self, sentences: list[str]) -> None:
        pending = self.flush()
        if pending is not None:
            sentences.append(pending)

    def _cut_oversized_into(self, sentences: list[str]) -> None:
        while len(self._buffer) > MAX_PENDING_CHARS:
            cut = self._cut_position()
            self._scanned_to = 0
            head, self._buffer = self._buffer[:cut], self._buffer[cut:]
            if head.strip():
                sentences.append(head.strip())

    def _cut_position(self) -> int:
        last_space = max(self._buffer.rfind(space) for space in _SPACES)
        if last_space > 0:
            return last_space
        prefix = self._buffer.rfind("<")
        if (
            prefix > 0
            and ">" not in self._buffer[prefix:]
            and len(self._buffer) - prefix <= MAX_PLACEHOLDER_PREFIX_CHARS
        ):
            return prefix
        return len(self._buffer)
