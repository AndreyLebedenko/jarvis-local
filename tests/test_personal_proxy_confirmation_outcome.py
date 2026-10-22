import pytest

from jarvis.personal_proxy.confirmation_outcome import ExchangeOutcome


def test_only_a_confirmation_leads_to_a_send():
    sending = [outcome for outcome in ExchangeOutcome if outcome.leads_to_send]

    assert sending == [ExchangeOutcome.CONFIRMED]


@pytest.mark.parametrize(
    "name",
    ["CONFIRMED", "DECLINED", "UNCLEAR", "TIMED_OUT", "CANCELLED", "FAILED"],
)
def test_the_outcomes_are_the_agreed_set(name):
    assert name in ExchangeOutcome.__members__
    assert len(ExchangeOutcome) == 6
