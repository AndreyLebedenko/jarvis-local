from pathlib import Path

import httpx
import pytest

from jarvis.personal_proxy.check.check_result import (
    CheckedTranscript,
    CheckSource,
    Doubt,
    DoubtKind,
    FallbackReason,
)
from manual import manual_check_transcript_check as harness


def _paths(*names):
    return [Path(f"{name}.wav") for name in names]


def test_the_required_recordings_come_first_then_the_first_others_by_name():
    available = _paths("z_last", "n_short_translate", "a_first", "m_trade_house", "b")

    chosen = harness.select_recordings(available, harness.REWRITE_CASES, 2)

    assert [path.stem for path in chosen] == [
        "n_short_translate",
        "m_trade_house",
        "a_first",
        "b",
    ]


def test_a_missing_required_recording_stops_the_run_naming_it():
    with pytest.raises(SystemExit, match="m_trade_house"):
        harness.select_recordings(_paths("n_short_translate"), harness.REWRITE_CASES, 0)


def test_a_checked_result_lists_its_text_and_each_doubt():
    result = CheckedTranscript(
        text="Позвони 8 912",
        doubts=(Doubt(DoubtKind.FRAGMENT, "8 912"),),
        source=CheckSource.CHECKED,
        would_ask=True,
    )

    lines = harness.render_result(result)

    assert "checked text: Позвони 8 912" in lines
    assert "source: checked; fallback reason: -" in lines
    assert "would_ask: True; doubts: 1" in lines
    assert "  doubt fragment '8 912'" in lines


def test_a_fallback_result_names_its_reason():
    result = CheckedTranscript(
        text="engine text",
        doubts=(Doubt(DoubtKind.REWRITE),),
        source=CheckSource.WHISPER_FALLBACK,
        would_ask=True,
        fallback_reason=FallbackReason.INVENTED_ADDRESS,
    )

    lines = harness.render_result(result)

    assert "source: whisper_fallback; fallback reason: invented_address" in lines
    assert "  doubt rewrite" in lines


def _client(handler):
    return httpx.Client(
        base_url="http://ollama.test", transport=httpx.MockTransport(handler)
    )


def _tags(*names):
    return httpx.Response(200, json={"models": [{"name": n} for n in names]})


def test_preflight_passes_when_the_server_lists_the_model():
    client = _client(lambda request: _tags("gemma4:12b"))

    assert harness.ollama_preflight(client, "http://ollama.test", "gemma4:12b") is None


def test_preflight_names_the_missing_model_and_the_pull_command():
    client = _client(lambda request: _tags("other:7b"))

    message = harness.ollama_preflight(client, "http://ollama.test", "gemma4:12b")

    assert "ollama pull gemma4:12b" in message


def test_preflight_says_so_when_the_server_does_not_answer():
    def refuse(request):
        raise httpx.ConnectError("refused")

    message = harness.ollama_preflight(
        _client(refuse), "http://ollama.test", "gemma4:12b"
    )

    assert "does not answer at http://ollama.test" in message


def test_preflight_treats_an_error_status_as_no_answer():
    client = _client(lambda request: httpx.Response(500))

    assert "does not answer" in harness.ollama_preflight(client, "http://x", "m")


async def test_the_recorder_keeps_only_the_first_reply_of_each_check():
    class Inner:
        def __init__(self):
            self.replies = ["sample", "judge", "next sample"]

        async def complete(self, request):
            return self.replies.pop(0)

    recorder = harness.RecordingBackend(Inner())

    await recorder.complete(None)
    await recorder.complete(None)
    assert recorder.first_reply == "sample"
    recorder.begin_check()
    assert recorder.first_reply is None
    await recorder.complete(None)
    assert recorder.first_reply == "next sample"
