"""Where the speech and typed-text handlers of the proxy leave their input.

The event bus awaits every handler inline, so a handler that did the work would
stop the microphone loop. A handler only calls `submit`, which enqueues and
returns at once; the service's worker takes items with `next_item`. The inbox
knows nothing about the confirmation exchange."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


class InboxFullError(Exception):
    """The inbox is at capacity; the submitted item was dropped."""

    def __init__(self) -> None:
        super().__init__("the proxy inbox is full; the item was dropped")


class WrongLoopError(Exception):
    """`submit` was called from outside the event loop that runs the worker."""

    def __init__(self) -> None:
        super().__init__("the proxy inbox must be used on the worker's event loop")


@dataclass(frozen=True)
class TypedText:
    text: str = field(repr=False)


@dataclass(frozen=True)
class Utterance:
    wav: bytes = field(repr=False)


InboxItem = TypedText | Utterance


def _running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


class ProxyInbox:
    """Not thread-safe. `submit` must be called on the event loop that runs the
    worker's `next_item`; a caller on another thread (the Status Console
    transport, a hotkey) marshals with `asyncio.run_coroutine_threadsafe` or
    `loop.call_soon_threadsafe`. Once the worker has started waiting, a `submit`
    from anywhere else raises `WrongLoopError` instead of corrupting the queue."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self._queue: asyncio.Queue[InboxItem] = asyncio.Queue(maxsize=capacity)
        self._worker_loop: asyncio.AbstractEventLoop | None = None

    def submit(self, item: InboxItem) -> None:
        if not isinstance(item, TypedText | Utterance):
            raise TypeError("the inbox takes TypedText or Utterance items")
        if self._worker_loop is not None and _running_loop() is not self._worker_loop:
            raise WrongLoopError
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            raise InboxFullError from None

    async def next_item(self) -> InboxItem:
        self._worker_loop = asyncio.get_running_loop()
        return await self._queue.get()
