import asyncio

import pytest

from jarvis.audio.input import MicrophoneCaptureFailed, UtteranceChunk
from manual.manual_record_personal_proxy_corpus import LiveTakeSource, parse_args


def _chunk(data=b"wav"):
    return UtteranceChunk(wav_bytes=data, start_seconds=0.0, end_seconds=1.0)


def test_next_take_returns_the_chunk_that_arrives_after_the_call():
    async def scenario():
        source = LiveTakeSource()
        await source.on_chunk(_chunk(b"stale"))
        task = asyncio.create_task(source.next_take(1.0))
        await asyncio.sleep(0.05)
        await source.on_chunk(_chunk(b"fresh"))
        return await task

    assert asyncio.run(scenario()) == b"fresh"


def test_next_take_times_out_with_none():
    assert asyncio.run(LiveTakeSource().next_take(0.05)) is None


def test_a_capture_failure_is_raised_instead_of_waiting_forever():
    async def scenario():
        source = LiveTakeSource()
        await source.on_failure(MicrophoneCaptureFailed(reason="device gone"))
        return await source.next_take(0.05)

    with pytest.raises(RuntimeError, match="device gone"):
        asyncio.run(scenario())


def test_cli_accepts_repeated_redo_ids_and_a_custom_directory():
    args = parse_args(["--out", "x", "--redo", "a", "--redo", "b"])

    assert (str(args.out), args.redo) == ("x", ["a", "b"])
