"""Reports the data as external exactly while the external stream is read."""

from __future__ import annotations

from collections.abc import AsyncIterator

from jarvis.personal_proxy.locality import LocalityReporter, external_locality


async def external_deltas(
    stream: AsyncIterator[str], reporter: LocalityReporter
) -> AsyncIterator[str]:
    """EXTERNAL from the first read of the stream until it ends, fails, or is
    closed; LOCAL again on every one of those paths. A stream never read leaves
    the locality untouched."""
    with external_locality(reporter):
        try:
            async for delta in stream:
                yield delta
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()
