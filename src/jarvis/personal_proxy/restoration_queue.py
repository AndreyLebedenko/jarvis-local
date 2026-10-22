"""An in-order queue of sentences between the reader of the answer and the
restoration, bounded by the characters waiting in it."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class QueueEnd:
    """The in-order end of the input; `error` is what ended it, if anything."""

    error: BaseException | None


class SentenceQueue:
    def __init__(self, max_chars: int) -> None:
        self._max_chars = max_chars
        self._items: deque[str | QueueEnd] = deque()
        self._chars = 0
        self._changed = asyncio.Condition()

    async def put(self, sentence: str) -> None:
        """Waits while the sentence would take the queued characters over the
        limit, so that a fast reader cannot fill memory; a sentence is always
        accepted into an empty queue, however large."""
        async with self._changed:
            await self._changed.wait_for(
                lambda: not self._items
                or self._chars + len(sentence) <= self._max_chars
            )
            self._items.append(sentence)
            self._chars += len(sentence)
            self._changed.notify_all()

    async def finish(self, error: BaseException | None) -> None:
        async with self._changed:
            self._items.append(QueueEnd(error))
            self._changed.notify_all()

    async def get(self) -> str | QueueEnd:
        async with self._changed:
            await self._changed.wait_for(lambda: bool(self._items))
            item = self._items.popleft()
            if isinstance(item, str):
                self._chars -= len(item)
            self._changed.notify_all()
            return item
