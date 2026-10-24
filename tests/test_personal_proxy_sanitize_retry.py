"""One retry of the local sanitize call: when it applies, when it must not, and
that the second outcome is final."""

import asyncio
import json
import logging

import pytest
from _backend_fakes import FakeBackend

from jarvis.core.config import PersonalProxySettings
from jarvis.personal_proxy import sanitize as sanitize_module
from jarvis.personal_proxy.check_result import CheckedTranscript, CheckSource
from jarvis.personal_proxy.sanitize import SANITIZE_RETRIES, sanitize
from jarvis.personal_proxy.sanitize_result import (
    SanitizeFailure,
    SanitizeFailureClass,
    SanitizeResult,
    SanitizeVerdict,
)

SETTINGS = PersonalProxySettings()
TRANSCRIPT = "tell briefly what a relay is"
TOPICS = "- the secret diagnosis of the user"
NO_TOPICS = ""


def _reply(**changes):
    document = {
        "verdict": "send",
        "reason": "",
        "sanitized_text": TRANSCRIPT,
        "mapping": {},
    } | changes
    return json.dumps(document)


GOOD = _reply()
REFUSAL = _reply(verdict="refuse", reason="DATE", sanitized_text="")
NO_SPEECH = _reply(verdict="refuse", reason="no speech", sanitized_text="")
TOPIC_REFUSAL = _reply(verdict="refuse", reason="a diagnosis", sanitized_text="")
NO_JSON = "I cannot do that"
MALFORMED = {
    SanitizeFailureClass.BAD_PLACEHOLDER: _reply(mapping={"bad": "x"}),
    SanitizeFailureClass.EMPTY_SANITIZED_TEXT: _reply(sanitized_text=""),
    SanitizeFailureClass.EMPTY_MAPPING_VALUE: _reply(mapping={"<PERSON_1>": " "}),
    SanitizeFailureClass.NO_JSON: NO_JSON,
    SanitizeFailureClass.EXTRA_PROSE: "Here: " + GOOD,
    SanitizeFailureClass.MISSING_FIELD: json.dumps({"verdict": "send"}),
    SanitizeFailureClass.WRONG_TYPE: json.dumps([1]),
    SanitizeFailureClass.BAD_VERDICT: _reply(verdict="maybe"),
}


async def _run(*replies, topics=NO_TOPICS):
    backend = FakeBackend(*replies)
    checked = CheckedTranscript(TRANSCRIPT, (), CheckSource.CHECKED, False)
    return await sanitize(checked, topics, backend, SETTINGS), backend


def test_the_retry_count_is_one():
    assert SANITIZE_RETRIES == 1


@pytest.mark.parametrize("failure", list(MALFORMED))
async def test_a_malformed_first_answer_is_retried_once(failure):
    result, backend = await _run(MALFORMED[failure], GOOD)

    assert len(backend.requests) == 2
    assert isinstance(result, SanitizeResult)
    assert result.verdict is SanitizeVerdict.SEND


@pytest.mark.parametrize("topics", [NO_TOPICS, TOPICS])
async def test_a_malformed_answer_is_retried_with_or_without_topics(topics):
    _, backend = await _run(NO_JSON, GOOD, topics=topics)

    assert len(backend.requests) == 2


async def test_a_topicless_refusal_is_retried_once_and_a_valid_send_is_used():
    result, backend = await _run(REFUSAL, GOOD)

    assert len(backend.requests) == 2
    assert result == SanitizeResult(SanitizeVerdict.SEND, "", TRANSCRIPT, {})


async def test_the_retried_request_is_identical_to_the_first():
    _, backend = await _run(REFUSAL, GOOD)

    assert backend.requests[1] == backend.requests[0]


async def test_a_second_topicless_refusal_is_a_typed_unexpected_refusal():
    result, backend = await _run(REFUSAL, REFUSAL)

    assert len(backend.requests) == 2
    assert result == SanitizeFailure(SanitizeFailureClass.UNEXPECTED_REFUSAL)


async def test_a_refusal_then_a_malformed_answer_reports_the_malformed_class():
    result, backend = await _run(REFUSAL, NO_JSON)

    assert len(backend.requests) == 2
    assert result == SanitizeFailure(SanitizeFailureClass.NO_JSON)


async def test_a_malformed_answer_then_a_refusal_without_topics_is_unexpected():
    result, _ = await _run(NO_JSON, REFUSAL)

    assert result == SanitizeFailure(SanitizeFailureClass.UNEXPECTED_REFUSAL)


async def test_a_second_failure_is_reported_with_its_own_class():
    result, backend = await _run(NO_JSON, MALFORMED[SanitizeFailureClass.BAD_VERDICT])

    assert len(backend.requests) == 2
    assert result == SanitizeFailure(SanitizeFailureClass.BAD_VERDICT)


async def test_a_second_backend_failure_is_reported_as_backend_failed():
    result, backend = await _run(NO_JSON, RuntimeError())

    assert len(backend.requests) == 2
    assert result == SanitizeFailure(SanitizeFailureClass.BACKEND_FAILED)


