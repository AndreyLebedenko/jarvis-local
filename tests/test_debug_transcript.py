"""The debug transcript: what it records, and what it must never record.

Pure tests - no live endpoint. The transcript is an exception to the
v1.6.4 content rule, so most of these assert the boundaries of that
exception rather than its contents.
"""

import base64
import json
import logging

import pytest

from jarvis.core.config import LoggingSettings
from jarvis.core.debug_transcript import (
    TRANSCRIPT_FILE_NAME,
    Exchange,
    begin_exchange,
    configure_debug_transcript,
    disable_debug_transcript,
    logger,
    media_descriptor,
    recording,
    redacted_messages,
)

WAV_BYTES = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 100
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 60


@pytest.fixture
def transcript(tmp_path):
    """Installs the sink and removes it afterwards, so a test never leaves
    the process recording."""
    path = configure_debug_transcript(
        LoggingSettings(directory=str(tmp_path), max_bytes=100000, backup_count=1)
    )
    yield path
    for handler in logger.handlers:
        handler.close()
    logger.handlers = []
    logger.setLevel(logging.NOTSET)


def records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def payload_with(messages, **extra):
    return {"model": "gemma4:12b-it-qat", "messages": messages, **extra}


def test_nothing_records_until_the_sink_is_installed():
    assert recording() is False
    assert begin_exchange(payload_with([])) is None


def test_the_sink_lands_beside_the_system_log(transcript, tmp_path):
    assert transcript == tmp_path / TRANSCRIPT_FILE_NAME
    assert recording() is True


def test_a_run_that_cannot_open_the_sink_reports_it(tmp_path):
    unwritable = tmp_path / "file-not-a-directory"
    unwritable.write_text("", encoding="utf-8")

    assert (
        configure_debug_transcript(LoggingSettings(directory=str(unwritable / "logs")))
        is None
    )


def test_the_transcript_never_reaches_the_root_logger(transcript):
    """jarvis.log promises it holds no request content, and that promise
    must survive a debug run: the transcript has its own sink and must not
    propagate into the handlers that write the system log."""
    assert logger.propagate is False


def test_media_is_described_rather_than_embedded(transcript):
    audio = base64.b64encode(WAV_BYTES).decode()
    exchange = begin_exchange(
        payload_with(
            [{"role": "user", "content": "[голосовое сообщение]", "images": [audio]}]
        )
    )

    exchange.write()

    [record] = records(transcript)
    [message] = record["request"]["messages"]
    assert "images" not in message
    assert message["media"] == [{"kind": "wav", "bytes": len(WAV_BYTES)}]
    assert audio[:32] not in transcript.read_text(encoding="utf-8")


def test_media_descriptor_names_what_it_can_and_admits_what_it_cannot():
    assert media_descriptor(base64.b64encode(WAV_BYTES).decode())["kind"] == "wav"
    assert media_descriptor(base64.b64encode(PNG_BYTES).decode())["kind"] == "png"
    assert (
        media_descriptor(base64.b64encode(b"nothing recognizable").decode())["kind"]
        == "unknown"
    )


@pytest.mark.parametrize("size", [1, 2, 3, 64, 999])
def test_the_described_byte_count_is_the_real_one(size):
    """Counted from the base64 length rather than by decoding megabytes of
    audio on a path that runs for every request."""
    encoded = base64.b64encode(b"x" * size).decode()

    assert media_descriptor(encoded)["bytes"] == size


def test_the_whole_message_list_is_recorded_including_history(transcript):
    """The gap this exists for: the 2026-07-25 investigation could not see
    what history the model was given, and history turned out to matter."""
    messages = [
        {"role": "system", "content": "You are Jarvis"},
        {"role": "user", "content": "[голосовое сообщение]"},
        {"role": "assistant", "content": "Я не могу прослушать"},
        {"role": "system", "content": "суббота, 2026-07-25T22:00"},
        {"role": "user", "content": "[голосовое сообщение]"},
    ]

    begin_exchange(payload_with(messages)).write()

    [record] = records(transcript)
    assert [message["role"] for message in record["request"]["messages"]] == [
        "system",
        "user",
        "assistant",
        "system",
        "user",
    ]
    assert record["request"]["messages"][2]["content"] == "Я не могу прослушать"


def test_the_attached_tools_are_recorded(transcript):
    tools = [{"type": "function", "function": {"name": "remember"}}]

    begin_exchange(payload_with([], tools=tools)).write()

    [record] = records(transcript)
    assert record["request"]["tools"] == tools


def test_the_answer_and_its_tool_calls_are_recorded(transcript):
    exchange = begin_exchange(payload_with([]))

    exchange.observe({"message": {"content": "Циклическая "}})
    exchange.observe({"message": {"content": "модель"}})
    exchange.observe(
        {"message": {"tool_calls": [{"function": {"name": "capture_camera_image"}}]}}
    )
    exchange.observe({"done": True, "done_reason": "stop", "eval_count": 42})
    exchange.write()

    [record] = records(transcript)
    assert record["response"]["content"] == "Циклическая модель"
    assert (
        record["response"]["tool_calls"][0]["function"]["name"]
        == "capture_camera_image"
    )
    assert record["response"]["eval_count"] == 42
    assert record["response"]["completed"] is True


