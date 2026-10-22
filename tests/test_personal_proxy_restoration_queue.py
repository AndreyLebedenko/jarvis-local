import asyncio

from jarvis.personal_proxy.restoration_queue import QueueEnd, SentenceQueue


async def _completes(awaitable, seconds=0.5):
    async with asyncio.timeout(seconds):
        return await awaitable


async def test_sentences_come_out_in_order_then_the_end():
    queue = SentenceQueue(100)
    await queue.put("один")
    await queue.put("два")
    await queue.finish(None)

    assert [await queue.get(), await queue.get()] == ["один", "два"]
    assert await queue.get() == QueueEnd(None)


async def test_the_end_carries_its_error():
    queue = SentenceQueue(100)
    error = ValueError("broke")

    await queue.finish(error)

    assert (await queue.get()).error is error


async def test_a_put_waits_while_the_queued_characters_are_at_the_bound():
    queue = SentenceQueue(10)
    await queue.put("aaaaaa")
    await queue.put("bbbb")
    waiting = asyncio.ensure_future(queue.put("c"))
    await asyncio.sleep(0.05)

    assert not waiting.done()
    await queue.get()
    await _completes(waiting)


async def test_taking_a_sentence_frees_its_characters():
    queue = SentenceQueue(10)
    await queue.put("aaaaaa")
    await queue.put("bbbb")

    await queue.get()

    await _completes(queue.put("cccccc"))


async def test_a_sentence_larger_than_the_bound_is_accepted_into_an_empty_queue():
    queue = SentenceQueue(10)

    await _completes(queue.put("a" * 50))

    assert await queue.get() == "a" * 50


async def test_a_sentence_larger_than_the_bound_waits_for_a_non_empty_queue():
    queue = SentenceQueue(10)
    await queue.put("aaa")
    waiting = asyncio.ensure_future(queue.put("b" * 50))
    await asyncio.sleep(0.05)

    assert not waiting.done()
    await queue.get()
    await _completes(waiting)


async def test_the_end_is_accepted_when_the_queue_is_full():
    queue = SentenceQueue(5)
    await queue.put("aaaaa")

    await _completes(queue.finish(None))


async def test_a_get_waits_for_a_sentence():
    queue = SentenceQueue(10)
    waiting = asyncio.ensure_future(queue.get())
    await asyncio.sleep(0.05)

    assert not waiting.done()
    await queue.put("пришло")
    assert await _completes(waiting) == "пришло"
