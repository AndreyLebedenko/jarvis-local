"""The restoration stage: puts the sanitizer's original values back into the
external answer, locally, one sentence at a time. A sentence without a known
placeholder passes through; any other goes to the local model and is accepted
only if a deterministic check passes, else it gets plain substitution. Nothing
is dropped, retried, or logged, and nothing here leaves the machine.

The answer is read by its own task into an in-order queue, so a slow model does
not hold the external stream (and its deadline) back."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping

from jarvis.core.config import PersonalProxySettings
from jarvis.personal_proxy.check.check_backend import CheckBackend
from jarvis.personal_proxy.external.external_limits import MAX_ANSWER_CHARS
from jarvis.personal_proxy.restoration.restoration_queue import QueueEnd, SentenceQueue
from jarvis.personal_proxy.restoration.restoration_requests import (
    build_restoration_request,
)
from jarvis.personal_proxy.restoration.restoration_result import (
    RestorationMethod,
    RestoredSentence,
)
from jarvis.personal_proxy.restoration.restoration_sentences import (
    BoundedSentenceBuffer,
)
from jarvis.personal_proxy.restoration.restoration_substitution import substitute
from jarvis.personal_proxy.restoration.restoration_validation import (
    fits_model_limits,
    restoration_is_valid,
)
from jarvis.personal_proxy.sanitize.placeholders import has_unresolved, known_entries

MAX_QUEUED_CHARS = MAX_ANSWER_CHARS
BACKEND_TIMEOUT_SECONDS = 15


async def restore_answer(
    deltas: AsyncIterator[str],
    mapping: Mapping[str, str],
    backend: CheckBackend,
    settings: PersonalProxySettings,
) -> AsyncIterator[RestoredSentence]:
    """An error of `deltas` propagates unchanged after the sentences read
    before it have been restored and yielded; the half-built sentence is
    dropped."""
    queue = SentenceQueue(MAX_QUEUED_CHARS)
    reader = asyncio.create_task(_read(deltas, queue))
    try:
        while True:
            item = await queue.get()
            if isinstance(item, QueueEnd):
                if item.error is not None:
                    raise item.error
                return
            yield await _restore_sentence(item, mapping, backend, settings)
    finally:
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)


async def _read(deltas: AsyncIterator[str], queue: SentenceQueue) -> None:
    """Always posts the end, whatever stops the input (even a BaseException),
    so the consumer can never wait for it forever."""
    buffer = BoundedSentenceBuffer()
    ending: BaseException | None = None
    try:
        async for delta in deltas:
            for sentence in buffer.feed(delta):
                await queue.put(sentence)
        last = buffer.flush()
        if last is not None:
            await queue.put(last)
    except BaseException as error:
        ending = error
    finally:
        try:
            await _close(deltas)
        finally:
            await queue.finish(ending)


async def _close(deltas: AsyncIterator[str]) -> None:
    close = getattr(deltas, "aclose", None)
    if close is not None:
        await close()


async def _restore_sentence(
    sentence: str,
    mapping: Mapping[str, str],
    backend: CheckBackend,
    settings: PersonalProxySettings,
) -> RestoredSentence:
    entries = known_entries(sentence, mapping)
    unresolved = has_unresolved(sentence, mapping)
    if not entries:
        return RestoredSentence(sentence, RestorationMethod.PASSTHROUGH, unresolved)
    restored = None
    if fits_model_limits(sentence, entries):
        restored = await _model_restoration(sentence, entries, backend, settings)
    if restored is not None:
        return RestoredSentence(restored, RestorationMethod.MODEL, unresolved)
    return RestoredSentence(
        substitute(sentence, entries), RestorationMethod.SUBSTITUTED, unresolved
    )


async def _model_restoration(
    sentence: str,
    entries: Mapping[str, str],
    backend: CheckBackend,
    settings: PersonalProxySettings,
) -> str | None:
    request = build_restoration_request(sentence, entries, settings.check_temperature)
    try:
        async with asyncio.timeout(BACKEND_TIMEOUT_SECONDS):
            reply = await backend.complete(request)
    except Exception:
        return None
    if not isinstance(reply, str):
        return None
    restored = reply.strip()
    if not restoration_is_valid(sentence, entries, restored):
        return None
    return restored
