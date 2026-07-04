"""Trivial asyncio pub/sub event bus.

Per PROJECT.md's Architecture v1.0: no priorities, no middleware, no
wildcard topics, no delivery guarantees beyond "subscribers get the
event". This is the sole inter-module communication mechanism for the
project and the extension point for everything added later.

A subscriber that raises does not break the bus or starve other
subscribers for the same event; the failure is logged, not swallowed.

Handlers must return quickly: enqueue work onto the module's own internal
queue and return. publish() awaits all handlers before returning, so heavy
work done inline in a handler (TTS synthesis, inference calls, disk/network
I/O) would serialize delivery to every other subscriber of that event.
"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

Handler = Callable[[Any], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: defaultdict[Any, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: Any, handler: Handler) -> None:
        self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: Any, handler: Handler) -> None:
        handlers = self._subscribers.get(event_type)
        if handlers is not None and handler in handlers:
            handlers.remove(handler)

    async def publish(self, event_type: Any, payload: Any = None) -> None:
        handlers = list(self._subscribers.get(event_type, ()))
        if not handlers:
            return
        results = await asyncio.gather(
            *(handler(payload) for handler in handlers),
            return_exceptions=True,
        )
        cancelled: asyncio.CancelledError | None = None
        for handler, result in zip(handlers, results):
            if isinstance(result, asyncio.CancelledError):
                cancelled = cancelled or result
                continue
            if isinstance(result, BaseException):
                logger.error(
                    "Unhandled exception in event bus subscriber %r",
                    handler,
                    exc_info=result,
                )
        if cancelled is not None:
            raise cancelled
