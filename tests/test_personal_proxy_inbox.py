import asyncio
import time

import pytest

from jarvis.personal_proxy.request.proxy_inbox import (
    InboxFullError,
    ProxyInbox,
    TypedText,
    Utterance,
)


async def test_items_come_out_in_the_order_they_went_in():
    inbox = ProxyInbox(capacity=4)
    inbox.submit(TypedText("first"))
    inbox.submit(Utterance(b"wav"))

    assert await inbox.next_item() == TypedText("first")
    assert await inbox.next_item() == Utterance(b"wav")


async def test_next_item_waits_for_an_item():
    inbox = ProxyInbox(capacity=1)
    waiting = asyncio.ensure_future(inbox.next_item())
    await asyncio.sleep(0.01)
    assert not waiting.done()

    inbox.submit(TypedText("late"))

    async with asyncio.timeout(1):
        assert await waiting == TypedText("late")


async def test_submit_returns_at_once_while_the_worker_is_busy():
    inbox = ProxyInbox(capacity=8)
    worker_release = asyncio.Event()

    async def slow_worker():
        await inbox.next_item()
        await worker_release.wait()

    worker = asyncio.ensure_future(slow_worker())
    inbox.submit(TypedText("taken by the worker"))
    await asyncio.sleep(0.01)

    started = time.perf_counter()
    for _ in range(5):
        inbox.submit(TypedText("queued"))

    assert time.perf_counter() - started < 0.05
    worker_release.set()
    await worker


async def test_a_full_inbox_raises_a_typed_error_and_never_blocks():
    inbox = ProxyInbox(capacity=1)
    inbox.submit(TypedText("kept"))

    with pytest.raises(InboxFullError):
        inbox.submit(TypedText("dropped"))

    assert await inbox.next_item() == TypedText("kept")


async def test_a_slot_freed_by_the_worker_can_be_used_again():
    inbox = ProxyInbox(capacity=1)
    inbox.submit(TypedText("one"))
    await inbox.next_item()

    inbox.submit(TypedText("two"))

    assert await inbox.next_item() == TypedText("two")


def test_an_item_that_is_neither_text_nor_an_utterance_is_refused():
    inbox = ProxyInbox(capacity=1)

    with pytest.raises(TypeError):
        inbox.submit("plain string")


def test_a_capacity_below_one_is_refused():
    with pytest.raises(ValueError):
        ProxyInbox(capacity=0)


def test_items_and_errors_do_not_show_their_content():
    secret = "marina@example.org"
    inbox = ProxyInbox(capacity=1)
    inbox.submit(TypedText(secret))
    with pytest.raises(InboxFullError) as error:
        inbox.submit(TypedText(secret))

    for shown in (
        repr(TypedText(secret)),
        str(TypedText(secret)),
        repr(Utterance(secret.encode())),
        repr(inbox),
        str(error.value),
        repr(error.value),
    ):
        assert secret not in shown
