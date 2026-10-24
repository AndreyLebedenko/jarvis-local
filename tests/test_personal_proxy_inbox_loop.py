import asyncio

import pytest

from jarvis.personal_proxy.request.proxy_inbox import (
    ProxyInbox,
    TypedText,
    WrongLoopError,
)


async def test_a_submit_from_another_thread_is_refused_once_the_worker_runs():
    inbox = ProxyInbox(capacity=2)
    worker = asyncio.ensure_future(inbox.next_item())
    await asyncio.sleep(0)

    with pytest.raises(WrongLoopError):
        await asyncio.to_thread(inbox.submit, TypedText("from a hotkey thread"))

    inbox.submit(TypedText("from the loop"))
    assert await worker == TypedText("from the loop")


def test_the_loop_contract_is_stated_in_the_docstring():
    assert "event loop" in ProxyInbox.__doc__
    assert "run_coroutine_threadsafe" in ProxyInbox.__doc__
