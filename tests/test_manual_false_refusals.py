"""The pure part of the false refusal measurement: the corpus and the report.
The live run is the owner's (manual/sanitize-false-refusals-handoff.md)."""

import re

import pytest

from jarvis.personal_proxy.sanitize.sanitize_result import (
    SanitizeFailure,
    SanitizeFailureClass,
    SanitizeResult,
    SanitizeVerdict,
)
from manual.personal_proxy.false_refusals import (
    ARM_OFF,
    ARM_ON,
    CORPUS,
    Trial,
    outcome_label,
    render_report,
)

SEND = SanitizeResult(SanitizeVerdict.SEND, "", "text", {})
REFUSED = SanitizeResult(SanitizeVerdict.REFUSE, "a reason", "", {})


def test_the_corpus_has_about_forty_unique_harmless_requests_in_both_languages():
    ids = [item.item_id for item in CORPUS]

    assert 36 <= len(CORPUS) <= 44
    assert len(set(ids)) == len(ids)
    assert any(item.text.isascii() for item in CORPUS)
    assert any(not item.text.isascii() for item in CORPUS)


def test_the_corpus_covers_the_origin_cases_and_short_and_long_requests():
    texts = [item.text for item in CORPUS]

    assert "tell briefly what a relay is" in texts
    assert any("21 October" in text for text in texts)
    assert min(len(text) for text in texts) < 30
    assert max(len(text) for text in texts) > 200


def test_no_corpus_request_has_a_long_digit_run():
    assert all(not re.search(r"\d{4}", item.text) for item in CORPUS)


@pytest.mark.parametrize(
    ("result", "label"),
    [
        (SEND, "send"),
        (REFUSED, "refused"),
        (SanitizeFailure(SanitizeFailureClass.NO_JSON), "no_json"),
        (
            SanitizeFailure(SanitizeFailureClass.UNEXPECTED_REFUSAL),
            "unexpected_refusal",
        ),
    ],
)
def test_an_outcome_label_is_the_verdict_or_the_failure_class(result, label):
    assert outcome_label(result) == label


def _trials():
    return [
        Trial("H01", ARM_ON, 1, "send"),
        Trial("H01", ARM_OFF, 1, "send"),
        Trial("H02", ARM_ON, 2, "send"),
        Trial("H02", ARM_OFF, 1, "unexpected_refusal"),
        Trial("H03", ARM_ON, 2, "no_json"),
        Trial("H03", ARM_OFF, 1, "no_json"),
        Trial("H03", ARM_ON, 2, "no_json"),
        Trial("H04", ARM_OFF, 1, "bad_placeholder"),
    ]


def test_the_report_counts_outcomes_per_arm():
    report = render_report(_trials(), topics_present=False)

    on_section = report.split(ARM_OFF)[0]
    assert "send: 2" in on_section
    assert "no_json: 2" in on_section


def test_the_report_counts_retried_and_rescued_requests_for_the_retry_arm():
    report = render_report(_trials(), topics_present=False)

    assert "retried: 3" in report
    assert "rescued by the retry: 1" in report


def test_the_report_lists_example_ids_of_requests_that_did_not_send():
    report = render_report(_trials(), topics_present=False)

    assert "H03" in report
    assert "H02" in report


def test_the_report_names_whether_topics_were_present():
    assert "topics: none" in render_report(_trials(), topics_present=False)
    assert "topics: present" in render_report(_trials(), topics_present=True)


def test_the_report_has_ids_and_counts_but_no_request_text():
    report = render_report(_trials(), topics_present=False)

    for item in CORPUS:
        assert item.text not in report
