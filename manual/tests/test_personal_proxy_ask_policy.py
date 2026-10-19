from manual.personal_proxy.ask_policy import (
    AskResult,
    covers,
    differing_items,
    evaluate_rule,
    weak_words,
)
from manual.personal_proxy.confidence_report import Signals

NAMES = ("S1", "S2", "S3a", "J3")


def _signals(subject, bad, **scores):
    return Signals(subject, bad, {**dict.fromkeys(NAMES, 0.0), **scores})


def test_rule_counts_asked_caught_and_missed_recordings():
    rows = [
        _signals("a", True, J3=1.0),
        _signals("b", True),
        _signals("c", False, J3=2.0),
        _signals("d", False),
    ]

    result = evaluate_rule("J3", (("J3", 1.0),), rows)

    assert (result.asked, result.total) == (2, 4)
    assert (result.caught, result.bad) == (1, 2)
    assert result.missed == ("b",)


def test_ask_rate_budget_is_a_quarter_of_the_requests():
    inside = AskResult("x", 1, 4, 0, 0, ())
    outside = AskResult("x", 2, 4, 0, 0, ())

    assert inside.within_budget
    assert not outside.within_budget


def test_a_doubt_covers_the_error_when_it_quotes_the_wrong_fragment():
    assert covers(["адрес alex.smirnov.92@sobakapochta.ru"], "v2_email_underscore")
    assert not covers(["паспорт серия 4508"], "v2_email_underscore")


def test_a_phrase_without_known_keys_is_never_covered():
    assert not covers(["что угодно"], "unknown_phrase")


def test_differing_items_are_those_not_all_samples_agree_on():
    samples = [frozenset({"a", "b"}), frozenset({"a", "c"}), frozenset({"a", "b"})]

    assert differing_items(samples) == ["b", "c"]


def test_weak_words_are_below_the_threshold_and_stripped():
    assert weak_words([(" Привет", 0.9), (" Майкл", 0.2)]) == ["Майкл"]
