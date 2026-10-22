import pytest

from jarvis.core.run_mode import (
    PERSONAL_PROXY_VERDICTS,
    ActionRefusal,
    ActionRefusedError,
    ControlAction,
    RefusalReason,
    RunMode,
    RunModePolicy,
    Verdict,
)

_A = ControlAction

_REFUSED_IN_PERSONAL_PROXY = {
    _A.TOGGLE_THINKING,
    _A.SET_REASONING_LEVEL,
    _A.SET_RESPONSE_MODE,
    _A.SET_MCP_ENABLED,
    _A.SET_SOLO_SESSION_ENABLED,
    _A.SET_TOOL_ENABLED,
    _A.RESET_CONTEXT,
    _A.JOURNAL_NEW_CONTEXT,
    _A.JOURNAL_FORK,
    _A.TRANSCRIPT_GENERATE,
    _A.ANNOTATION_GENERATE,
    _A.CONSOLIDATION_EXECUTE,
    _A.REPLAY,
}


def test_the_personal_proxy_has_an_explicit_verdict_for_every_action():
    assert set(PERSONAL_PROXY_VERDICTS) == set(ControlAction)


def test_the_personal_proxy_verdicts_cannot_be_changed_at_runtime():
    with pytest.raises(TypeError):
        PERSONAL_PROXY_VERDICTS[_A.JOURNAL_INPUT] = Verdict.REFUSED


def test_the_personal_proxy_refuses_exactly_the_controls_of_the_main_model():
    policy = RunModePolicy(RunMode.PERSONAL_PROXY)

    refused = {action for action in ControlAction if policy.refusal(action)}

    assert refused == _REFUSED_IN_PERSONAL_PROXY
    assert set(policy.refused_actions()) == _REFUSED_IN_PERSONAL_PROXY


@pytest.mark.parametrize("action", [_A.JOURNAL_INPUT, _A.SET_TTS_ENABLED])
def test_dock_text_and_the_speech_switch_stay_allowed(action):
    assert RunModePolicy(RunMode.PERSONAL_PROXY).verdict(action) is Verdict.ALLOWED


def test_a_refusal_in_the_personal_proxy_names_its_own_reason():
    policy = RunModePolicy(RunMode.PERSONAL_PROXY)

    with pytest.raises(ActionRefusedError) as raised:
        policy.check(_A.TOGGLE_THINKING)

    assert raised.value.refusal == ActionRefusal(
        _A.TOGGLE_THINKING, RefusalReason.PERSONAL_PROXY
    )
    assert RefusalReason.PERSONAL_PROXY.value == "personal_proxy"