def test_a_reasoning_trace_never_enters_the_transcript(transcript):
    """PROJECT.md isolates message.thinking from output, TTS, history, UI,
    and logs. Debug lifts the content rule, not that one."""
    exchange = begin_exchange(payload_with([]))

    exchange.observe({"message": {"thinking": "сначала подумаю", "content": "ответ"}})
    exchange.write()

    assert "подумаю" not in transcript.read_text(encoding="utf-8")


def test_an_unfinished_exchange_is_still_recorded(transcript):
    """A call that hangs or fails is exactly what a transcript is wanted
    for, so the record must not depend on a done chunk arriving."""
    Exchange(payload_with([{"role": "user", "content": "hi"}])).write()

    [record] = records(transcript)
    assert record["response"]["completed"] is False
    assert record["response"]["content"] == ""


def test_each_exchange_is_one_line(transcript):
    for _ in range(3):
        begin_exchange(
            payload_with([{"role": "user", "content": "многострочный\nтекст"}])
        ).write()

    assert len(transcript.read_text(encoding="utf-8").strip().splitlines()) == 3


def test_redaction_leaves_messages_without_media_untouched():
    messages = [{"role": "user", "content": "текст"}]

    assert redacted_messages(messages) == messages


# --- turning it off (review finding, 2026-07-26) ---------------------------
# The logger is module state, so "debug is off" has to be an action. Every
# case below is a way the previous run's sink could otherwise outlive the
# flag that opened it.


def test_disabling_stops_recording_and_closes_the_file(transcript):
    begin_exchange(payload_with([{"role": "user", "content": "первый прогон"}])).write()

    disable_debug_transcript()

    assert recording() is False
    assert begin_exchange(payload_with([])) is None
    assert logger.handlers == []


def test_a_second_run_without_debug_does_not_inherit_the_first_sink(tmp_path):
    """The leak this finding names: run(debug=True) then run(debug=False)
    in one process kept writing request content with nothing saying so."""
    path = configure_debug_transcript(LoggingSettings(directory=str(tmp_path)))
    begin_exchange(payload_with([{"role": "user", "content": "первый"}])).write()

    disable_debug_transcript()
    assert begin_exchange(payload_with([{"role": "user", "content": "второй"}])) is None

    assert "второй" not in path.read_text(encoding="utf-8")


def test_a_failed_configure_leaves_nothing_recording(tmp_path):
    """Otherwise the announcement says "records nothing" while writes
    continue into the previous run's file."""
    old = configure_debug_transcript(LoggingSettings(directory=str(tmp_path)))
    blocked = tmp_path / "file-not-a-directory"
    blocked.write_text("", encoding="utf-8")

    assert (
        configure_debug_transcript(LoggingSettings(directory=str(blocked / "logs")))
        is None
    )
    assert recording() is False
    assert (
        begin_exchange(payload_with([{"role": "user", "content": "после сбоя"}]))
        is None
    )
    assert "после сбоя" not in old.read_text(encoding="utf-8")


def test_a_debug_level_root_logger_alone_does_not_start_recording():
    """recording() must mean "there is a sink", not "the level allows it":
    the level is inherited, and a process that turns root to DEBUG must not
    thereby start recording request content."""
    disable_debug_transcript()
    root = logging.getLogger()
    previous = root.level
    root.setLevel(logging.DEBUG)
    try:
        assert recording() is False
    finally:
        root.setLevel(previous)


# --- one discriminant, two record kinds ------------------------------------


def test_an_exchange_record_is_discriminated_by_kind(transcript):
    begin_exchange(payload_with([{"role": "user", "content": "hi"}])).write()

    [record] = records(transcript)
    assert record["kind"] == "exchange"


def test_write_record_does_nothing_without_a_sink():
    """The same do-nothing-when-off property as begin_exchange(), for the
    generic path the utterance bridge uses directly."""
    from jarvis.core.debug_transcript import write_record

    write_record("utterance", {"peak_dbfs": -1.0})  # must not raise


def test_write_record_stamps_the_kind_and_a_timestamp(transcript):
    from jarvis.core.debug_transcript import write_record

    write_record("utterance", {"peak_dbfs": -12.5})

    [record] = records(transcript)
    assert record["kind"] == "utterance"
    assert record["peak_dbfs"] == -12.5
    assert "timestamp" in record


def test_two_record_kinds_coexist_in_one_file_without_ambiguity(transcript):
    from jarvis.core.debug_transcript import write_record

    write_record("utterance", {"peak_dbfs": -12.5})
    begin_exchange(payload_with([{"role": "user", "content": "hi"}])).write()
    write_record("utterance", {"peak_dbfs": -8.0})

    kinds = [record["kind"] for record in records(transcript)]
    assert kinds == ["utterance", "exchange", "utterance"]
