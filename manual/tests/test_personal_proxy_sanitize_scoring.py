import json

from manual.personal_proxy.corpus import CORPUS, Verdict
from manual.personal_proxy.sanitize_scoring import (
    Totals,
    aggregate,
    decide,
    score_call,
)

PHONE = next(u for u in CORPUS if u.utterance_id == "id_phone_words")
HEARD = PHONE.text


def _reply(text, mapping=None, verdict="send"):
    return json.dumps(
        {
            "verdict": verdict,
            "reason": "",
            "sanitized_text": text,
            "mapping": mapping or {},
        },
        ensure_ascii=False,
    )


def _score(input_text, reply):
    return score_call(PHONE, "G", 1, input_text, reply, "stop", 1.0)


def test_a_span_still_in_the_output_is_a_leak():
    score = _score(HEARD, _reply(HEARD))

    assert score.recognisable == ("p1",)
    assert score.leaked == ("p1",)


def test_a_replaced_span_with_its_original_in_the_mapping_is_clean():
    mapping = {"<PHONE_1>": PHONE.spans[0].surface}

    score = _score(HEARD, _reply("Запиши мой телефон: <PHONE_1>.", mapping))

    assert score.leaked == ()
    assert (score.mapping_checked, score.mapping_errors) == (1, 0)


def test_a_replaced_span_missing_from_the_mapping_is_a_mapping_error():
    score = _score(HEARD, _reply("Запиши мой телефон: <PHONE_1>."))

    assert (score.mapping_checked, score.mapping_errors) == (1, 1)


def test_a_span_the_engine_lost_is_listed_and_cannot_leak():
    score = _score("Запиши мой телефон.", _reply("Запиши мой телефон."))

    assert score.recognisable == ()
    assert score.lost == ("p1",)
    assert score.leaked == ()
    assert score.mapping_checked == 0


def test_an_unparsable_reply_is_invalid_and_scores_nothing():
    score = _score(HEARD, "not json")

    assert not score.valid
    assert score.leaked == ()


def test_refusing_a_send_expected_utterance_is_a_false_refusal():
    score = _score(HEARD, _reply("", verdict="refuse"))

    assert score.expected_verdict is Verdict.SEND
    assert score.false_refusal


def _totals(**overrides):
    base = {
        "generations": 100,
        "valid": 100,
        "spans_recognisable": 100,
        "spans_lost": 0,
        "spans_leaked": 5,
        "mapping_checked": 100,
        "mapping_errors": 10,
        "mean_preservation": 0.7,
        "mean_input_preservation": 0.9,
        "send_expected": 100,
        "false_refusals": 5,
        "missed_refusals": 0,
        "median_seconds": 1.0,
        "p90_seconds": 2.0,
    }
    return Totals(**{**base, **overrides})


def test_all_criteria_inside_their_limits_is_go():
    assert decide(_totals()).verdict == "Go"


def test_a_leak_rate_between_the_limits_goes_to_the_owner():
    assert decide(_totals(spans_leaked=12)).verdict == "Owner"


def test_a_leak_rate_above_the_close_limit_closes_the_pass():
    assert decide(_totals(spans_leaked=20)).verdict == "Close"


def test_validity_below_ninety_percent_closes_the_pass():
    assert decide(_totals(valid=89)).verdict == "Close"


def test_aggregate_counts_only_sent_generations_in_the_leak_rate():
    leaked = _score(HEARD, _reply(HEARD))
    refused = _score(HEARD, _reply("", verdict="refuse"))

    totals = aggregate([leaked, refused])

    assert (totals.spans_recognisable, totals.spans_leaked) == (1, 1)
    assert totals.false_refusals == 1