async def test_there_is_never_a_third_call():
    result, backend = await _run(REFUSAL, NO_JSON, GOOD)

    assert len(backend.requests) == 2
    assert isinstance(result, SanitizeFailure)


@pytest.mark.parametrize("error", [RuntimeError("x"), TimeoutError()])
async def test_an_unreachable_backend_is_not_retried(error):
    result, backend = await _run(error, GOOD)

    assert len(backend.requests) == 1
    assert result == SanitizeFailure(SanitizeFailureClass.BACKEND_FAILED)


async def test_a_reply_that_is_not_text_is_not_retried():
    result, backend = await _run(None, GOOD)

    assert len(backend.requests) == 1
    assert result == SanitizeFailure(SanitizeFailureClass.BACKEND_FAILED)


async def test_a_refusal_with_topics_present_is_final_and_not_retried():
    result, backend = await _run(TOPIC_REFUSAL, GOOD, topics=TOPICS)

    assert len(backend.requests) == 1
    assert result == SanitizeResult(SanitizeVerdict.REFUSE, "a diagnosis", "", {})


async def test_a_no_speech_refusal_is_not_retried():
    result, backend = await _run(NO_SPEECH, GOOD)

    assert len(backend.requests) == 1
    assert result == SanitizeResult(SanitizeVerdict.REFUSE, "no speech", "", {})


async def test_a_valid_send_is_not_retried():
    result, backend = await _run(GOOD, GOOD)

    assert len(backend.requests) == 1
    assert isinstance(result, SanitizeResult)


async def test_an_empty_reply_is_retried_once():
    result, backend = await _run("   ", GOOD)

    assert len(backend.requests) == 2
    assert isinstance(result, SanitizeResult)


async def test_two_empty_replies_are_reported_as_empty():
    result, backend = await _run("", "  ")

    assert len(backend.requests) == 2
    assert result == SanitizeFailure(SanitizeFailureClass.EMPTY)


BLANK_TOPICS = ["  \n", "\ufeff", "\u200b", "\n\t \n"]


@pytest.mark.parametrize("topics", BLANK_TOPICS)
async def test_blank_topics_count_as_no_topics_so_a_refusal_is_retried(topics):
    result, backend = await _run(REFUSAL, GOOD, topics=topics)

    assert len(backend.requests) == 2
    assert isinstance(result, SanitizeResult)
    assert result.verdict is SanitizeVerdict.SEND


@pytest.mark.parametrize("topics", BLANK_TOPICS)
async def test_blank_topics_and_two_refusals_are_an_unexpected_refusal(topics):
    result, backend = await _run(REFUSAL, REFUSAL, topics=topics)

    assert len(backend.requests) == 2
    assert result == SanitizeFailure(SanitizeFailureClass.UNEXPECTED_REFUSAL)


async def test_the_prompt_and_the_retry_rule_agree_on_blank_topics():
    _, backend = await _run(GOOD, topics="  \n")

    assert "Sensitive topics" not in backend.requests[0].system


@pytest.mark.parametrize("reason", ["No speech", " no speech ", "NO SPEECH\n"])
async def test_a_no_speech_reason_in_any_case_or_spacing_is_not_retried(reason):
    refusal = _reply(verdict="refuse", reason=reason, sanitized_text="")

    result, backend = await _run(refusal, GOOD)

    assert len(backend.requests) == 1
    assert isinstance(result, SanitizeResult)
    assert result.verdict is SanitizeVerdict.REFUSE


async def test_a_cancelled_backend_call_propagates_and_is_not_retried():
    backend = FakeBackend(asyncio.CancelledError(), GOOD)
    checked = CheckedTranscript(TRANSCRIPT, (), CheckSource.CHECKED, False)

    with pytest.raises(asyncio.CancelledError):
        await sanitize(checked, NO_TOPICS, backend, SETTINGS)

    assert len(backend.requests) == 1


async def test_the_retry_count_constant_decides_the_number_of_calls(monkeypatch):
    monkeypatch.setattr(sanitize_module, "SANITIZE_RETRIES", 0)

    result, backend = await _run(REFUSAL, GOOD)

    assert len(backend.requests) == 1
    assert result == SanitizeFailure(SanitizeFailureClass.UNEXPECTED_REFUSAL)


async def test_the_empty_transcript_still_makes_no_call():
    backend = FakeBackend(GOOD)
    checked = CheckedTranscript("  ", (), CheckSource.CHECKED, False)

    result = await sanitize(checked, NO_TOPICS, backend, SETTINGS)

    assert backend.requests == []
    assert result.reason == "no speech"


async def test_nothing_of_the_transcript_or_the_model_output_is_logged_or_shown(
    caplog,
):
    leaking = _reply(verdict="refuse", reason="LEAKED-REASON", sanitized_text="")
    caplog.set_level(logging.DEBUG)

    result, _ = await _run(leaking, leaking)

    assert isinstance(result, SanitizeFailure)
    shown = f"{result!s} {result!r} {caplog.text}"
    assert "LEAKED-REASON" not in shown
    assert TRANSCRIPT not in shown
    assert caplog.records == []
