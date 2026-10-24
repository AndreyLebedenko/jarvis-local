"""Runs a microphone resume to its end even when the caller is cancelled.

A resume that is cancelled halfway can leave the microphone off for good, so a
cancellation that arrives meanwhile is held back until the resume has finished
(or the time limit has passed), and then raised again."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable


def _consume(task: asyncio.Future[None]) -> None:
    if not task.cancelled():
        task.exception()


async def resume_completely(resume: Awaitable[None], limit_seconds: float) -> bool:
    """True if the resume finished without an error within the limit."""
    task = asyncio.ensure_future(resume)
    task.add_done_callback(_consume)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + limit_seconds
    cancellation: asyncio.CancelledError | None = None
    while not task.done() and loop.time() < deadline:
        try:
            await asyncio.wait({task}, timeout=max(0.0, deadline - loop.time()))
        except asyncio.CancelledError as error:
            cancellation = error
    finished = task.done() and not task.cancelled() and task.exception() is None
    if not task.done():
        task.cancel()
    if cancellation is not None:
        raise cancellation
    return finished
