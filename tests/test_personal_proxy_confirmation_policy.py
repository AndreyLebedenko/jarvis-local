from jarvis.core.config import PersonalProxySettings
from jarvis.personal_proxy.check.check_result import (
    CheckedTranscript,
    CheckSource,
    Doubt,
    DoubtKind,
)
from jarvis.personal_proxy.confirmation.confirmation_policy import should_ask


def _checked(would_ask, doubts=()):
    return CheckedTranscript(
        text="x", doubts=tuple(doubts), source=CheckSource.CHECKED, would_ask=would_ask
    )


def test_a_transcript_the_check_wants_asked_about_is_asked():
    assert should_ask(_checked(True, [Doubt(DoubtKind.FRAGMENT, "f")])) is True


def test_a_transcript_without_a_reason_to_doubt_is_not_asked():
    assert should_ask(_checked(False)) is False


def test_the_threshold_is_the_one_the_check_applied_not_a_second_one():
    assert PersonalProxySettings().doubt_min_listed == 1
    one_doubt_below_a_higher_threshold = _checked(
        False, [Doubt(DoubtKind.FRAGMENT, "f")]
    )

    assert should_ask(one_doubt_below_a_higher_threshold) is False
